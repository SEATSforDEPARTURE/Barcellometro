from __future__ import annotations

import asyncio
import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import aiosqlite
import discord

from app.services.discord_embed_utils import FIELD_MAX, safe_add_field, safe_set_description
from app.services.database import DatabaseService
from app.services.footer import attach_footer_meta, attach_footer_meta_to_all
from app.services.greetings_copy_service import get_greetings_title_parts
from app.services.dm_template_placeholders import render_dm_template
from app.services.inactivity_dm_templates import build_inactivity_dm_template_payload
from app.services.users_moderation_dms import UsersModerationDmService
from app.shared.discord.dm_embed_builder import build_standard_dm_embed
from app.shared.discord.embed_body import (
    build_server_summary_title,
    format_standard_description,
    format_standard_field_name,
    format_standard_title,
)
from app.shared.discord.component_notices import send_standard_component_notice

logger = logging.getLogger(__name__)
ROME = ZoneInfo("Europe/Rome")
USERS_GRACE_TEMPBAN_DEFAULT_SECONDS = 0
MAX_FIELDS_PER_EMBED = 24
INACTIVE_GRACE_TITLE_EMOJI, INACTIVE_GRACE_TITLE_TEXT = get_greetings_title_parts("inactive_grace")
INACTIVE_TEMPBAN_TITLE_EMOJI, INACTIVE_TEMPBAN_TITLE_TEXT = get_greetings_title_parts("inactive_tempban")


