from __future__ import annotations

import logging
import json
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from app.plugins.commands_modular.command_helpers import add_group_once
from app.plugins.commands_modular.ctx import CommandContext
from app.services.config_file_loader import load_json_file
from app.services.message_scheduler import calculate_initial_next_run

logger = logging.getLogger(__name__)


BARCELLO_TRIGGER_CONFIG_PATH = "settings/barcello_trigger.json"


def register_triggers(barcellometro_group: app_commands.Group, ctx: CommandContext) -> None:
    qna_group = app_commands.Group(name="qna", description="Trigger e limiti QnA")
    frasi_group = app_commands.Group(name="frasi", description="Trigger e regole frasi")
    barcello_group = app_commands.Group(name="barcello", description="Trigger Barcello")
    prompt_group = app_commands.Group(name="prompt", description="Trigger e campagne prompt")
    insights_group = app_commands.Group(name="insights", description="Trigger curiosità utenti")

    add_group_once(barcellometro_group, qna_group, logger)
    add_group_once(barcellometro_group, frasi_group, logger)
    add_group_once(barcellometro_group, barcello_group, logger)
    add_group_once(barcellometro_group, prompt_group, logger)
    add_group_once(barcellometro_group, insights_group, logger)

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

        per_user: dict[str, dict[str, str]] = {}
        raw_per_user = raw_state.get("per_user")
        if isinstance(raw_per_user, dict):
            for user_id, user_templates_raw in raw_per_user.items():
                if not isinstance(user_id, str) or not isinstance(user_templates_raw, dict):
                    continue
                clean_user_templates: dict[str, str] = {}
                for kind in ("DEFAULT", "FIRST"):
                    value = user_templates_raw.get(kind)
                    if isinstance(value, str):
                        clean_user_templates[kind] = value
                if clean_user_templates:
                    per_user[user_id] = clean_user_templates
        if per_user:
            state["per_user"] = per_user

        return state

    @barcello_group.command(name="on", description="Abilita trigger barcello")
    async def barcello_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "barcello", "on")

    @barcello_group.command(name="off", description="Disabilita trigger barcello")
    async def barcello_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "barcello", "off")

    @barcello_group.command(name="status", description="Stato trigger barcello")
    async def barcello_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "barcello", "status")

    @barcello_group.command(name="mood", description="Mostra o imposta mood per il canale")
    @app_commands.describe(value="Nuovo mood (se vuoto mostra lo status)")
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
    @app_commands.describe(phrase="Frase", match_mode="contains|regex")
    @app_commands.choices(
        match_mode=[
            app_commands.Choice(name="contains", value="CONTAINS"),
            app_commands.Choice(name="regex", value="REGEX"),
        ]
    )
    async def frasi_add(interaction: discord.Interaction, phrase: str, match_mode: app_commands.Choice[str]) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        await ctx.database.add_trigger_phrase(guild_id, channel_id, phrase, match_mode.value, False)
        await interaction.response.send_message("Frase aggiunta.", ephemeral=True)

    @frasi_group.command(name="remove", description="Rimuovi frase trigger")
    async def frasi_remove(interaction: discord.Interaction, id_or_phrase: str) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        phrase = id_or_phrase
        if id_or_phrase.isdigit():
            rows = await ctx.database.list_trigger_phrases(guild_id, channel_id)
            row = next((r for r in rows if int(r["id"]) == int(id_or_phrase)), None)
            if row is None:
                await interaction.response.send_message("Nessuna frase trovata per quell'id.", ephemeral=True)
                return
            phrase = str(row["phrase"])
        await ctx.database.remove_trigger_phrase(guild_id, channel_id, phrase)
        await interaction.response.send_message("Frase rimossa.", ephemeral=True)

    @frasi_group.command(name="list", description="Lista frasi")
    async def frasi_list(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        rows = await ctx.database.list_trigger_phrases(guild_id, channel_id)
        if not rows:
            await interaction.response.send_message("Nessuna frase configurata.", ephemeral=True)
            return
        lines = [f"{r['id']}. {r['phrase']} [{r['match_mode']}] {'cs' if r['case_sensitive'] else 'ci'}" for r in rows]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @frasi_group.command(name="template_show", description="Mostra template trigger frasi")
    async def frasi_template_show(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, channel_id = scope
        state = await ctx.database.get_trigger_state(guild_id, channel_id, "frasi")
        normalized = _normalize_phrase_templates_state(state)
        pretty = json.dumps(normalized, ensure_ascii=False, indent=2)
        guide = (
            "Placeholder disponibili:\n"
            "{author}, {author_name}, {phrase}, {count_user}, {last_seen_human}, {last_seen_dt}"
        )
        await interaction.response.send_message(f"```json\n{pretty}\n```\n{guide}", ephemeral=True)

    @frasi_group.command(name="template_set", description="Imposta template trigger frasi (canale)")
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
        guild_id, channel_id = scope
        state = await ctx.database.get_trigger_state(guild_id, channel_id, "frasi")
        normalized = _normalize_phrase_templates_state(state)
        templates = dict(normalized.get("templates") or {})
        templates[kind.value] = text
        normalized["templates"] = templates
        await ctx.database.set_trigger_state(guild_id, channel_id, "frasi", normalized)
        await interaction.response.send_message(f"Template {kind.value} aggiornato.", ephemeral=True)

    @frasi_group.command(name="template_set_user", description="Imposta template trigger frasi per utente")
    @app_commands.choices(
        kind=[
            app_commands.Choice(name="DEFAULT", value="DEFAULT"),
            app_commands.Choice(name="FIRST", value="FIRST"),
        ]
    )
    async def frasi_template_set_user(
        interaction: discord.Interaction,
        user: discord.Member,
        kind: app_commands.Choice[str],
        text: str,
    ) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, channel_id = scope
        state = await ctx.database.get_trigger_state(guild_id, channel_id, "frasi")
        normalized = _normalize_phrase_templates_state(state)
        per_user = dict(normalized.get("per_user") or {})
        user_id = str(user.id)
        user_templates = dict(per_user.get(user_id) or {})
        user_templates[kind.value] = text
        per_user[user_id] = user_templates
        normalized["per_user"] = per_user
        await ctx.database.set_trigger_state(guild_id, channel_id, "frasi", normalized)
        await interaction.response.send_message(f"Template {kind.value} aggiornato per {user.mention}.", ephemeral=True)

    @frasi_group.command(name="template_reset", description="Reset template trigger frasi")
    async def frasi_template_reset(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        if not await _require_mod(interaction):
            return
        guild_id, channel_id = scope
        await ctx.database.set_trigger_state(guild_id, channel_id, "frasi", {})
        await interaction.response.send_message("Template trigger frasi resettati (fallback attivo).", ephemeral=True)

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
    async def prompt_create(
        interaction: discord.Interaction,
        name: str,
        time_local: str,
        interval_minutes: int,
        prompt_text: str,
    ) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa in una guild.", ephemeral=True)
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
        campaign = await ctx.database.get_message_campaign(str(interaction.guild_id), id)
        if not campaign:
            await interaction.response.send_message("Campagna non trovata.", ephemeral=True)
            return
        if str(campaign.get("type")) != "AI_PROMPT":
            await interaction.response.send_message("Questo test è solo per AI_PROMPT.", ephemeral=True)
            return

        rendered_text, reason, debug_payload = await ctx.message_scheduler_service.preview_campaign_text(
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
            await interaction.response.send_message(
                f"Impossibile generare il test ({reason or 'no_text'}).",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("Test inviato.", ephemeral=True)
        if isinstance(interaction.channel, discord.abc.Messageable):
            await interaction.channel.send(content=rendered_text)

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

    @qna_group.command(name="limits_set", description="Imposta limite giornaliero QnA per tier")
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

    @qna_group.command(name="bonus_add", description="Aggiunge bonus domande QnA a un utente")
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
