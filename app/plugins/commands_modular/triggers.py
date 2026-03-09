from __future__ import annotations

import logging
import json
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from app.plugins.commands_modular.command_helpers import add_group_once
from app.plugins.commands_modular.ctx import CommandContext
from app.services.config_file_loader import load_json_file
from app.services.message_scheduler import calculate_initial_next_run

logger = logging.getLogger(__name__)


BARCELLO_TRIGGER_CONFIG_PATH = "settings/barcello_trigger.json"


def register_triggers(bm_group: app_commands.Group, ctx: CommandContext) -> app_commands.Group:
    qna_group = app_commands.Group(name="qna", description="QnA")
    frasi_group = app_commands.Group(name="frasi", description="Frasi")
    barcello_group = app_commands.Group(name="barcello", description="Trigger Barcello")
    prompt_group = app_commands.Group(name="prompt", description="Prompt")
    insights_group = app_commands.Group(name="insights", description="Curiosità utenti")

    add_group_once(bm_group, qna_group, logger)
    add_group_once(bm_group, barcello_group, logger)
    add_group_once(bm_group, prompt_group, logger)
    add_group_once(bm_group, insights_group, logger)

    async def _require_channel(interaction: discord.Interaction) -> tuple[str, str] | None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa il comando in un canale.", ephemeral=True)
            return None
        return str(interaction.guild_id), str(interaction.channel_id)

    async def _set_toggle(interaction: discord.Interaction, key: str, action: str) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        if key == "frasi":
            if action == "status":
                enabled = await ctx.database.get_trigger_enabled_global(guild_id, key)
                if not enabled:
                    enabled = await ctx.database.get_trigger_enabled_any_channel(guild_id, key)
                await interaction.response.send_message(f"Trigger {key} (globale server): {'on' if enabled else 'off'}", ephemeral=True)
                return
            profile = await ctx.entitlements.resolve_profile(interaction.user)
            if profile != "mod":
                await interaction.response.send_message("Non hai permessi per questa azione.", ephemeral=True)
                return
            enabled = action == "on"
            await ctx.database.set_trigger_enabled_global(guild_id, key, enabled)
            await interaction.response.send_message(
                f"Trigger {key} globale nel server {'abilitato' if enabled else 'disabilitato'}.",
                ephemeral=True,
            )
            return
        if action == "status":
            enabled = await ctx.database.get_trigger_enabled(guild_id, channel_id, key)
            await interaction.response.send_message(f"Trigger {key}: {'on' if enabled else 'off'}", ephemeral=True)
            return
        profile = await ctx.entitlements.resolve_profile(interaction.user)
        if profile != "mod":
            await interaction.response.send_message("Non hai permessi per questa azione.", ephemeral=True)
            return
        enabled = action == "on"
        await ctx.database.set_trigger_enabled(guild_id, channel_id, key, enabled)
        await interaction.response.send_message(f"Trigger {key} {'abilitato' if enabled else 'disabilitato'}.", ephemeral=True)

    async def _require_mod(interaction: discord.Interaction) -> bool:
        profile = await ctx.entitlements.resolve_profile(interaction.user)
        if profile == "mod":
            return True
        await interaction.response.send_message("Non hai permessi per questa azione.", ephemeral=True)
        return False


    def _normalize_embed_color(raw: str | None) -> str | None:
        if raw is None:
            return None
        value = raw.strip()
        if not value:
            return None

        if value.startswith("#"):
            candidate = value[1:]
            if len(candidate) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in candidate):
                return f"#{candidate.upper()}"
            return None

        lowered = value.lower()
        if lowered.startswith("0x"):
            candidate = value[2:]
            if len(candidate) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in candidate):
                return f"#{candidate.upper()}"
            return None

        if len(value) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in value):
            return f"#{value.upper()}"

        if value.isdigit():
            number = int(value, 10)
            if 0 <= number <= 0xFFFFFF:
                return f"#{number:06X}"
        return None

    def _normalize_phrase_templates_state(raw_state: dict[str, object]) -> dict[str, object]:
        state: dict[str, object] = {}

        templates: dict[str, str] = {}
        raw_templates = raw_state.get("templates")
        if isinstance(raw_templates, dict):
            for kind in ("DEFAULT", "FIRST"):
                value = raw_templates.get(kind)
                if isinstance(value, str):
                    templates[kind] = value
        if templates:
            state["templates"] = templates

        global_milestones_enabled = raw_state.get("global_milestones_enabled")
        if isinstance(global_milestones_enabled, bool):
            state["global_milestones_enabled"] = global_milestones_enabled

        return state

    def _parse_role_ids_input(raw_roles: str | None) -> list[str]:
        text = str(raw_roles or "").strip()
        if not text:
            return []
        found = re.findall(r"<@&(\d+)>", text)
        if found:
            values = found
        else:
            values = re.findall(r"\d+", text)
        return list(dict.fromkeys(values))

    def _format_phrase_row(row: dict[str, object]) -> str:
        role_ids = row.get("allowed_role_ids") if isinstance(row.get("allowed_role_ids"), list) else []
        roles_text = "tutti" if not role_ids else ", ".join(f"<@&{role_id}>" for role_id in role_ids)
        mode_raw = str(row.get("match_mode") or "CONTAINS").lower()
        cooldown_raw = row.get("cooldown_seconds")
        cooldown_text = f"{cooldown_raw}s" if cooldown_raw is not None else "nessuno"
        enabled = bool(row.get("enabled", 1))
        return " · ".join(
            [
                f"#{row.get('id')}",
                f'"{row.get("phrase")}"',
                f"mode: {mode_raw}",
                f"colore: {row.get('embed_color') or '-'}",
                f"cooldown: {cooldown_text}",
                f"ruoli: {roles_text}",
                f"stato: {'attiva' if enabled else 'disattiva'}",
            ]
        )

    def _humanize_ts(raw_ts: object) -> str:
        if not raw_ts:
            return "-"
        try:
            dt = datetime.fromisoformat(str(raw_ts))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
            minutes = max(0, int(delta.total_seconds() // 60))
            if minutes < 120:
                rel = f"{minutes}m fa"
            elif minutes < 60 * 48:
                rel = f"{minutes // 60}h fa"
            else:
                rel = f"{minutes // (60 * 24)}g fa"
            return f"{dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} ({rel})"
        except ValueError:
            return str(raw_ts)

    @barcello_group.command(name="on", description="Abilita trigger barcello")
    async def barcello_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "barcello", "on")

    @barcello_group.command(name="off", description="Disabilita trigger barcello")
    async def barcello_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "barcello", "off")

    @barcello_group.command(name="status", description="Stato trigger barcello")
    async def barcello_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "barcello", "status")

    @barcello_group.command(name="mood", description="Mostra/imposta mood")
    @app_commands.describe(value="Nuovo mood")
    async def barcello_mood(interaction: discord.Interaction, value: str | None = None) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        cfg = load_json_file(BARCELLO_TRIGGER_CONFIG_PATH)

        stored = await ctx.database.get_trigger_state(guild_id, channel_id, "barcello_mood")
        stored_mood = str(stored.get("mood") or "")

        channels_cfg = cfg.get("channels") if isinstance(cfg.get("channels"), dict) else {}
        channel_cfg = channels_cfg.get(channel_id) if isinstance(channels_cfg.get(channel_id), dict) else {}
        cfg_default = str(cfg.get("mood_default") or "chill")
        channel_default = str(channel_cfg.get("mood_default") or "")
        effective = stored_mood or channel_default or cfg_default

        time_buckets = cfg.get("time_buckets") if isinstance(cfg.get("time_buckets"), dict) else {}
        now_rome = datetime.now(ctx.timezone)
        current_hour = now_rome.hour
        time_bucket = "unknown"
        for name, payload in time_buckets.items():
            if not isinstance(payload, dict):
                continue
            start = payload.get("start")
            end = payload.get("end")
            if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= 24 and start <= current_hour < end:
                time_bucket = str(name)
                break

        daily = await ctx.database.get_trigger_state(guild_id, channel_id, "barcello_daily")
        day_key = now_rome.date().isoformat()
        counts = daily.get("counts") if isinstance(daily.get("counts"), dict) and str(daily.get("date") or "") == day_key else {}
        last_status = await ctx.database.get_barcello_trigger_state(guild_id, channel_id)
        current_color = str((last_status or {}).get("last_color") or "")
        state_count_today = int(counts.get(current_color) or 0) if current_color else 0

        tiers = cfg.get("dramatic_tiers") if isinstance(cfg.get("dramatic_tiers"), list) else [{"min_count_today": 1, "label": "t1"}]
        drama_label = "t1"
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            minimum = tier.get("min_count_today")
            label = tier.get("label")
            if isinstance(minimum, int) and isinstance(label, str) and state_count_today >= minimum:
                drama_label = label

        if value is None:
            await interaction.response.send_message(
                "\n".join(
                    [
                        f"Mood attuale: `{effective}`",
                        f"Mood salvato: `{stored_mood or '-'}`",
                        f"Mood default canale: `{channel_default or '-'}`",
                        f"Mood default globale: `{cfg_default}`",
                        f"Time bucket corrente: `{time_bucket}`",
                        f"Drama label corrente: `{drama_label}` (count {state_count_today}, stato {current_color or '-'})",
                    ]
                ),
                ephemeral=True,
            )
            return

        if not await _require_mod(interaction):
            return
        normalized = value.strip()
        if not normalized:
            await interaction.response.send_message("Inserisci un mood valido.", ephemeral=True)
            return
        cfg = load_json_file(BARCELLO_TRIGGER_CONFIG_PATH)
        available_moods = cfg.get("moods") if isinstance(cfg.get("moods"), dict) else {}
        if available_moods and normalized not in available_moods:
            await interaction.response.send_message(
                f"Mood `{normalized}` non definito in config. Disponibili: {', '.join(sorted(available_moods.keys()))}",
                ephemeral=True,
            )
            return
        today = datetime.now(ctx.timezone).date().isoformat()
        await ctx.database.set_trigger_state(
            guild_id,
            channel_id,
            "barcello_mood",
            {"mood": normalized, "date": today, "mode": "manual"},
        )
        await interaction.response.send_message(f"Mood impostato a `{normalized}` per questo canale.", ephemeral=True)

    @barcello_group.command(name="mood_reset", description="Reset mood del canale")
    async def barcello_mood_reset(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, channel_id = scope
        await ctx.database.set_trigger_state(guild_id, channel_id, "barcello_mood", {})
        await interaction.response.send_message("Mood resettato: torna al default config.", ephemeral=True)

    @frasi_group.command(name="on", description="Abilita trigger frasi")
    async def frasi_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "frasi", "on")

    @frasi_group.command(name="off", description="Disabilita trigger frasi")
    async def frasi_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "frasi", "off")

    @frasi_group.command(name="status", description="Stato trigger frasi")
    async def frasi_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "frasi", "status")

    @frasi_group.command(name="add", description="Aggiungi frase trigger")
    @app_commands.describe(
        phrase="Frase",
        match_mode="contains|regex",
        colore="Colore embed opzionale (#RRGGBB)",
        cooldown="Cooldown in secondi (opzionale)",
        ruoli="Ruoli autorizzati (menzioni o ID separati da virgole/spazi)",
    )
    @app_commands.choices(
        match_mode=[
            app_commands.Choice(name="contains", value="CONTAINS"),
            app_commands.Choice(name="regex", value="REGEX"),
        ]
    )
    async def frasi_add(
        interaction: discord.Interaction,
        phrase: str,
        match_mode: app_commands.Choice[str],
        colore: str | None = None,
        cooldown: int | None = None,
        ruoli: str | None = None,
    ) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        if cooldown is not None and cooldown <= 0:
            await interaction.response.send_message("Cooldown non valido. Inserisci un numero intero positivo di secondi.", ephemeral=True)
            return
        color = _normalize_embed_color(colore)
        if colore is not None and color is None:
            await interaction.response.send_message("Colore non valido. Usa #RRGGBB, RRGGBB, 0xRRGGBB o valore decimale.", ephemeral=True)
            return
        role_ids = _parse_role_ids_input(ruoli)
        if role_ids and interaction.guild is None:
            await interaction.response.send_message("Impossibile validare i ruoli senza guild.", ephemeral=True)
            return
        if role_ids and interaction.guild is not None:
            invalid_ids = [role_id for role_id in role_ids if interaction.guild.get_role(int(role_id)) is None]
            if invalid_ids:
                await interaction.response.send_message(
                    f"Ruoli non validi per questo server: {', '.join(invalid_ids)}",
                    ephemeral=True,
                )
                return
        await ctx.database.add_trigger_phrase(
            guild_id,
            channel_id,
            phrase,
            match_mode.value,
            False,
            color,
            cooldown,
            role_ids,
        )
        role_text = "tutti"
        if role_ids:
            role_text = ", ".join(f"<@&{role_id}>" for role_id in role_ids)
        cooldown_text = f"{cooldown}s" if cooldown is not None else "nessuno"
        await interaction.response.send_message(
            "\n".join(
                [
                    "Frase aggiunta a livello server.",
                    f"Cooldown: {cooldown_text}",
                    f"Ruoli autorizzati: {role_text}",
                ]
            ),
            ephemeral=True,
        )

    @frasi_group.command(name="remove", description="Rimuovi frase trigger")
    async def frasi_remove(interaction: discord.Interaction, id_or_phrase: str) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, _ = scope
        if id_or_phrase.isdigit():
            await ctx.database.remove_trigger_phrase_by_id(guild_id, int(id_or_phrase))
        else:
            await ctx.database.remove_trigger_phrase_guild(guild_id, id_or_phrase)
        await interaction.response.send_message("Frase rimossa.", ephemeral=True)

    @frasi_group.command(name="list", description="Lista frasi")
    async def frasi_list(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, _ = scope
        rows = await ctx.database.list_trigger_phrases_guild(guild_id)
        if not rows:
            await interaction.response.send_message("Nessuna frase configurata.", ephemeral=True)
            return
        lines: list[str] = []
        for row in rows:
            lines.append(_format_phrase_row(row))
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @frasi_group.command(name="edit", description="Modifica frase trigger esistente")
    @app_commands.describe(
        id="ID frase da modificare",
        frase="Nuovo testo frase",
        match_mode="contains|regex",
        colore="Nuovo colore (#RRGGBB)",
        cooldown="Nuovo cooldown in secondi",
        ruoli="Nuovi ruoli autorizzati (menzioni/ID)",
        reset_ruoli="Rimuovi allowlist ruoli",
        reset_cooldown="Rimuovi cooldown",
        reset_colore="Rimuovi colore personalizzato",
        attiva="Abilita/disabilita la singola frase",
    )
    @app_commands.choices(
        match_mode=[
            app_commands.Choice(name="contains", value="CONTAINS"),
            app_commands.Choice(name="regex", value="REGEX"),
        ]
    )
    async def frasi_edit(
        interaction: discord.Interaction,
        id: int,
        frase: str | None = None,
        match_mode: app_commands.Choice[str] | None = None,
        colore: str | None = None,
        cooldown: int | None = None,
        ruoli: str | None = None,
        reset_ruoli: bool = False,
        reset_cooldown: bool = False,
        reset_colore: bool = False,
        attiva: bool | None = None,
    ) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, _ = scope

        row = await ctx.database.get_trigger_phrase_by_id(guild_id, id)
        if not row:
            await interaction.response.send_message(f"Frase #{id} non trovata in questa guild.", ephemeral=True)
            return

        if reset_ruoli and ruoli:
            await interaction.response.send_message("Non puoi usare insieme `ruoli` e `reset_ruoli=true`.", ephemeral=True)
            return
        if reset_cooldown and cooldown is not None:
            await interaction.response.send_message("Non puoi usare insieme `cooldown` e `reset_cooldown=true`.", ephemeral=True)
            return
        if reset_colore and colore is not None:
            await interaction.response.send_message("Non puoi usare insieme `colore` e `reset_colore=true`.", ephemeral=True)
            return

        if cooldown is not None and cooldown <= 0:
            await interaction.response.send_message("Cooldown non valido. Inserisci un numero intero positivo di secondi.", ephemeral=True)
            return

        parsed_color: str | None = None
        if colore is not None:
            parsed_color = _normalize_embed_color(colore)
            if parsed_color is None:
                await interaction.response.send_message("Colore non valido. Usa #RRGGBB, RRGGBB, 0xRRGGBB o valore decimale.", ephemeral=True)
                return

        role_ids: list[str] | None = None
        if ruoli is not None:
            role_ids = _parse_role_ids_input(ruoli)
            if interaction.guild is None:
                await interaction.response.send_message("Impossibile validare i ruoli senza guild.", ephemeral=True)
                return
            invalid_ids = [role_id for role_id in role_ids if interaction.guild.get_role(int(role_id)) is None]
            if invalid_ids:
                await interaction.response.send_message(f"Ruoli non validi per questo server: {', '.join(invalid_ids)}", ephemeral=True)
                return

        requested = any(
            [
                frase is not None,
                match_mode is not None,
                colore is not None,
                cooldown is not None,
                ruoli is not None,
                reset_ruoli,
                reset_cooldown,
                reset_colore,
                attiva is not None,
            ]
        )
        if not requested:
            await interaction.response.send_message("Nessuna modifica richiesta.", ephemeral=True)
            return

        updated = await ctx.database.update_trigger_phrase(
            guild_id,
            id,
            phrase=frase,
            match_mode=match_mode.value if match_mode is not None else None,
            embed_color=parsed_color if colore is not None else None,
            set_embed_color=colore is not None or reset_colore,
            cooldown_seconds=cooldown,
            set_cooldown_seconds=cooldown is not None or reset_cooldown,
            allowed_role_ids=role_ids,
            set_allowed_role_ids=ruoli is not None or reset_ruoli,
            enabled=attiva,
        )
        if not updated:
            await interaction.response.send_message("Nessuna modifica richiesta.", ephemeral=True)
            return
        row_after = await ctx.database.get_trigger_phrase_by_id(guild_id, id)
        await interaction.response.send_message(
            "\n".join(
                [
                    f"Frase #{id} aggiornata a livello server.",
                    _format_phrase_row(row_after),
                ]
            ),
            ephemeral=True,
        )

    @frasi_group.command(name="stats", description="Statistiche dettagliate di una frase")
    @app_commands.describe(id="ID frase")
    async def frasi_stats(interaction: discord.Interaction, id: int) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, _ = scope
        phrase = await ctx.database.get_trigger_phrase_by_id(guild_id, id)
        if not phrase:
            await interaction.response.send_message(f"Frase #{id} non trovata in questa guild.", ephemeral=True)
            return

        summary = await ctx.database.get_trigger_phrase_stats_summary(guild_id, id)
        top_users = await ctx.database.list_trigger_phrase_user_stats(guild_id, id, limit=10)
        global_milestones_enabled = await ctx.database.get_trigger_phrase_global_milestones_enabled(guild_id)
        global_milestones = await ctx.database.list_trigger_phrase_global_milestones(guild_id)

        embed = discord.Embed(
            title=f"📊 STATISTICHE FRASE #{id}",
            description=str(phrase.get("phrase") or ""),
            color=discord.Color.blurple(),
        )
        unique_users = int(summary.get("unique_users") or 0)
        total_uses = int(summary.get("total_uses") or 0)
        avg = (total_uses / unique_users) if unique_users > 0 else 0
        embed.add_field(name="Utenti unici", value=str(unique_users), inline=True)
        embed.add_field(name="Utilizzi totali", value=str(total_uses), inline=True)
        embed.add_field(name="Media per utente", value=f"{avg:.2f}" if unique_users > 0 else "-", inline=True)
        embed.add_field(name="Ultima attività frase", value=_humanize_ts(summary.get("last_seen_ts_max") or phrase.get("last_seen_ts")), inline=False)
        embed.add_field(name="Milestone globali", value="ON" if global_milestones_enabled else "OFF", inline=True)
        embed.add_field(name="N. milestone globali", value=str(len(global_milestones)), inline=True)

        if not top_users:
            embed.add_field(name="Top utenti", value="Nessun utilizzo registrato.", inline=False)
        else:
            lines: list[str] = []
            for idx, row in enumerate(top_users, start=1):
                user_id = str(row.get("user_id") or "")
                user_label = user_id
                if interaction.guild is not None and user_id.isdigit():
                    member = interaction.guild.get_member(int(user_id))
                    if member is not None:
                        user_label = member.mention
                lines.append(
                    f"{idx}. {user_label} — {int(row.get('count') or 0)} volte — ultima: {_humanize_ts(row.get('last_seen_ts'))}"
                )
            embed.add_field(name="Top utenti", value="\n".join(lines), inline=False)

        embed.set_footer(text="Servizio offerto dal vostro Barcellometro di fiducia.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @frasi_group.command(name="milestone_global_on", description="Abilita milestone globali")
    async def frasi_milestone_global_on(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, _ = scope
        await ctx.database.set_trigger_phrase_global_milestones_enabled(guild_id, True)
        await interaction.response.send_message("Milestone globali abilitate.", ephemeral=True)

    @frasi_group.command(name="milestone_global_off", description="Disabilita milestone globali")
    async def frasi_milestone_global_off(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, _ = scope
        await ctx.database.set_trigger_phrase_global_milestones_enabled(guild_id, False)
        await interaction.response.send_message("Milestone globali disabilitate.", ephemeral=True)

    @frasi_group.command(name="milestone_global_status", description="Stato milestone globali")
    async def frasi_milestone_global_status(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, _ = scope
        enabled = await ctx.database.get_trigger_phrase_global_milestones_enabled(guild_id)
        rows = await ctx.database.list_trigger_phrase_global_milestones(guild_id)
        await interaction.response.send_message(
            f"Milestone globali: {'ON' if enabled else 'OFF'} · configurate: {len(rows)}",
            ephemeral=True,
        )

    @frasi_group.command(name="milestone_global_set", description="Imposta/aggiorna milestone globale")
    @app_commands.describe(soglia="Soglia conteggio utente", testo="Template milestone globale")
    async def frasi_milestone_global_set(interaction: discord.Interaction, soglia: int, testo: str) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, _ = scope
        if soglia < 2:
            await interaction.response.send_message("La soglia deve essere >= 2.", ephemeral=True)
            return
        text_clean = testo.strip()
        if not text_clean:
            await interaction.response.send_message("Il testo milestone non può essere vuoto.", ephemeral=True)
            return
        await ctx.database.set_trigger_phrase_global_milestone(guild_id, soglia, text_clean)
        await interaction.response.send_message(f"Milestone globale impostata alla soglia {soglia}.", ephemeral=True)

    @frasi_group.command(name="milestone_global_remove", description="Rimuovi milestone globale")
    @app_commands.describe(soglia="Soglia milestone")
    async def frasi_milestone_global_remove(interaction: discord.Interaction, soglia: int) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, _ = scope
        deleted = await ctx.database.delete_trigger_phrase_global_milestone(guild_id, soglia)
        if not deleted:
            await interaction.response.send_message(f"Nessuna milestone globale alla soglia {soglia}.", ephemeral=True)
            return
        await interaction.response.send_message(f"Milestone globale rimossa alla soglia {soglia}.", ephemeral=True)

    @frasi_group.command(name="milestone_global_list", description="Lista milestone globali")
    async def frasi_milestone_global_list(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, _ = scope
        milestones = await ctx.database.list_trigger_phrase_global_milestones(guild_id)
        if not milestones:
            await interaction.response.send_message("Nessuna milestone globale configurata.", ephemeral=True)
            return
        lines = [f"{int(m['threshold_count'])} → \"{str(m['template_text'])}\"" for m in milestones]
        await interaction.response.send_message("\n".join(["Milestone globali:", *lines]), ephemeral=True)

    @frasi_group.command(name="template_show", description="Mostra template trigger frasi")
    async def frasi_template_show(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, _ = scope
        state = await ctx.database.get_trigger_state_any_channel(guild_id, "frasi")
        normalized = _normalize_phrase_templates_state(state)
        pretty = json.dumps(normalized, ensure_ascii=False, indent=2)
        guide = (
            "Placeholder disponibili:\n"
            "{author}, {author_name}, {phrase}, {count_user_prev}, {count_user}, {last_seen_human}, {last_seen_dt}, {milestone}, {custom_user_phrase}\n"
            "Nota: i template per-user legacy non sono più usati a runtime; usa /frasi userphrase_set."
        )
        await interaction.response.send_message(f"```json\n{pretty}\n```\n{guide}", ephemeral=True)

    @frasi_group.command(name="template_set", description="Template frasi server")
    @app_commands.choices(
        kind=[
            app_commands.Choice(name="DEFAULT", value="DEFAULT"),
            app_commands.Choice(name="FIRST", value="FIRST"),
        ]
    )
    async def frasi_template_set(interaction: discord.Interaction, kind: app_commands.Choice[str], text: str) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, _ = scope
        state = await ctx.database.get_trigger_state_any_channel(guild_id, "frasi")
        normalized = _normalize_phrase_templates_state(state)
        templates = dict(normalized.get("templates") or {})
        templates[kind.value] = text
        normalized["templates"] = templates
        await ctx.database.set_trigger_state_global(guild_id, "frasi", normalized)
        await interaction.response.send_message(f"Template {kind.value} aggiornato.", ephemeral=True)

    @frasi_group.command(name="template_reset", description="Reset template trigger frasi")
    async def frasi_template_reset(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, _ = scope
        await ctx.database.set_trigger_state_global(guild_id, "frasi", {})
        await interaction.response.send_message("Template trigger frasi globali resettati (DEFAULT/FIRST).", ephemeral=True)

    @frasi_group.command(name="userphrase_set", description="Imposta frase custom globale utente")
    async def frasi_userphrase_set(interaction: discord.Interaction, utente: discord.Member, testo: str) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, _ = scope
        text_clean = testo.strip()
        if not text_clean:
            await interaction.response.send_message("Il testo non può essere vuoto.", ephemeral=True)
            return
        if len(text_clean) > 300:
            await interaction.response.send_message("Testo troppo lungo (max 300 caratteri).", ephemeral=True)
            return
        await ctx.database.upsert_trigger_phrase_global_user_custom_text(guild_id, str(utente.id), text_clean)
        await interaction.response.send_message(f"Frase custom globale aggiornata per {utente.mention}.", ephemeral=True)

    @frasi_group.command(name="userphrase_remove", description="Rimuovi frase custom globale utente")
    async def frasi_userphrase_remove(interaction: discord.Interaction, utente: discord.Member) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, _ = scope
        removed = await ctx.database.delete_trigger_phrase_global_user_custom_text(guild_id, str(utente.id))
        if not removed:
            await interaction.response.send_message(f"Nessuna frase custom globale trovata per {utente.mention}.", ephemeral=True)
            return
        await interaction.response.send_message(f"Frase custom globale rimossa per {utente.mention}.", ephemeral=True)

    @frasi_group.command(name="userphrase_show", description="Mostra frase custom globale utente")
    async def frasi_userphrase_show(interaction: discord.Interaction, utente: discord.Member) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, _ = scope
        text = await ctx.database.get_trigger_phrase_global_user_custom_text(guild_id, str(utente.id))
        if not text:
            await interaction.response.send_message(f"{utente.mention} non ha una frase custom globale.", ephemeral=True)
            return
        await interaction.response.send_message(f"{utente.mention} → {text}", ephemeral=True)

    @frasi_group.command(name="userphrase_list", description="Lista frasi custom globali utenti")
    async def frasi_userphrase_list(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, _ = scope
        rows = await ctx.database.list_trigger_phrase_global_user_custom_texts(guild_id)
        if not rows:
            await interaction.response.send_message("Nessuna frase custom globale configurata.", ephemeral=True)
            return
        lines: list[str] = []
        for row in rows[:30]:
            user_id = str(row.get("user_id") or "")
            mention = f"<@{user_id}>" if user_id.isdigit() else user_id
            lines.append(f"{mention} → {row.get('custom_text')}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @prompt_group.command(name="on", description="Abilita trigger prompt")
    async def prompt_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "prompt", "on")

    @prompt_group.command(name="off", description="Disabilita trigger prompt")
    async def prompt_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "prompt", "off")

    @prompt_group.command(name="status", description="Stato trigger prompt")
    async def prompt_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "prompt", "status")

    @prompt_group.command(name="create", description="Crea campagna AI_PROMPT")
    @app_commands.describe(
        embed_title="Titolo embed opzionale",
        embed_color="Colore embed opzionale",
    )
    async def prompt_create(
        interaction: discord.Interaction,
        name: str,
        time_local: str,
        interval_minutes: int,
        prompt_text: str,
        embed_title: str | None = None,
        embed_color: str | None = None,
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa in una guild.", ephemeral=True)
            return
        if ctx.message_scheduler is not None and not ctx.message_scheduler.is_valid_embed_color(embed_color):
            await interaction.response.send_message("embed_color non valido. Usa #RRGGBB, RRGGBB oppure 0xRRGGBB.", ephemeral=True)
            return
        next_run = calculate_initial_next_run(datetime.now(timezone.utc), time_local, interval_minutes, ctx.timezone)
        campaign_id = await ctx.database.create_message_campaign(
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            campaign_type="AI_PROMPT",
            name=name,
            text=prompt_text,
            text_green=None,
            text_yellow=None,
            text_red=None,
            text_black=None,
            enabled=True,
            start_time_local=time_local,
            interval_minutes=interval_minutes,
            jitter_seconds=0,
            only_if_idle_minutes=0,
            mood_mode="IGNORE_BARCELLO",
            next_run_at=next_run.isoformat(),
            created_by=str(interaction.user.id),
            embed_title=embed_title,
            embed_color=embed_color,
        )
        await interaction.response.send_message(f"Campagna AI_PROMPT creata: {campaign_id}", ephemeral=True)

    @prompt_group.command(name="list", description="Lista campagne AI_PROMPT")
    async def prompt_list(interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa in una guild.", ephemeral=True)
            return
        rows = await ctx.database.list_message_campaigns(str(interaction.guild_id), include_disabled=True)
        rows = [r for r in rows if str(r["type"]) == "AI_PROMPT"]
        if not rows:
            await interaction.response.send_message("Nessuna campagna AI_PROMPT.", ephemeral=True)
            return
        await interaction.response.send_message(
            "\n".join(
                [
                    f"ID {r['id']} {'on' if r['enabled'] else 'off'} {r['name'] or '-'} ch={r['channel_id'] or '-'} next={r['next_run_at'] or '-'}"
                    f" embed_title={r['embed_title'] or '-'} embed_color={r['embed_color'] or '-'}"
                    for r in rows
                ]
            ),
            ephemeral=True,
        )

    @prompt_group.command(name="delete", description="Elimina campagna AI_PROMPT")
    async def prompt_delete(interaction: discord.Interaction, id_or_name: str) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa in una guild.", ephemeral=True)
            return
        campaign_id: int | None = int(id_or_name) if id_or_name.isdigit() else None
        if campaign_id is None:
            rows = await ctx.database.list_message_campaigns(str(interaction.guild_id), include_disabled=True)
            row = next((r for r in rows if str(r["type"]) == "AI_PROMPT" and str(r["name"] or "") == id_or_name), None)
            if row is None:
                await interaction.response.send_message("Campagna non trovata.", ephemeral=True)
                return
            campaign_id = int(row["id"])
        await ctx.database.soft_delete_message_campaign(str(interaction.guild_id), campaign_id)
        await interaction.response.send_message("Campagna eliminata.", ephemeral=True)

    @prompt_group.command(name="test", description="Genera e invia un test AI_PROMPT")
    @app_commands.describe(id="ID campagna")
    async def prompt_test(interaction: discord.Interaction, id: int) -> None:
        if not await _require_mod(interaction):
            return
        if interaction.guild_id is None or interaction.channel is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa in una guild.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        campaign = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not campaign:
            await interaction.followup.send("Campagna non trovata.", ephemeral=True)
            return
        if not isinstance(campaign, dict) and hasattr(campaign, "keys"):
            campaign = dict(campaign)

        logger.info(
            "prompt_test campaign_id=%s type=%s user=%s channel=%s",
            id,
            campaign.get("type"),
            interaction.user.id,
            interaction.channel_id,
        )
        if str(campaign.get("type")) != "AI_PROMPT":
            await interaction.followup.send("Questo test è solo per AI_PROMPT.", ephemeral=True)
            return

        if ctx.message_scheduler is None:
            await interaction.followup.send("Servizio scheduler non disponibile.", ephemeral=True)
            return

        logger.info("prompt_test campaign_id=%s used_service=%s", id, "message_scheduler")
        rendered_text, reason, debug_payload = await ctx.message_scheduler.preview_campaign_text(
            campaign,
            channel_id_override=str(interaction.channel_id),
        )
        logger.info(
            "prompt_test campaign_id=%s user=%s channel=%s ai_called=%s reason=%s",
            id,
            interaction.user.id,
            interaction.channel_id,
            "yes" if debug_payload.get("selected_source") == "ai" else "no",
            reason,
        )
        if not rendered_text:
            await interaction.followup.send(
                f"Impossibile generare il test ({reason or 'no_text'}).",
                ephemeral=True,
            )
            return

        await interaction.followup.send("Test inviato.", ephemeral=True)
        if isinstance(interaction.channel, discord.abc.Messageable):
            await ctx.message_scheduler.send_campaign_embed(interaction.channel, campaign, rendered_text)

    @qna_group.command(name="on", description="Abilita trigger qna")
    async def qna_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "qna", "on")

    @qna_group.command(name="off", description="Disabilita trigger qna")
    async def qna_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "qna", "off")

    @qna_group.command(name="status", description="Stato trigger qna")
    async def qna_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "qna", "status")

    @qna_group.command(name="limits_show", description="Mostra limiti giornalieri QnA")
    async def qna_limits_show(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        profile = await ctx.entitlements.resolve_profile(interaction.user)
        if profile != "mod":
            await interaction.response.send_message("Non hai permessi per questa azione.", ephemeral=True)
            return
        raw = await ctx.database.get_setting("qna.daily_limits")
        defaults = {"base": 0, "role1": 1, "role2": 2, "role3": 3, "mod": 999}
        if not raw:
            data = defaults
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = defaults
            data = parsed if isinstance(parsed, dict) else defaults
        pretty = json.dumps(data, ensure_ascii=False, indent=2)
        await interaction.response.send_message(f"```json\n{pretty}\n```", ephemeral=True)

    @qna_group.command(name="limits_set", description="Imposta limite QnA tier")
    async def qna_limits_set(interaction: discord.Interaction, tier_key: str, limit_int: int) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        profile = await ctx.entitlements.resolve_profile(interaction.user)
        if profile != "mod":
            await interaction.response.send_message("Non hai permessi per questa azione.", ephemeral=True)
            return
        allowed_keys = {"base", "role1", "role2", "role3", "mod"}
        key = tier_key.strip().lower()
        if key not in allowed_keys:
            await interaction.response.send_message("tier_key non valido. Usa: base, role1, role2, role3, mod.", ephemeral=True)
            return
        if limit_int < 0 or limit_int > 999:
            await interaction.response.send_message("limit_int deve essere tra 0 e 999.", ephemeral=True)
            return
        raw = await ctx.database.get_setting("qna.daily_limits")
        data = {"base": 0, "role1": 1, "role2": 2, "role3": 3, "mod": 999}
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                data.update(parsed)
        data[key] = int(limit_int)
        await ctx.database.set_setting("qna.daily_limits", json.dumps(data, ensure_ascii=False))
        await interaction.response.send_message(f"Limite aggiornato: {key}={limit_int}", ephemeral=True)

    @qna_group.command(name="bonus_add", description="Aggiungi bonus QnA utente")
    async def qna_bonus_add(interaction: discord.Interaction, user: discord.Member, amount_int: int, hours_valid: int | None = None) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa in una guild.", ephemeral=True)
            return
        profile = await ctx.entitlements.resolve_profile(interaction.user)
        if profile != "mod":
            await interaction.response.send_message("Non hai permessi per questa azione.", ephemeral=True)
            return
        if amount_int < 0 or amount_int > 999:
            await interaction.response.send_message("amount_int deve essere tra 0 e 999.", ephemeral=True)
            return
        expires_at = None
        if hours_valid is not None:
            if hours_valid <= 0 or hours_valid > 24 * 30:
                await interaction.response.send_message("hours_valid non valido (1..720).", ephemeral=True)
                return
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours_valid)).isoformat()
        current_bonus, _ = await ctx.database.get_qna_bonus(str(interaction.guild_id), str(user.id))
        new_bonus = current_bonus + int(amount_int)
        await ctx.database.set_qna_bonus(str(interaction.guild_id), str(user.id), new_bonus, expires_at)
        await interaction.response.send_message(
            f"Bonus impostato per {user.mention}: {current_bonus} → {new_bonus}" + (f" fino a {expires_at}" if expires_at else ""),
            ephemeral=True,
        )

    @qna_group.command(name="bonus_clear", description="Rimuove bonus domande QnA")
    async def qna_bonus_clear(interaction: discord.Interaction, user: discord.Member) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa in una guild.", ephemeral=True)
            return
        profile = await ctx.entitlements.resolve_profile(interaction.user)
        if profile != "mod":
            await interaction.response.send_message("Non hai permessi per questa azione.", ephemeral=True)
            return
        await ctx.database.clear_qna_bonus(str(interaction.guild_id), str(user.id))
        await interaction.response.send_message(f"Bonus rimosso per {user.mention}.", ephemeral=True)

    @qna_group.command(name="bonus_show", description="Mostra bonus domande QnA")
    async def qna_bonus_show(interaction: discord.Interaction, user: discord.Member) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa in una guild.", ephemeral=True)
            return
        profile = await ctx.entitlements.resolve_profile(interaction.user)
        if profile != "mod":
            await interaction.response.send_message("Non hai permessi per questa azione.", ephemeral=True)
            return
        bonus, expires_at = await ctx.database.get_qna_bonus(str(interaction.guild_id), str(user.id))
        await interaction.response.send_message(
            f"Bonus attivo per {user.mention}: {bonus}\nScadenza: {expires_at or '-'}",
            ephemeral=True,
        )

    @insights_group.command(name="on", description="Abilita trigger curiosità utenti")
    async def insights_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "insights", "on")

    @insights_group.command(name="off", description="Disabilita trigger curiosità utenti")
    async def insights_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "insights", "off")

    @insights_group.command(name="status", description="Stato trigger curiosità utenti")
    async def insights_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "insights", "status")

    return frasi_group
