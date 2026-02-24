from __future__ import annotations

import asyncio
import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import discord

from app.services.discord_embed_utils import FIELD_MAX, safe_add_field, safe_set_description
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)
ROME = ZoneInfo("Europe/Rome")


@dataclass
class InactiveCandidate:
    member: discord.Member
    last_message_ts: str | None
    last_channel_id: str | None
    last_message_id: str | None
    count_in_window: int
    days_inactive: int
    policy: dict[str, Any]


class InactivityActionsView(discord.ui.View):
    def __init__(self, service: "InactiveMembersModerationService", guild_id: str, mod_channel_id: str, timeout: float = 600) -> None:
        super().__init__(timeout=timeout)
        self._service = service
        self._guild_id = guild_id
        self._mod_channel_id = mod_channel_id
        self.message: discord.Message | None = None

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                logger.debug("inactive view timeout edit failed", exc_info=True)

    @discord.ui.button(label="🔔 Invia reminder", style=discord.ButtonStyle.primary)
    async def reminder(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await interaction.response.defer(ephemeral=True)
        result = await self._service.execute_reminders(self._guild_id)
        await interaction.followup.send(embed=self._service.build_action_embed("✅ AZIONE COMPLETATA · Reminder", result), ephemeral=True)

    @discord.ui.button(label="🚪 Caccia + ban temporaneo", style=discord.ButtonStyle.danger)
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        await interaction.response.defer(ephemeral=True)
        result = await self._service.execute_kick_pipeline(self._guild_id, require_grace=False)
        await interaction.followup.send(embed=self._service.build_action_embed("✅ AZIONE COMPLETATA · Caccia", result), ephemeral=True)

    @discord.ui.button(label="❌ Annulla", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(view=self)
        embed = discord.Embed(title="❌ Annullato", description="Azione manuale inattivi annullata.", color=0x808080)
        await interaction.followup.send(embed=embed, ephemeral=True)


class InactiveMembersModerationService:
    def __init__(self, database: DatabaseService, bot: discord.Client) -> None:
        self._database = database
        self._bot = bot
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._unban_loop())

    async def _unban_loop(self) -> None:
        await self._bot.wait_until_ready()
        while True:
            try:
                await self._run_due_unbans()
            except Exception:
                logger.exception("inactive moderation unban tick failed")
            await asyncio.sleep(60)

    async def _run_due_unbans(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        rows = await self._database.list_due_temp_unbans(now_iso)
        for row in rows:
            guild = self._bot.get_guild(int(row["guild_id"]))
            if guild is None:
                continue
            user_id = int(row["user_id"])
            try:
                await guild.unban(discord.Object(id=user_id), reason="Scadenza ban temporaneo inattività")
                await self._database.remove_temp_ban(str(guild.id), str(user_id))
                logger.info("inactive moderation: unbanned user=%s guild=%s", user_id, guild.id)
            except Exception:
                logger.warning("inactive moderation: failed unban user=%s guild=%s", user_id, guild.id, exc_info=True)

    async def _get_config(self, guild_id: str) -> dict[str, Any] | None:
        row = await self._database.get_inactivity_config(guild_id)
        if row is None:
            return None
        data = dict(row)
        data["excluded_role_ids"] = self._parse_json_list(data.get("excluded_role_ids_json"))
        data["default_policy"] = self._parse_policy_json(data.get("default_policy_json"))
        return data

    @staticmethod
    def _parse_json_list(raw: Any) -> set[int]:
        try:
            values = json.loads(raw or "[]")
            return {int(v) for v in values}
        except Exception:
            return set()

    @staticmethod
    def _parse_policy_json(raw: Any) -> dict[str, Any]:
        default = {"inactive_days": 30, "window_days": 30, "min_messages": 1, "mode": "OR", "min_account_age_days": 0}
        try:
            if raw is None:
                return default
            data = json.loads(str(raw))
            default.update(data)
        except Exception:
            pass
        default["mode"] = str(default.get("mode", "OR")).upper()
        return default

    async def _policy_for_member(self, guild_id: str, member: discord.Member, default_policy: dict[str, Any]) -> dict[str, Any]:
        rows = await self._database.list_inactivity_role_policies(guild_id)
        selected: tuple[int, dict[str, Any]] | None = None
        member_roles = {str(r.id) for r in member.roles}
        for row in rows:
            if str(row["role_id"]) not in member_roles:
                continue
            policy = self._parse_policy_json(row["policy_json"])
            priority = int(row["priority"])
            if selected is None or priority > selected[0]:
                selected = (priority, policy)
        return selected[1] if selected else dict(default_policy)

    def _is_inactive(self, *, days_inactive: int, count_in_window: int, policy: dict[str, Any]) -> bool:
        cond_days = days_inactive >= int(policy.get("inactive_days", 30))
        cond_msgs = count_in_window < int(policy.get("min_messages", 1))
        mode = str(policy.get("mode", "OR")).upper()
        return cond_days and cond_msgs if mode == "AND" else cond_days or cond_msgs

    async def scan_inactive_members(self, guild_id: str) -> tuple[list[InactiveCandidate], int, dict[str, Any]]:
        guild = self._bot.get_guild(int(guild_id))
        if guild is None:
            return [], 0, {}
        cfg = await self._get_config(guild_id)
        if cfg is None:
            return [], 0, {}

        excluded_roles = cfg["excluded_role_ids"]
        default_policy = cfg["default_policy"]
        last_map = await self._database.fetch_last_message_info_by_user_guild(guild_id)
        max_window_days = int(default_policy.get("window_days", 30))
        role_rows = await self._database.list_inactivity_role_policies(guild_id)
        for row in role_rows:
            p = self._parse_policy_json(row["policy_json"])
            max_window_days = max(max_window_days, int(p.get("window_days", 30)))
        window_start = (datetime.now(timezone.utc) - timedelta(days=max_window_days)).isoformat()
        count_map = await self._database.fetch_message_counts_by_user_since(guild_id, window_start)

        candidates: list[InactiveCandidate] = []
        considered = 0
        now = datetime.now(timezone.utc)
        for member in guild.members:
            if member.bot:
                continue
            if excluded_roles.intersection({r.id for r in member.roles}):
                continue
            policy = await self._policy_for_member(guild_id, member, default_policy)
            min_age = int(policy.get("min_account_age_days", 0))
            if min_age > 0:
                created_at = member.created_at if member.created_at.tzinfo else member.created_at.replace(tzinfo=timezone.utc)
                if (now - created_at).days < min_age:
                    continue

            considered += 1
            last_info = last_map.get(member.id)
            last_ts = last_info.get("ts") if last_info else None
            last_channel_id = last_info.get("channel_id") if last_info else None
            last_message_id = last_info.get("message_id") if last_info else None
            if last_ts:
                try:
                    last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    days = max(0, int((now - last_dt).total_seconds() // 86400))
                except Exception:
                    days = 9999
            else:
                days = 9999
            win_days = int(policy.get("window_days", 30))
            member_window_start = (now - timedelta(days=win_days)).isoformat()
            # approximate via full-window map when policy differs: fallback to precise query only if needed
            count = count_map.get(member.id, 0)
            if win_days != max_window_days:
                per_member_counts = await self._database.fetch_message_counts_by_user_since(guild_id, member_window_start)
                count = per_member_counts.get(member.id, 0)
            if self._is_inactive(days_inactive=days, count_in_window=count, policy=policy):
                candidates.append(
                    InactiveCandidate(
                        member=member,
                        last_message_ts=last_ts,
                        last_channel_id=last_channel_id,
                        last_message_id=last_message_id,
                        count_in_window=count,
                        days_inactive=days,
                        policy=policy,
                    )
                )

        return candidates, considered, cfg

    @staticmethod
    def _parse_last_message_dt(ts: str | None) -> datetime | None:
        if not ts:
            return None
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    @classmethod
    def _inactive_sort_key(cls, candidate: InactiveCandidate) -> tuple[int, datetime]:
        dt = cls._parse_last_message_dt(candidate.last_message_ts)
        if dt is None:
            return (0, datetime.min.replace(tzinfo=timezone.utc))
        return (1, dt)

    @classmethod
    def _format_inactive_preview_line(cls, candidate: InactiveCandidate) -> str:
        dt = cls._parse_last_message_dt(candidate.last_message_ts)
        if dt is None:
            return f"• {candidate.member.mention} — ({candidate.count_in_window} msg) | 💬 Ultimo: mai"
        if not candidate.last_channel_id or not candidate.last_message_id:
            return f"• {candidate.member.mention} — ({candidate.count_in_window} msg) | 💬 Ultimo: mai"
        local = cls._to_rome(dt)
        last_fmt = local.strftime("%d/%m %H:%M")
        jump_url = (
            f"https://discord.com/channels/{candidate.member.guild.id}/{candidate.last_channel_id}/{candidate.last_message_id}"
        )
        return (
            f"• {candidate.member.mention} — ({candidate.count_in_window} msg) | "
            f"💬 Ultimo: [{last_fmt}]({jump_url}) 🕒 {candidate.days_inactive}g fa"
        )

    def _format_policy_default(self, policy: dict[str, Any]) -> str:
        mode = str(policy.get("mode", "OR")).upper()
        return (
            f"• Inattività: **{policy.get('inactive_days', 30)} giorni**\n"
            f"• Finestra analisi: **{policy.get('window_days', 30)} giorni**\n"
            f"• Min messaggi: **{policy.get('min_messages', 1)}**\n"
            f"• Logica: **{mode}**\n"
            "  ↳ OR: basta 1 condizione (pochi msg OPPURE assenza lunga)\n"
            "  ↳ AND: servono entrambe (pochi msg E assenza lunga)"
        )

    def _format_role_policies(self, guild: discord.Guild, rows: list[Any]) -> str:
        if not rows:
            return "• Nessuna policy ruolo configurata."
        lines: list[str] = []
        for row in rows[:8]:
            policy = self._parse_policy_json(row["policy_json"])
            role_id = int(str(row["role_id"]))
            role = guild.get_role(role_id)
            role_label = role.mention if role else f"ruolo {role_id}"
            lines.append(
                f"• **{role_label}** (prio {int(row['priority'])}): inattività {policy.get('inactive_days', 30)}g · "
                f"finestra {policy.get('window_days', 30)}g · min {policy.get('min_messages', 1)} · {str(policy.get('mode', 'OR')).upper()}"
            )
        if len(rows) > 8:
            lines.append(f"• …altre {len(rows) - 8} policy ruolo")
        return "\n".join(lines)

    async def handle_post_activity_report(self, guild_id: str, mod_channel_id: str) -> None:
        cfg = await self._get_config(guild_id)
        if not cfg or not bool(cfg.get("enabled")):
            return
        guild = self._bot.get_guild(int(guild_id))
        channel = self._bot.get_channel(int(mod_channel_id))
        if guild is None or not isinstance(channel, discord.abc.Messageable):
            return
        await self.post_manual_panel(guild_id, mod_channel_id)
        if bool(cfg.get("auto_enabled")):
            reminder_stats = await self.execute_reminders(guild_id)
            kick_stats = await self.execute_kick_pipeline(guild_id, require_grace=True)
            await channel.send(embed=self.build_action_embed("🤖 Auto inattivi completata", reminder_stats, kick_stats))

    async def post_manual_panel(self, guild_id: str, mod_channel_id: str) -> None:
        guild = self._bot.get_guild(int(guild_id))
        channel = self._bot.get_channel(int(mod_channel_id))
        if guild is None or not isinstance(channel, discord.abc.Messageable):
            return
        inactive, considered, cfg = await self.scan_inactive_members(guild_id)
        policy = cfg.get("default_policy", {}) if cfg else {}
        role_policy_rows = await self._database.list_inactivity_role_policies(guild_id)

        embed = discord.Embed(title="✏️ INATTIVI (SERVER-WIDE)", colour=discord.Colour.blue())
        safe_add_field(embed, name="Membri analizzati", value=str(considered), inline=True)
        safe_add_field(embed, name="Inattivi trovati", value=str(len(inactive)), inline=True)
        safe_add_field(embed, name="📄 Policy di base", value=self._format_policy_default(policy), inline=False)
        safe_add_field(embed, name="🏷️ Policy per ruoli", value=self._format_role_policies(guild, role_policy_rows), inline=False)

        ordered = sorted(inactive, key=self._inactive_sort_key)
        all_lines = [self._format_inactive_preview_line(candidate) for candidate in ordered]
        preview_lines: list[str] = []
        extra_lines: list[str] = []
        preview_limit = 15
        current_len = 0
        for idx, line in enumerate(all_lines):
            if idx >= preview_limit:
                extra_lines.append(line)
                continue
            add_len = len(line) + (1 if preview_lines else 0)
            if current_len + add_len > FIELD_MAX:
                extra_lines.extend(all_lines[idx:])
                break
            preview_lines.append(line)
            current_len += add_len

        if preview_lines:
            preview_value = "\n".join(preview_lines)
        else:
            preview_value = "Nessun inattivo."

        if extra_lines:
            summary_line = f"+ altri {len(extra_lines)} inattivi… (vedi allegato .txt)"
            if preview_lines:
                summary_add = len(summary_line) + 1
                while preview_lines and (current_len + summary_add) > FIELD_MAX:
                    moved = preview_lines.pop()
                    extra_lines.insert(0, moved)
                    current_len = len("\n".join(preview_lines)) if preview_lines else 0
                if preview_lines:
                    preview_lines.append(summary_line)
                    preview_value = "\n".join(preview_lines)
                else:
                    preview_value = summary_line[:FIELD_MAX]
            else:
                preview_value = summary_line[:FIELD_MAX]

        embed.add_field(name="Preview inattivi", value=preview_value, inline=False)

        extra_file: discord.File | None = None
        if extra_lines:
            ts_name = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"inattivi_extra_{ts_name}.txt"
            payload = "\n".join(extra_lines).encode("utf-8")
            extra_file = discord.File(io.BytesIO(payload), filename=filename)

        view = InactivityActionsView(self, guild_id, mod_channel_id)
        if extra_file is not None:
            message = await channel.send(embed=embed, view=view, file=extra_file)
        else:
            message = await channel.send(embed=embed, view=view)
        view.message = message

    def _render_template(self, template: str, *, member: discord.Member, guild: discord.Guild, days_inactive: int, policy: dict[str, Any], cfg: dict[str, Any]) -> str:
        base = template or ""
        return base.format(
            user=member.mention,
            username=member.display_name,
            server=guild.name,
            days_inactive=days_inactive,
            window_days=policy.get("window_days", 30),
            rejoin_link=cfg.get("invite_url") or "",
            grace_days=cfg.get("grace_days_after_reminder", 7),
        )

    async def execute_reminders(self, guild_id: str) -> dict[str, Any]:
        inactive, _, cfg = await self.scan_inactive_members(guild_id)
        guild = self._bot.get_guild(int(guild_id))
        if guild is None or not cfg:
            return {"dm_ok": 0, "dm_fail": 0, "errors": []}
        now = datetime.now(timezone.utc)
        cooldown = int(cfg.get("reminder_cooldown_days", 14))
        template = cfg.get("dm_reminder_template") or "Ciao {user}, sei inattivo su {server} da {days_inactive} giorni. Ti aspettiamo!"
        ok = 0
        fail = 0
        errors: list[str] = []
        for candidate in inactive:
            state = await self._database.get_inactivity_user_state(guild_id, str(candidate.member.id))
            last_reminder = state["last_reminder_at"] if state else None
            if last_reminder:
                try:
                    last_dt = datetime.fromisoformat(str(last_reminder).replace("Z", "+00:00"))
                    if (now - last_dt).days < cooldown:
                        continue
                except Exception:
                    pass
            body = self._render_template(template, member=candidate.member, guild=guild, days_inactive=candidate.days_inactive, policy=candidate.policy, cfg=cfg)
            try:
                await candidate.member.send(body)
                await self._database.mark_user_reminded(guild_id, str(candidate.member.id), now.isoformat())
                ok += 1
            except Exception as exc:
                fail += 1
                errors.append(f"{candidate.member.id}: {exc.__class__.__name__}")
        logger.info("inactive reminders guild=%s ok=%s fail=%s", guild_id, ok, fail)
        return {"dm_ok": ok, "dm_fail": fail, "errors": errors[:10]}

    async def execute_kick_pipeline(self, guild_id: str, *, require_grace: bool) -> dict[str, Any]:
        inactive, _, cfg = await self.scan_inactive_members(guild_id)
        guild = self._bot.get_guild(int(guild_id))
        if guild is None or not cfg:
            return {"kick_ok": 0, "kick_fail": 0, "ban_ok": 0, "ban_fail": 0, "dm_ok": 0, "dm_fail": 0, "atrio_ok": 0, "errors": []}
        now = datetime.now(timezone.utc)
        grace_days = int(cfg.get("grace_days_after_reminder", 7))
        ban_days = int(cfg.get("ban_days", 7))
        kick_template = cfg.get("dm_kick_template") or "Ciao {user}, sei stato rimosso da {server} per inattività. Puoi rientrare: {rejoin_link}"
        atrio_template = cfg.get("atrio_template") or "👋 {username} è uscito per inattività ({days_inactive}g)."
        atrio_channel = guild.get_channel(int(cfg["atrio_channel_id"])) if cfg.get("atrio_channel_id") else None
        stats = {"kick_ok": 0, "kick_fail": 0, "ban_ok": 0, "ban_fail": 0, "dm_ok": 0, "dm_fail": 0, "atrio_ok": 0, "errors": []}
        by_id = {c.member.id: c for c in inactive}
        for user_id, candidate in by_id.items():
            state = await self._database.get_inactivity_user_state(guild_id, str(user_id))
            if require_grace:
                if not state or not state["last_reminder_at"]:
                    continue
                try:
                    reminder_at = datetime.fromisoformat(str(state["last_reminder_at"]).replace("Z", "+00:00"))
                except Exception:
                    continue
                if (now - reminder_at).days < grace_days:
                    continue
                if candidate.last_message_ts and candidate.last_message_ts > str(state["last_reminder_at"]):
                    continue
            try:
                msg = self._render_template(kick_template, member=candidate.member, guild=guild, days_inactive=candidate.days_inactive, policy=candidate.policy, cfg=cfg)
                await candidate.member.send(msg)
                stats["dm_ok"] += 1
            except Exception as exc:
                stats["dm_fail"] += 1
                stats["errors"].append(f"dm {user_id}: {exc.__class__.__name__}")
            try:
                await candidate.member.kick(reason="Inattività prolungata")
                stats["kick_ok"] += 1
            except Exception as exc:
                stats["kick_fail"] += 1
                stats["errors"].append(f"kick {user_id}: {exc.__class__.__name__}")
                continue
            try:
                await guild.ban(discord.Object(id=user_id), reason="Ban temporaneo post kick inattività", delete_message_seconds=0)
                stats["ban_ok"] += 1
                unban_at = (now + timedelta(days=ban_days)).isoformat()
                await self._database.add_temp_ban(guild_id, str(user_id), unban_at, "Inattività")
                await self._database.mark_user_kicked(guild_id, str(user_id), now.isoformat())
            except Exception as exc:
                stats["ban_fail"] += 1
                stats["errors"].append(f"ban {user_id}: {exc.__class__.__name__}")
            if isinstance(atrio_channel, discord.abc.Messageable):
                try:
                    text = self._render_template(atrio_template, member=candidate.member, guild=guild, days_inactive=candidate.days_inactive, policy=candidate.policy, cfg=cfg)
                    await atrio_channel.send(text)
                    stats["atrio_ok"] += 1
                except Exception as exc:
                    stats["errors"].append(f"atrio {user_id}: {exc.__class__.__name__}")
        logger.info(
            "inactive kick pipeline guild=%s dm_ok=%s kick_ok=%s ban_ok=%s",
            guild_id,
            stats["dm_ok"],
            stats["kick_ok"],
            stats["ban_ok"],
        )
        stats["errors"] = stats["errors"][:10]
        return stats

    def build_action_embed(self, title: str, stats: dict[str, Any], extra: dict[str, Any] | None = None) -> discord.Embed:
        embed = discord.Embed(title=title, color=0x57F287)
        merged = dict(stats)
        if extra:
            for key, value in extra.items():
                if isinstance(value, int):
                    merged[key] = int(merged.get(key, 0)) + value
        lines = [
            f"DM success/fail: **{merged.get('dm_ok', 0)}/{merged.get('dm_fail', 0)}**",
            f"Kick success/fail: **{merged.get('kick_ok', 0)}/{merged.get('kick_fail', 0)}**",
            f"Ban success/fail: **{merged.get('ban_ok', 0)}/{merged.get('ban_fail', 0)}**",
            f"Atrio posted: **{merged.get('atrio_ok', 0)}**",
        ]
        errors = merged.get("errors") or []
        if errors:
            lines.append("Errori: " + "; ".join(errors[:10]))
        safe_set_description(embed, "\n".join(lines))
        return embed
    @staticmethod
    def _to_rome(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ROME)