def _state_int(state: Any, key: str, default: int = 0) -> int:
    if not state:
        return default
    try:
        if hasattr(state, "keys") and key not in state.keys():
            return default
        value = state[key]
    except Exception:
        try:
            value = state.get(key)
        except Exception:
            return default
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


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

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return bool(interaction.user.guild_permissions.administrator)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self._is_admin(interaction):
            await send_standard_component_notice(interaction, area="inactive moderation", message="Solo gli amministratori possono usare questi bottoni.", kind="error")
            return False
        return True

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
        if not self._is_admin(interaction):
            await send_standard_component_notice(interaction, area="inactive moderation", message="Solo gli amministratori possono usare questo comando.", kind="error")
            return
        await interaction.response.defer(ephemeral=True)
        result = await self._service.execute_reminders(self._guild_id)
        await interaction.followup.send(embed=self._service.build_action_embed("✅ AZIONE COMPLETATA · Reminder", result), ephemeral=True)

    @discord.ui.button(label="🚪 Caccia + ban temporaneo", style=discord.ButtonStyle.danger)
    async def kick(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        if not self._is_admin(interaction):
            await send_standard_component_notice(interaction, area="inactive moderation", message="Solo gli amministratori possono usare questo comando.", kind="error")
            return
        await interaction.response.defer(ephemeral=True)
        result = await self._service.execute_kick_pipeline(self._guild_id, require_grace=False)
        await interaction.followup.send(embed=self._service.build_action_embed("✅ AZIONE COMPLETATA · Caccia", result), ephemeral=True)

    @discord.ui.button(label="❌ Annulla", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        if not self._is_admin(interaction):
            await send_standard_component_notice(interaction, area="inactive moderation", message="Solo gli amministratori possono usare questo comando.", kind="error")
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(view=self)
        embed = discord.Embed(title=format_standard_title("Annullato", emoji="❌"), description="Azione manuale inattivi annullata.", color=0x808080)
        attach_footer_meta(embed, service_name="inactivity_moderation", used_local_processing=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


class GraceExpiredActionsView(discord.ui.View):
    def __init__(
        self,
        service: "InactiveMembersModerationService",
        guild_id: str,
        expired_user_ids: list[str],
        timeout: float = 600,
    ) -> None:
        super().__init__(timeout=timeout)
        self._service = service
        self._guild_id = guild_id
        self._expired_user_ids = expired_user_ids
        self.message: discord.Message | None = None

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return bool(interaction.user.guild_permissions.administrator)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self._is_admin(interaction):
            await send_standard_component_notice(interaction, area="inactive moderation", message="Solo gli amministratori possono usare questi bottoni.", kind="error")
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                logger.debug("grace expired view timeout edit failed", exc_info=True)

    @discord.ui.button(label="🚪 Kick ora", style=discord.ButtonStyle.danger)
    async def kick_now(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        if not self._is_admin(interaction):
            await send_standard_component_notice(interaction, area="inactive moderation", message="Solo gli amministratori possono usare questo comando.", kind="error")
            return
        await interaction.response.defer(ephemeral=True)
        result = await self._service.execute_kick_pipeline(self._guild_id, require_grace=True)
        await interaction.followup.send(embed=self._service.build_action_embed("✅ AZIONE COMPLETATA · Kick scaduti", result), ephemeral=True)

    @discord.ui.button(label="⏳ Estendi grace", style=discord.ButtonStyle.primary)
    async def extend_grace(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        if not self._is_admin(interaction):
            await send_standard_component_notice(interaction, area="inactive moderation", message="Solo gli amministratori possono usare questo comando.", kind="error")
            return
        await interaction.response.defer(ephemeral=True)
        now_iso = datetime.now(timezone.utc).isoformat()
        for user_id in self._expired_user_ids:
            await self._service._database.extend_user_grace(self._guild_id, user_id, now_iso)
        await send_standard_component_notice(
            interaction,
            area="inactive moderation",
            message=f"Grace esteso per {len(self._expired_user_ids)} utenti (senza invio DM).",
            kind="success",
        )

    @discord.ui.button(label="❌ Annulla", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:  # type: ignore[override]
        _ = button
        if not self._is_admin(interaction):
            await send_standard_component_notice(interaction, area="inactive moderation", message="Solo gli amministratori possono usare questo comando.", kind="error")
            return
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(view=self)
        await send_standard_component_notice(interaction, area="inactive moderation", message="Azione grace scaduto annullata.", kind="warning")


class InactiveMembersModerationService:
    def __init__(self, database: DatabaseService, bot: discord.Client, *, member_flow_notifications: Any | None = None) -> None:
        self._database = database
        self._bot = bot
        self._member_flow_notifications = member_flow_notifications
        self._users_dm_service = UsersModerationDmService(database, bot)
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
                await self._database.clear_user_ban_state(str(guild.id), str(user_id))
                if self._member_flow_notifications is not None:
                    await self._member_flow_notifications.log_action(guild_id=str(guild.id), user_id=str(user_id), moderator_id=None, action_type="unban", reason="Scadenza ban temporaneo inattività", metadata={"source": "inactive_members_moderation"})
                logger.info("inactive moderation: unbanned user=%s guild=%s", user_id, guild.id)
            except Exception:
                logger.warning("inactive moderation: failed unban user=%s guild=%s", user_id, guild.id, exc_info=True)
        await self._run_due_manual_grace_tempbans(now_iso)

    async def _log_moderation_action(
        self,
        *,
        guild_id: str,
        user_id: str,
        action_type: str,
        reason: str,
        duration_seconds: int | None = None,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if self._member_flow_notifications is None:
            await self._database.log_moderation_action(
                guild_id=guild_id,
                user_id=user_id,
                moderator_id=None,
                action_type=action_type,
                reason=reason,
                duration_seconds=duration_seconds,
                expires_at=expires_at,
                metadata=metadata,
            )
            return None
        return await self._member_flow_notifications.log_action(
            guild_id=guild_id,
            user_id=user_id,
            moderator_id=None,
            action_type=action_type,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            metadata=metadata,
        )

    @staticmethod
    def _users_grace_tempban_setting_key(guild_id: str) -> str:
        return f"users.grace.tempban.default_seconds.{guild_id}"

    async def _manual_grace_tempban_seconds(self, guild_id: str) -> int:
        raw = await self._database.get_setting(self._users_grace_tempban_setting_key(guild_id))
        if raw is None:
            return USERS_GRACE_TEMPBAN_DEFAULT_SECONDS
        try:
            return max(0, int(str(raw).strip()))
        except Exception:
            return USERS_GRACE_TEMPBAN_DEFAULT_SECONDS

    async def _run_due_manual_grace_tempbans(self, now_iso: str) -> None:
        rows = await self._database.list_due_manual_grace(now_iso)
        now = datetime.now(timezone.utc)
        for row in rows:
            guild_id = str(row["guild_id"])
            user_id = str(row["user_id"])
            guild = self._bot.get_guild(int(guild_id))
            if guild is None:
                continue
            await self._log_moderation_action(
                guild_id=guild_id,
                user_id=user_id,
                action_type="ungrace",
                reason="Manual grace period expired",
                metadata={"source": "users_grace_auto_expiry"},
            )
            duration_seconds = await self._manual_grace_tempban_seconds(guild_id)
            if duration_seconds <= 0:
                continue
            if self._member_flow_notifications is not None:
                remember = getattr(self._member_flow_notifications, "remember_departure_action", None)
                if remember is not None:
                    remember(guild_id, user_id, "tempban")
            expires_at = now + timedelta(seconds=duration_seconds)
            try:
                await self._users_dm_service.send_for_event_by_user_id(
                    guild=guild,
                    user_id=user_id,
                    event_type="tempban",
                    duration_seconds=duration_seconds,
                    expires_at=expires_at,
                    reason=None,
                    reason_is_human=False,
                    reasoning="users_manual_grace_expired_tempban",
                    metadata={"source": "users_grace_auto_tempban"},
                )
                await guild.ban(discord.Object(id=int(user_id)), reason=None, delete_message_seconds=0)
            except Exception:
                if self._member_flow_notifications is not None:
                    forget = getattr(self._member_flow_notifications, "forget_departure_action", None)
                    if forget is not None:
                        forget(guild_id, user_id)
                logger.warning("users grace auto-tempban failed user=%s guild=%s", user_id, guild_id, exc_info=True)
                continue
            await self._database.add_temp_ban(guild_id, user_id, expires_at.isoformat(), None)
            result = await self._log_moderation_action(
                guild_id=guild_id,
                user_id=user_id,
                action_type="tempban",
                reason=None,
                duration_seconds=duration_seconds,
                expires_at=expires_at.isoformat(),
                metadata={
                    "source": "users_grace_auto_tempban",
                    "grace_action_id": str(row["id"]),
                    "greetings_origin": "manual_grace_expired_auto_tempban",
                    "greetings_reason": "",
                },
            )
            if (
                self._member_flow_notifications is not None
                and isinstance(result, dict)
                and result.get("canonical_written")
                and result.get("canonical_visible")
            ):
                await self._member_flow_notifications.send_notification(
                    guild=guild,
                    user=discord.Object(id=int(user_id)),
                    action_type="tempban",
                    reason=None,
                    duration_seconds=duration_seconds,
                    expires_at=expires_at,
                    metadata={
                        "source": "users_grace_auto_tempban",
                        "grace_action_id": str(row["id"]),
                        "greetings_origin": "manual_grace_expired_auto_tempban",
                        "greetings_reason": "",
                    },
                    canonical_event=result.get("canonical_event"),
                )

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
    def _parse_state_reminder_dt(cls, state: aiosqlite.Row | None) -> datetime | None:
        if not state:
            return None
        return cls._parse_last_message_dt(state["last_reminder_at"])

    def _format_grace_remaining(self, reminder_at: datetime, grace_days: int) -> str:
        deadline = reminder_at + timedelta(days=grace_days)
        now = datetime.now(timezone.utc)
        delta = deadline - now
        if delta.total_seconds() <= 0:
            return "scaduto"
        total_seconds = int(delta.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = max(1, (total_seconds % 3600) // 60)
        if days > 0:
            return f"-{days}g {hours}h"
        if hours > 0:
            return f"-{hours}h {minutes}m"
        return f"-{minutes}m"

    def _format_inactive_preview_line(self, idx: int, candidate: InactiveCandidate, *, state: aiosqlite.Row | None, cfg: dict[str, Any]) -> str:
        grace_days = int(cfg.get("grace_days_after_reminder", 7)) if cfg else 7
        reminder_dt = self._parse_state_reminder_dt(state)
        if reminder_dt is None:
            prefix = ""
        else:
            remaining = self._format_grace_remaining(reminder_dt, grace_days)
            prefix = f"⌛{remaining} " if remaining != "scaduto" else ""
        head = f"{idx}) {prefix}{candidate.member.mention} ({candidate.count_in_window} msg) | "
        dt = self._parse_last_message_dt(candidate.last_message_ts)
        if dt is None or not candidate.last_channel_id or not candidate.last_message_id:
            return f"{head}💬 Ultimo: mai"
        local = self._to_rome(dt)
        last_fmt = local.strftime("%d/%m %H:%M")
        jump_url = (
            f"https://discord.com/channels/{candidate.member.guild.id}/{candidate.last_channel_id}/{candidate.last_message_id}"
        )
        return f"{head}💬 Ultimo: [{last_fmt}]({jump_url}) 🕒 {candidate.days_inactive}g fa"

    def _format_inactive_txt_line(
        self,
        idx: int,
        candidate: InactiveCandidate,
        *,
        state: aiosqlite.Row | None = None,
        cfg: dict[str, Any] | None = None,
        guild: discord.Guild | None = None,
    ) -> str:
        mention = candidate.member.mention
        display = getattr(candidate.member, "display_name", getattr(candidate.member, "name", "sconosciuto"))
        count = candidate.count_in_window
        grace_days = int((cfg or {}).get("grace_days_after_reminder", 7))
        reminder_dt = self._parse_state_reminder_dt(state)
        if reminder_dt is None:
            prefix = f"{idx}) {mention} ({display}) ({count} msg totali) | "
        else:
            data_fmt = self._to_rome(reminder_dt).strftime("%d/%m %H:%M")
            remaining = self._format_grace_remaining(reminder_dt, grace_days)
            grace_text = f"⌛{remaining}"
            prefix = f"{idx}) 🔔 Avv. il {data_fmt} ({grace_text}) | {mention} ({display}) ({count} msg totali) | "
        dt = self._parse_last_message_dt(candidate.last_message_ts)
        if dt is None or not candidate.last_channel_id or not candidate.last_message_id:
            return f"{prefix}💬 Ultimo: mai"

        local = self._to_rome(dt)
        last_fmt = local.strftime("%d/%m %H:%M")
        channel_id = int(candidate.last_channel_id)
        ch = (guild.get_channel(channel_id) if guild is not None else None) or self._bot.get_channel(channel_id)
        channel_name = ch.name if ch and hasattr(ch, "name") else "canale_sconosciuto"
        guild_id = guild.id if guild is not None else candidate.member.guild.id
        jump_url = f"https://discord.com/channels/{guild_id}/{candidate.last_channel_id}/{candidate.last_message_id}"
        return f"{prefix}💬 Ultimo: {last_fmt} in \"{channel_name}\" 🕒 {candidate.days_inactive}g fa ({jump_url})"

    def _format_policy_default(self, policy: dict[str, Any], cfg: dict[str, Any]) -> str:
        mode = str(policy.get("mode", "OR")).upper()
        auto_enabled = "ON" if bool(cfg.get("auto_enabled")) else "OFF"
        invite_set = "si" if bool(cfg.get("invite_url")) else "no"
        atrio_set = "si" if bool(cfg.get("notify_channel_id") or cfg.get("atrio_channel_id")) else "no"
        min_account_age_days = int(policy.get("min_account_age_days", 0))
        return (
            f"- Inattivita: {policy.get('inactive_days', 30)} giorni\n"
            f"- Finestra analisi: {policy.get('window_days', 30)} giorni\n"
            f"- Min messaggi: {policy.get('min_messages', 1)}\n"
            f"- Logica: {mode}\n"
            "  OR: basta 1 condizione (pochi msg OPPURE assenza lunga)\n"
            "  AND: servono entrambe (pochi msg E assenza lunga)\n"
            f"- Grace period: {cfg.get('grace_days_after_reminder', 7)} giorni\n"
            f"- Ban temporaneo: {cfg.get('ban_days', 7)} giorni\n"
            f"- Nuovi utenti ignorati per: {min_account_age_days} giorni\n"
            f"- Modalita auto kick: {auto_enabled}\n"
            f"- Reminder cooldown: {cfg.get('reminder_cooldown_days', 14)} giorni\n"
            f"- Invite link impostato: {invite_set}\n"
            f"- Canale greetings configurato: {atrio_set}"
        )

    def _format_excluded_roles(self, guild: discord.Guild, cfg: dict[str, Any]) -> str:
        role_ids = cfg.get("excluded_role_ids") or []
        if not role_ids:
            return "- Nessuno"
        lines: list[str] = []
        for role_id in sorted(int(r) for r in role_ids):
            role = guild.get_role(role_id)
            if role:
                lines.append(f"- {role.name} (<@&{role_id}>)")
            else:
                lines.append(f"- ruolo_sconosciuto (ID:{role_id})")
        return "\n".join(lines)

    def _format_role_policies(self, guild: discord.Guild, rows: list[Any]) -> str:
        if not rows:
            return "- Nessuna policy ruolo configurata."
        lines: list[str] = []
        for row in rows:
            policy = self._parse_policy_json(row["policy_json"])
            role_id = int(str(row["role_id"]))
            role = guild.get_role(role_id)
            role_label = f"{role.name} (<@&{role_id}>)" if role else f"ruolo_sconosciuto (ID:{role_id})"
            lines.append(
                f"- {role_label}: prio {int(row['priority'])}, inattivita {policy.get('inactive_days', 30)}g, "
                f"finestra {policy.get('window_days', 30)}g, min {policy.get('min_messages', 1)}, "
                f"{str(policy.get('mode', 'OR')).upper()}, min_age {policy.get('min_account_age_days', 0)}g"
            )
        return "\n".join(lines)

    async def _collect_expired_grace_users(
        self,
        guild_id: str,
        inactive: list[InactiveCandidate],
        cfg: dict[str, Any],
    ) -> list[tuple[InactiveCandidate, aiosqlite.Row, datetime, timedelta]]:
        if not inactive:
            return []
        grace_days = int(cfg.get("grace_days_after_reminder", 7))
        states = await self._database.fetch_inactivity_user_states(guild_id, [str(c.member.id) for c in inactive])
        now = datetime.now(timezone.utc)
        expired: list[tuple[InactiveCandidate, aiosqlite.Row, datetime, timedelta]] = []
        for candidate in inactive:
            state = states.get(str(candidate.member.id))
            reminder_at = self._parse_state_reminder_dt(state)
            if reminder_at is None:
                continue
            if candidate.last_message_ts and candidate.last_message_ts > str(state["last_reminder_at"]):
                continue
            delta = now - reminder_at
            if delta < timedelta(days=grace_days):
                continue
            expired.append((candidate, state, reminder_at, delta - timedelta(days=grace_days)))
        return expired

    async def handle_post_activity_report(self, guild_id: str, mod_channel_id: str) -> None:
        cfg = await self._get_config(guild_id)
        if not cfg or not bool(cfg.get("enabled")):
            return
        guild = self._bot.get_guild(int(guild_id))
        channel = self._bot.get_channel(int(mod_channel_id))
        if guild is None or not isinstance(channel, discord.abc.Messageable):
            return
        inactive, considered, _ = await self.scan_inactive_members(guild_id)
        await self.post_manual_panel(guild_id, mod_channel_id, inactive=inactive, cfg=cfg, considered=considered)
        if bool(cfg.get("auto_enabled")):
            grace_enabled = int(cfg.get("grace_days_after_reminder", 7) or 0) > 0
            kick_stats = await self.execute_kick_pipeline(guild_id, require_grace=grace_enabled)
            reminder_stats = await self.execute_reminders(guild_id) if grace_enabled else {"dm_ok": 0, "dm_fail": 0, "errors": []}
            await channel.send(embed=self.build_auto_inactive_completed_embed(reminder_stats, kick_stats))
            return

        expired = await self._collect_expired_grace_users(guild_id, inactive, cfg)
        if not expired:
            return

        lines: list[str] = []
        for candidate, state, reminder_at, overdue in expired:
            display = getattr(candidate.member, "display_name", getattr(candidate.member, "name", "sconosciuto"))
            reminded_fmt = self._to_rome(reminder_at).strftime("%d/%m %H:%M")
            overdue_days = max(0, int(overdue.total_seconds() // 86400))
            lines.append(f"• {candidate.member.mention} ({display}) — 🔔 {reminded_fmt} · scaduto da {overdue_days}g")

        preview_lines: list[str] = []
        extra = 0
        current_len = 0
        for line in lines:
            add_len = len(line) + (1 if preview_lines else 0)
            if current_len + add_len > FIELD_MAX:
                extra += 1
                continue
            preview_lines.append(line)
            current_len += add_len
        if extra > 0:
            preview_lines.append(f"+ altri {extra}…")
        embed = discord.Embed(title=format_standard_title("GRACE SCADUTO (AUTO OFF)", emoji="⚠️"), colour=discord.Colour.orange())
        safe_add_field(embed, name=format_standard_field_name("Utenti scaduti"), value=str(len(expired)), inline=True)
        safe_add_field(embed, name=format_standard_field_name("Dettaglio"), value="\n".join(preview_lines) if preview_lines else "Nessun utente.", inline=False)
        attach_footer_meta(embed, service_name="inactivity_moderation", used_local_processing=True)

        view = GraceExpiredActionsView(self, guild_id, [str(c.member.id) for c, _, _, _ in expired])
        message = await channel.send(embed=embed, view=view)
        view.message = message

    async def build_serverwide_inactive_embeds(
        self,
        guild_id: str,
        mod_channel_id: str,
        *,
        inactive: list[InactiveCandidate] | None = None,
        cfg: dict[str, Any] | None = None,
        considered: int | None = None,
        include_actions_view: bool = True,
    ) -> tuple[list[discord.Embed], discord.File | None, InactivityActionsView | None]:
        guild = self._bot.get_guild(int(guild_id))
        if guild is None:
            return [], None, None
        if inactive is None or cfg is None or considered is None:
            inactive, considered, cfg = await self.scan_inactive_members(guild_id)
        policy = cfg.get("default_policy", {}) if cfg else {}
        role_policy_rows = await self._database.list_inactivity_role_policies(guild_id)

        ordered = sorted(inactive, key=self._inactive_sort_key)
        states = await self._database.fetch_inactivity_user_states(guild_id, [str(c.member.id) for c in ordered])
        now = datetime.now(timezone.utc)
        grace_days = int(cfg.get("grace_days_after_reminder", 7)) if cfg else 7
        warned = 0
        in_grace = 0
        expired_grace = 0
        for candidate in ordered:
            reminder_at = self._parse_state_reminder_dt(states.get(str(candidate.member.id)))
            if reminder_at is None:
                continue
            warned += 1
            delta = now - reminder_at
            if delta < timedelta(days=grace_days):
                in_grace += 1
            else:
                expired_grace += 1

        all_lines = [
            self._format_inactive_preview_line(i, candidate, state=states.get(str(candidate.member.id)), cfg=cfg)
            for i, candidate in enumerate(ordered, start=1)
        ]

        def _chunk_lines_for_field(lines: list[str]) -> list[str]:
            if not lines:
                return ["Nessun inattivo."]
            chunks: list[str] = []
            current: list[str] = []
            current_len = 0
            for raw_line in lines:
                line = raw_line if len(raw_line) <= FIELD_MAX else f"{raw_line[: FIELD_MAX - 1]}…"
                candidate_len = len(line) + (1 if current else 0)
                if current and current_len + candidate_len > FIELD_MAX:
                    chunks.append("\n".join(current))
                    current = [line]
                    current_len = len(line)
                else:
                    current.append(line)
                    current_len += candidate_len
            if current:
                chunks.append("\n".join(current))
            return chunks

        embeds: list[discord.Embed] = []
        inactive_field_chunks = _chunk_lines_for_field(all_lines)
        for i, chunk in enumerate(inactive_field_chunks):
            if not embeds or len(embeds[-1].fields) >= MAX_FIELDS_PER_EMBED:
                embed = discord.Embed(
                    title=build_server_summary_title("INATTIVI"),
                    colour=discord.Colour.blue(),
                    description=format_standard_description(
                        "Panoramica dei membri inattivi rilevati secondo la policy attiva.",
                        italic=True,
                    ),
                )
                if not embeds:
                    safe_add_field(embed, name=format_standard_field_name("Membri analizzati"), value=str(considered), inline=True)
                    safe_add_field(embed, name=format_standard_field_name("Inattivi trovati"), value=str(len(inactive)), inline=True)
                    safe_add_field(embed, name=format_standard_field_name("Stato reminder"), value=f"🔔 Avvisati: {warned}\n⏳ In grace: {in_grace}\n⚠️ Grace scaduto: {expired_grace}", inline=True)
                embeds.append(embed)
            field_label = "INATTIVI" if i == 0 else "INATTIVI (CONT.)"
            safe_add_field(embeds[-1], name=format_standard_field_name(field_label, emoji="✏️"), value=chunk, inline=False)
        attach_footer_meta_to_all(embeds, service_name="inactivity_moderation", used_local_processing=True)

        txt_file: discord.File | None = None
        if ordered:
            ts_name = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"inattivi_serverwide_{ts_name}.txt"
            txt_lines = [
                self._format_inactive_txt_line(i, candidate, state=states.get(str(candidate.member.id)), cfg=cfg, guild=guild)
                for i, candidate in enumerate(ordered, start=1)
            ]
            policy_sections = (
                "\n\n====================\n"
                "POLICY E IMPOSTAZIONI\n"
                "====================\n"
                f"\n📄 Policy di base\n{self._format_policy_default(policy, cfg or {})}"
                f"\n\n🏷️ Policy per ruoli\n{self._format_role_policies(guild, role_policy_rows)}"
                f"\n\n⛔ Ruoli esclusi dal controllo inattivi\n{self._format_excluded_roles(guild, cfg or {})}"
            )
            payload = ("\n".join(txt_lines) + policy_sections).encode("utf-8")
            txt_file = discord.File(io.BytesIO(payload), filename=filename)

        view = InactivityActionsView(self, guild_id, mod_channel_id) if include_actions_view else None
        return embeds, txt_file, view

    async def post_manual_panel(self, guild_id: str, mod_channel_id: str, *, inactive: list[InactiveCandidate] | None = None, cfg: dict[str, Any] | None = None, considered: int | None = None) -> None:
        channel = self._bot.get_channel(int(mod_channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            return
        embeds, txt_file, view = await self.build_serverwide_inactive_embeds(
            guild_id,
            mod_channel_id,
            inactive=inactive,
            cfg=cfg,
            considered=considered,
            include_actions_view=True,
        )
        if not embeds or view is None:
            return
        if txt_file is not None:
            message = await channel.send(embed=embeds[0], view=view, file=txt_file)
        else:
            message = await channel.send(embed=embeds[0], view=view)
        view.message = message

        for extra_embed in embeds[1:]:
            await channel.send(embed=extra_embed)

    def _render_template(
        self,
        template: str,
        *,
        member: discord.Member,
        guild: discord.Guild,
        event_type: str,
        days_inactive: int,
        policy: dict[str, Any],
        cfg: dict[str, Any],
        message_count: int | None = None,
        reminder_count: int | None = None,
        reason: str | None = None,
        reasoning: str | None = None,
        inactivity_text: str | None = None,
        event_state: str | None = None,
        event_cause: str | None = None,
        duration_seconds: int | None = None,
        now: datetime | None = None,
        started_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> str:
        base = template or ""
        payload = build_inactivity_dm_template_payload(
            member=member,
            guild=guild,
            event_type=event_type,
            days_inactive=days_inactive,
            policy=policy,
            cfg=cfg,
            message_count=message_count,
            reminder_count=reminder_count,
            reason=reason,
            reasoning=reasoning,
            inactivity_text=inactivity_text,
            event_state=event_state,
            event_cause=event_cause,
            duration_seconds=duration_seconds,
            now=now,
            started_at=started_at,
            expires_at=expires_at,
        )
        return render_dm_template(base, payload)

    @staticmethod
    def _parse_iso_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            return None

    @staticmethod
    def _resolve_inactivity_dm_color(raw_color: Any, fallback: discord.Colour) -> discord.Colour:
        value = str(raw_color or "").strip()
        if not value:
            return fallback
        if value.startswith("#"):
            value = value[1:]
        elif value.lower().startswith("0x"):
            value = value[2:]
        if len(value) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in value):
            return fallback
        try:
            return discord.Colour(int(value, 16))
        except ValueError:
            return fallback

    async def _latest_grace_dm_delivery(self, guild_id: str, user_id: str) -> Any | None:
        latest_delivery_lookup = getattr(self._database, "get_latest_inactivity_dm_delivery", None)
        if latest_delivery_lookup is None:
            return None
        latest_grace = await latest_delivery_lookup(guild_id, user_id, "grace")
        latest_legacy = await latest_delivery_lookup(guild_id, user_id, "reminder")
        if latest_grace is None:
            return latest_legacy
        if latest_legacy is None:
            return latest_grace
        grace_sent_at = self._parse_iso_datetime(str(latest_grace["sent_at"]) if latest_grace["sent_at"] else None)
        legacy_sent_at = self._parse_iso_datetime(str(latest_legacy["sent_at"]) if latest_legacy["sent_at"] else None)
        if grace_sent_at is None:
            return latest_legacy
        if legacy_sent_at is None:
            return latest_grace
        return latest_grace if grace_sent_at >= legacy_sent_at else latest_legacy

    async def execute_reminders(self, guild_id: str) -> dict[str, Any]:
        inactive, _, cfg = await self.scan_inactive_members(guild_id)
        guild = self._bot.get_guild(int(guild_id))
        if guild is None or not cfg:
            return {"dm_ok": 0, "dm_fail": 0, "dm_skipped": 0, "errors": []}
        if int(cfg.get("dm_reminders_enabled", 1) or 0) <= 0:
            logger.info("inactive reminders disabled for guild=%s", guild_id)
            return {"dm_ok": 0, "dm_fail": 0, "dm_skipped": 0, "errors": [], "disabled": True}
        now = datetime.now(timezone.utc)
        grace_days = int(cfg.get("grace_days_after_reminder", 7) or 7)
        grace_enabled = grace_days > 0
        grace_template = cfg.get("template_grace") or cfg.get("dm_reminder_template") or "Ciao {user}, sei inattivo su {server} da {days_inactive} giorni. Ti aspettiamo!"
        raw_cooldown_seconds = cfg.get("reminder_cooldown_seconds")
        if raw_cooldown_seconds is None:
            raw_cooldown_seconds = int(cfg.get("reminder_cooldown_days", 14) or 14) * 86400
        cooldown_seconds = max(0, int(raw_cooldown_seconds or 0))
        ok = 0
        fail = 0
        skipped = 0
        errors: list[str] = []
        for candidate in inactive:
            state = await self._database.get_inactivity_user_state(guild_id, str(candidate.member.id))
            reminder_at = self._parse_state_reminder_dt(state)
            latest_activity = self._parse_last_message_dt(candidate.last_message_ts)
            if grace_enabled and reminder_at is not None:
                has_post_reminder_activity = latest_activity is not None and latest_activity > reminder_at
                if not has_post_reminder_activity:
                    skipped += 1
                    continue

            latest_delivery = await self._latest_grace_dm_delivery(guild_id, str(candidate.member.id))
            if latest_delivery and latest_delivery["sent_at"] and str(latest_delivery["outcome"] or "").lower() == "success":
                try:
                    last_sent = self._parse_iso_datetime(str(latest_delivery["sent_at"]))
                    if last_sent is None:
                        raise ValueError("invalid sent_at")
                    if cooldown_seconds > 0 and now - last_sent < timedelta(seconds=cooldown_seconds):
                        skipped += 1
                        continue
                except Exception:
                    logger.debug("inactive reminder cooldown parse failed", exc_info=True)
            inactivity_text = f"è stato inattivo per {candidate.days_inactive} giorni"
            expires_at = now + timedelta(days=grace_days)
            grace_metadata = {
                "source": "inactive_members_moderation",
                "greetings_reason": "",
                "days_inactive": candidate.days_inactive,
                "inactivity_text": inactivity_text,
            }
            body = self._render_template(
                grace_template,
                member=candidate.member,
                guild=guild,
                event_type="grace",
                days_inactive=candidate.days_inactive,
                policy=candidate.policy,
                cfg=cfg,
                message_count=candidate.count_in_window,
                reminder_count=_state_int(state, "reminder_count", 0),
                reason=None,
                reasoning="inactivity_grace",
                inactivity_text=inactivity_text,
                event_state="grace_started",
                event_cause="inactivity",
                duration_seconds=grace_days * 86400,
                now=now,
                started_at=now,
                expires_at=expires_at,
            )
            reminder_embed = await build_standard_dm_embed(
                service_name="inactivity",
                canonical_top_level_command="inattivi",
                title=INACTIVE_GRACE_TITLE_TEXT,
                title_emoji=INACTIVE_GRACE_TITLE_EMOJI,
                description=body,
                color=self._resolve_inactivity_dm_color(cfg.get("template_grace_embed_color"), discord.Colour.blurple()),
            )

            async def _log_grace_event() -> None:
                if self._member_flow_notifications is None:
                    return
                result = await self._member_flow_notifications.log_action(
                    guild_id=guild_id,
                    user_id=str(candidate.member.id),
                    moderator_id=None,
                    action_type="inactive_grace",
                    reason=None,
                    duration_seconds=grace_days * 86400,
                    expires_at=expires_at.isoformat(),
                    metadata=grace_metadata,
                )
                if result.get("canonical_written") and result.get("canonical_visible"):
                    await self._member_flow_notifications.send_notification(
                        guild=guild,
                        user=candidate.member,
                        action_type="inactive_grace",
                        reason=None,
                        duration_seconds=grace_days * 86400,
                        expires_at=expires_at,
                        metadata=grace_metadata,
                        canonical_event=result.get("canonical_event"),
                    )
            try:
                await candidate.member.send(embed=reminder_embed)
                await self._database.mark_user_reminded(guild_id, str(candidate.member.id), now.isoformat())
                await self._database.log_inactivity_dm_delivery(
                    guild_id=guild_id,
                    user_id=str(candidate.member.id),
                    event_type="grace",
                    reason=inactivity_text,
                    sent_at=now.isoformat(),
                    outcome="success",
                    metadata={
                        "source": "inactive_members_moderation",
                        "days_inactive": candidate.days_inactive,
                        "message_count": candidate.count_in_window,
                    },
                )
                await _log_grace_event()
                ok += 1
            except Exception as exc:
                try:
                    await candidate.member.send(body)
                    await self._database.mark_user_reminded(guild_id, str(candidate.member.id), now.isoformat())
                    await self._database.log_inactivity_dm_delivery(
                        guild_id=guild_id,
                        user_id=str(candidate.member.id),
                        event_type="grace",
                        reason=inactivity_text,
                        sent_at=now.isoformat(),
                        outcome="success",
                        metadata={
                            "source": "inactive_members_moderation",
                            "days_inactive": candidate.days_inactive,
                            "message_count": candidate.count_in_window,
                            "delivery_fallback": "text",
                        },
                    )
                    await _log_grace_event()
                    ok += 1
                    continue
                except Exception:
                    fail += 1
                    errors.append(f"{candidate.member.id}: {exc.__class__.__name__}")
                    await self._database.log_inactivity_dm_delivery(
                        guild_id=guild_id,
                        user_id=str(candidate.member.id),
                        event_type="grace",
                        reason=inactivity_text,
                        sent_at=now.isoformat(),
                        outcome="fail",
                        error_summary=exc.__class__.__name__,
                        metadata={
                            "source": "inactive_members_moderation",
                            "days_inactive": candidate.days_inactive,
                            "message_count": candidate.count_in_window,
                        },
                    )
        logger.info("inactive reminders guild=%s ok=%s fail=%s", guild_id, ok, fail)
        return {"dm_ok": ok, "dm_fail": fail, "dm_skipped": skipped, "errors": errors[:10]}

    async def execute_kick_pipeline(self, guild_id: str, *, require_grace: bool) -> dict[str, Any]:
        inactive, _, cfg = await self.scan_inactive_members(guild_id)
        guild = self._bot.get_guild(int(guild_id))
        if guild is None or not cfg:
            return {"kick_ok": 0, "kick_fail": 0, "ban_ok": 0, "ban_fail": 0, "dm_ok": 0, "dm_fail": 0, "notify_ok": 0, "errors": []}
        now = datetime.now(timezone.utc)
        grace_days = int(cfg.get("grace_days_after_reminder", 7))
        ban_days = int(cfg.get("ban_days", 7))
        tempban_template = cfg.get("template_tempban") or cfg.get("dm_kick_template") or "Ciao {user}, sei stato rimosso da {server} per inattività. Puoi rientrare: {rejoin_link}"
        stats = {"kick_ok": 0, "kick_fail": 0, "ban_ok": 0, "ban_fail": 0, "dm_ok": 0, "dm_fail": 0, "notify_ok": 0, "errors": []}
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
            reminder_count = _state_int(state, "reminder_count", 0)
            inactivity_text = f"è stato inattivo per {candidate.days_inactive} giorni"
            msg = self._render_template(
                tempban_template,
                member=candidate.member,
                guild=guild,
                event_type="tempban",
                days_inactive=candidate.days_inactive,
                policy=candidate.policy,
                cfg=cfg,
                message_count=candidate.count_in_window,
                reminder_count=reminder_count,
                reason=None,
                reasoning="inactivity_grace_expired_tempban" if require_grace else "inactivity_direct_tempban",
                inactivity_text=inactivity_text,
                event_state="grace_expired" if require_grace else "manual_action",
                event_cause="inactivity",
                duration_seconds=ban_days * 86400,
                now=now,
                started_at=now,
                expires_at=now + timedelta(days=ban_days),
            )
            try:
                tempban_embed = await build_standard_dm_embed(
                    service_name="inactivity",
                    canonical_top_level_command="inattivi",
                    title=INACTIVE_TEMPBAN_TITLE_TEXT,
                    title_emoji=INACTIVE_TEMPBAN_TITLE_EMOJI,
                    description=msg,
                    color=self._resolve_inactivity_dm_color(cfg.get("template_tempban_embed_color"), discord.Colour.orange()),
                )
                await candidate.member.send(embed=tempban_embed)
                await self._database.log_inactivity_dm_delivery(
                    guild_id=guild_id,
                    user_id=str(user_id),
                    event_type="tempban",
                    reason="Inattività prolungata",
                    sent_at=now.isoformat(),
                    outcome="success",
                    metadata={
                        "source": "inactive_members_moderation",
                        "days_inactive": candidate.days_inactive,
                        "message_count": candidate.count_in_window,
                        "grace_required": require_grace,
                    },
                )
                stats["dm_ok"] += 1
            except Exception as exc:
                try:
                    await candidate.member.send(msg)
                    await self._database.log_inactivity_dm_delivery(
                        guild_id=guild_id,
                        user_id=str(user_id),
                        event_type="tempban",
                        reason="Inattività prolungata",
                        sent_at=now.isoformat(),
                        outcome="success",
                        metadata={
                            "source": "inactive_members_moderation",
                            "days_inactive": candidate.days_inactive,
                            "message_count": candidate.count_in_window,
                            "grace_required": require_grace,
                            "delivery_fallback": "text",
                        },
                    )
                    stats["dm_ok"] += 1
                except Exception:
                    stats["dm_fail"] += 1
                    stats["errors"].append(f"dm {user_id}: {exc.__class__.__name__}")
                    await self._database.log_inactivity_dm_delivery(
                        guild_id=guild_id,
                        user_id=str(user_id),
                        event_type="tempban",
                        reason="Inattività prolungata",
                        sent_at=now.isoformat(),
                        outcome="fail",
                        error_summary=exc.__class__.__name__,
                        metadata={
                            "source": "inactive_members_moderation",
                            "days_inactive": candidate.days_inactive,
                            "message_count": candidate.count_in_window,
                            "grace_required": require_grace,
                        },
                    )
            try:
                if self._member_flow_notifications is not None:
                    remember = getattr(self._member_flow_notifications, "remember_departure_action", None)
                    if remember is not None:
                        remember(guild_id, str(user_id), "inactive_tempban" if ban_days > 0 else "inactive_kick")
                await candidate.member.kick(reason="Inattività prolungata")
                stats["kick_ok"] += 1
            except Exception as exc:
                if self._member_flow_notifications is not None:
                    forget = getattr(self._member_flow_notifications, "forget_departure_action", None)
                    if forget is not None:
                        forget(guild_id, str(user_id))
                stats["kick_fail"] += 1
                stats["errors"].append(f"kick {user_id}: {exc.__class__.__name__}")
                continue
            last_message_at = self._parse_last_message_dt(candidate.last_message_ts)
            if not last_message_at:
                inactivity_text = "non è mai stato attivo"
            else:
                days_inactive = (now - last_message_at).days
                inactivity_text = f"è stato inattivo per {days_inactive} giorni"
            reason_text = inactivity_text[:1].upper() + inactivity_text[1:] if inactivity_text else None
            operation_id = str(uuid4())
            kick_result: dict[str, Any] | None = None
            if self._member_flow_notifications is not None:
                greetings_event_type = "inactive_tempban" if ban_days > 0 else "inactive_kick"
                kick_result = await self._member_flow_notifications.log_action(
                    guild_id=guild_id,
                    user_id=str(user_id),
                    moderator_id=None,
                    action_type="inactive_kick",
                    reason=reason_text,
                    metadata={
                        "source": "inactive_members_moderation",
                        "operation_id": operation_id,
                        "visible_in_greetings": ban_days <= 0,
                        "greetings_reason": reason_text,
                        "days_inactive": candidate.days_inactive,
                        "inactivity_text": inactivity_text,
                    },
                )

            if ban_days > 0:
                try:
                    await guild.ban(discord.Object(id=user_id), reason="Ban temporaneo post kick inattività", delete_message_seconds=0)
                    stats["ban_ok"] += 1
                    expires_at = now + timedelta(days=ban_days)
                    unban_at = expires_at.isoformat()
                    await self._database.add_temp_ban(guild_id, str(user_id), unban_at, "Inattività")
                    await self._database.mark_user_kicked(guild_id, str(user_id), now.isoformat())
                    if self._member_flow_notifications is not None and reason_text is not None:
                        result = await self._member_flow_notifications.log_action(
                            guild_id=guild_id,
                            user_id=str(user_id),
                            moderator_id=None,
                            action_type="inactive_tempban",
                            reason=None,
                            duration_seconds=ban_days * 86400,
                            expires_at=unban_at,
                            metadata={
                                "source": "inactive_members_moderation",
                                "operation_id": operation_id,
                                "greetings_reason": "",
                                "days_inactive": candidate.days_inactive,
                                "inactivity_text": inactivity_text,
                                **({"greetings_origin": "inactive_grace_expired_auto_tempban", "greetings_reason": ""} if require_grace else {}),
                            },
                        )
                        if result.get("canonical_written") and result.get("canonical_visible"):
                            await self._member_flow_notifications.send_notification(
                                guild=guild,
                                user=candidate.member,
                                action_type="inactive_tempban",
                                reason=None,
                                duration_seconds=ban_days * 86400,
                                expires_at=expires_at,
                                metadata={
                                    "source": "inactive_members_moderation",
                                    "operation_id": operation_id,
                                    "greetings_reason": "",
                                    "days_inactive": candidate.days_inactive,
                                    "inactivity_text": inactivity_text,
                                    **({"greetings_origin": "inactive_grace_expired_auto_tempban", "greetings_reason": ""} if require_grace else {}),
                                },
                                canonical_event=result.get("canonical_event"),
                            )
                        stats["notify_ok"] += 1
                except Exception as exc:
                    stats["ban_fail"] += 1
                    stats["errors"].append(f"ban {user_id}: {exc.__class__.__name__}")
                    continue
            else:
                await self._database.mark_user_kicked(guild_id, str(user_id), now.isoformat())
                if self._member_flow_notifications is not None and reason_text is not None and kick_result is not None:
                    if not (kick_result.get("canonical_written") and kick_result.get("canonical_visible")):
                        continue
                    await self._member_flow_notifications.send_notification(
                        guild=guild,
                        user=candidate.member,
                        action_type="inactive_kick",
                        reason=reason_text,
                        metadata={
                            "source": "inactive_members_moderation",
                            "operation_id": operation_id,
                            "greetings_reason": reason_text,
                            "days_inactive": candidate.days_inactive,
                            "inactivity_text": inactivity_text,
                        },
                        canonical_event=kick_result.get("canonical_event"),
                    )
                    stats["notify_ok"] += 1
        logger.info(
            "inactive kick pipeline guild=%s dm_ok=%s kick_ok=%s ban_ok=%s",
            guild_id,
            stats["dm_ok"],
            stats["kick_ok"],
            stats["ban_ok"],
        )
        stats["errors"] = stats["errors"][:10]
        return stats

    def build_auto_inactive_completed_embed(self, reminder_stats: dict[str, Any], kick_stats: dict[str, Any]) -> discord.Embed:
        return self.build_action_embed("🤖 Auto inattivi completata", reminder_stats, kick_stats)

    def build_action_embed(self, title: str, stats: dict[str, Any], extra: dict[str, Any] | None = None) -> discord.Embed:
        _ = title
        embed = discord.Embed(title=build_server_summary_title("INATTIVI CHECK"), color=0x57F287)
        merged = dict(stats)
        if extra:
            for key, value in extra.items():
                if isinstance(value, int):
                    merged[key] = int(merged.get(key, 0)) + value
        lines = [
            f"• DM success/fail: **{merged.get('dm_ok', 0)}/{merged.get('dm_fail', 0)}**",
            f"• Kick success/fail: **{merged.get('kick_ok', 0)}/{merged.get('kick_fail', 0)}**",
            f"• Ban success/fail: **{merged.get('ban_ok', 0)}/{merged.get('ban_fail', 0)}**",
            f"• Notify posted: **{merged.get('notify_ok', 0)}**",
        ]
        errors = merged.get("errors") or []
        if errors:
            lines.append("• Errori: " + "; ".join(errors[:10]))
        safe_set_description(embed, format_standard_description("Operazione automatica inattivi completata con riepilogo finale.", italic=True))
        safe_add_field(
            embed,
            name=format_standard_field_name("Dettagli", emoji="📌"),
            value="\n".join(lines),
            inline=False,
        )
        attach_footer_meta(embed, service_name="inactivity_moderation", used_local_processing=True)
        return embed
    @staticmethod
    def _to_rome(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ROME)
