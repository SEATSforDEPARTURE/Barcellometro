from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission
from app.services.ai_model_catalog import build_model_autocomplete_choices
from app.services.footer import ServiceFooterProfile, ServiceFooterVariant, _is_persistable_service_name


def _clean_opt(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _format_value(value: str | None) -> str:
    return value if value else "(non impostata)"


def _human_service_name(service_name: str) -> str:
    labels = {
        "campagne_notizie": "campagne_notizie",
        "campagne_meteo": "campagne_meteo",
        "campagne_oroscopo": "campagne_oroscopo",
        "campagne_prompt": "campagne_prompt",
        "campagne_timer": "campagne_timer",
    }
    return labels.get(service_name, service_name.replace("_", " ").title())


def _format_contributors(contributors: list[str]) -> str:
    return " + ".join(contributors) if contributors else "(nessuno)"


def _format_variant_block(service_name: str, variant: ServiceFooterVariant, phrase: str) -> str:
    mode = "local" if variant.used_local_processing else "remote"
    footer_text = variant.last_rendered_footer or "(footer non ancora renderizzato)"
    origins = ",".join(sorted(variant.origins or [])) or "(n/d)"
    updated = variant.updated_at or "(n/d)"
    return (
        f"variante: {mode} | {_format_contributors(variant.contributors)}\n"
        f"→ {footer_text}\n"
        f"frase: {phrase}\n"
        f"origine: {origins}\n"
        f"aggiornato: {updated}\n"
        f"chiave: {variant.variant_key}"
    )


def _format_service_header(service_name: str) -> str:
    return f"**{service_name}**\nlabel: {_human_service_name(service_name)}\nalias tecnico: `{service_name}`"


def _service_section(service_name: str) -> int:
    if service_name in {"campagne_notizie", "campagne_meteo", "campagne_oroscopo"}:
        return 1
    if service_name == "campagne_prompt":
        return 2
    if service_name == "campagne_timer":
        return 3
    return 0


def _split_long_text(text: str, max_len: int = 1900) -> list[str]:
    clean_text = text.strip()
    if not clean_text:
        return []
    if len(clean_text) <= max_len:
        return [clean_text]

    parts: list[str] = []
    for line in clean_text.split("\n"):
        if len(line) <= max_len:
            parts.append(line)
            continue
        for idx in range(0, len(line), max_len):
            parts.append(line[idx : idx + max_len])

    chunks: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}\n{part}" if current else part
        if len(candidate) <= max_len:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = part
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def _chunk_status_blocks(blocks: list[str], max_len: int = 1900) -> list[str]:
    chunks: list[str] = []
    current = ""

    for raw_block in blocks:
        block = raw_block.strip()
        if not block:
            continue
        if len(block) > max_len:
            split_blocks = _split_long_text(block, max_len=max_len)
        else:
            split_blocks = [block]

        for split_block in split_blocks:
            candidate = f"{current}\n\n{split_block}" if current else split_block
            if len(candidate) <= max_len:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = split_block
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]

def _truncate_embed_text(value: str | None, limit: int = 1000) -> str:
    text = (value or "").strip()
    if not text:
        return "(vuoto)"
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"



async def _infer_audio_notes_profile(ctx: CommandContext) -> ServiceFooterProfile:
    stt_backend = ((await ctx.database.get_setting("stt.backend")) or "local").strip().lower()
    translate_backend = ((await ctx.database.get_setting("translate.backend")) or "local").strip().lower()
    stt_local_model = ((await ctx.database.get_setting("stt.local.model")) or "small").strip()
    stt_ai_model = ctx.ai.get_runtime_model("transcription") if ctx.ai is not None else "openai:gpt-4o-transcribe"
    translate_ai_model = ctx.ai.get_runtime_model("translation") if ctx.ai is not None else "openai:gpt-4o-mini"

    stt_model = stt_local_model if stt_backend != "ai" else (stt_ai_model or "gpt-4o-transcribe")
    translation_model = "argos" if translate_backend != "ai" else (translate_ai_model or "gpt-4o-mini")

    contributors: list[str] = []
    if stt_model:
        contributors.append(stt_model)
    if translation_model:
        contributors.append(translation_model)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in contributors:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        deduped.append(clean)

    return ServiceFooterProfile(
        service_name="audio_notes",
        contributors=deduped,
        used_local_processing=(stt_backend != "ai" or translate_backend != "ai"),
        last_rendered_footer=None,
        updated_at=None,
        origins={"inference"},
    )


async def _infer_service_profile(service_name: str, ctx: CommandContext) -> ServiceFooterProfile:
    if service_name == "audio_notes":
        return await _infer_audio_notes_profile(ctx)
    return ServiceFooterProfile(
        service_name=service_name,
        contributors=[],
        used_local_processing=True,
        last_rendered_footer=None,
        updated_at=None,
        origins={"fallback"},
    )


def register_admin(bm_group: app_commands.Group, ctx: CommandContext) -> None:
    ai_task_choices = [
        app_commands.Choice(name="summary", value="summary"),
        app_commands.Choice(name="server_summary", value="server_summary"),
        app_commands.Choice(name="audio_summary", value="audio_summary"),
        app_commands.Choice(name="qa", value="qa"),
        app_commands.Choice(name="analysis", value="analysis"),
        app_commands.Choice(name="transcription", value="transcription"),
        app_commands.Choice(name="translation", value="translation"),
        app_commands.Choice(name="campaign_editorial", value="campaign_editorial"),
        app_commands.Choice(name="campaign_prompt", value="campaign_prompt"),
    ]
    @bm_group.command(name="check", description="Attiva/disattiva raccolta eventi")
    @app_commands.describe(state="on/off")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def check_command(interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        if not await check_permission(interaction, "bm.check", ctx):
            return
        if not interaction.channel or not isinstance(interaction.channel, discord.abc.GuildChannel):
            await interaction.response.send_message("Questo comando funziona solo nei canali della guild.", ephemeral=True)
            return
        enabled = 1 if state.value == "on" else 0
        await ctx.database.upsert_channel(
            channel_id=str(interaction.channel.id),
            guild_id=str(interaction.guild_id),
            name=interaction.channel.name,
            enabled=enabled,
            channel_type=str(interaction.channel.type),
            category_id=str(interaction.channel.category_id) if interaction.channel.category_id else None,
            is_nsfw=1 if interaction.channel.is_nsfw() else 0,
            slowmode_delay=interaction.channel.slowmode_delay,
        )
        await interaction.response.send_message(
            f"Canale {'abilitato' if enabled else 'disabilitato'} per la raccolta eventi.",
            ephemeral=True,
        )

    @bm_group.command(name="retention", description="Gestisci la retention dei dati")
    @app_commands.describe(action="get/set", days="Numero di giorni di retention")
    @app_commands.choices(action=[app_commands.Choice(name="get", value="get"), app_commands.Choice(name="set", value="set")])
    async def retention_command(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        days: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.retention", ctx):
            return
        if action.value == "get":
            current = await ctx.retention.get_retention_days()
            await interaction.response.send_message(f"Retention attuale: {current} giorni.", ephemeral=True)
            return
        if days is None or days <= 0:
            await interaction.response.send_message("Specifica un numero di giorni valido.", ephemeral=True)
            return
        await ctx.retention.set_retention_days(days)
        await interaction.response.send_message(f"Retention aggiornata a {days} giorni.", ephemeral=True)

    @bm_group.command(name="backfill", description="Gestisci il backfill dei dati")
    @app_commands.describe(state="on/off", days="Numero di giorni di backfill")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def backfill_command(
        interaction: discord.Interaction,
        state: app_commands.Choice[str] | None = None,
        days: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.backfill", ctx):
            return
        if interaction.response.is_done():
            responder = interaction.followup
        else:
            responder = interaction.response
        if state is None and days is None:
            current_days = await ctx.backfill.get_backfill_days()
            enabled = await ctx.backfill.is_enabled()
            await responder.send_message(
                f"Backfill {'attivo' if enabled else 'disattivato'} ({current_days} giorni).",
                ephemeral=True,
            )
            return

        if days is not None:
            if days <= 0:
                await responder.send_message("Specifica un numero di giorni valido.", ephemeral=True)
                return
            await ctx.backfill.set_backfill_days(days)

        if state is not None:
            await ctx.backfill.set_enabled(state.value == "on")

        if await ctx.backfill.is_enabled():
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
            result = await ctx.backfill.run_once(force_full_window=True)
            await interaction.followup.send(
                "Backfill completato. "
                f"Messaggi: {result.messages}, Eventi: {result.events}, Canali: {result.channels}, Errori: {result.errors}.",
                ephemeral=True,
            )
            return

        await responder.send_message("Backfill disattivato.", ephemeral=True)

    ai_group = app_commands.Group(name="ai", description="Gestione servizio AI")
    bm_group.add_command(ai_group)

    async def _autocomplete_ai_model(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        selected_task = getattr(interaction.namespace, "task", None)
        task_value = selected_task.value if isinstance(selected_task, app_commands.Choice) else selected_task
        return await build_model_autocomplete_choices(task_value, current)

    def _is_valid_provider_model(value: str) -> bool:
        return ":" in value and bool(value.split(":", 1)[0].strip()) and bool(value.split(":", 1)[1].strip())

    @ai_group.command(name="on", description="Abilita il servizio AI")
    async def ai_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.ai", ctx):
            return
        await ctx.ai.set_enabled(True)
        await interaction.response.send_message("AI abilitata.", ephemeral=True)

    @ai_group.command(name="off", description="Disabilita il servizio AI")
    async def ai_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.ai", ctx):
            return
        await ctx.ai.set_enabled(False)
        await interaction.response.send_message("AI disabilitata.", ephemeral=True)

    @ai_group.command(name="model", description="Imposta il modello AI per un task")
    @app_commands.describe(task="Task AI", model="Seleziona o cerca un modello (provider:model)")
    @app_commands.choices(task=ai_task_choices)
    @app_commands.autocomplete(model=_autocomplete_ai_model)
    async def ai_model_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str],
        model: str,
    ) -> None:
        if not await check_permission(interaction, "bm.ai-model", ctx):
            return
        if not _is_valid_provider_model(model):
            await interaction.response.send_message(
                "Formato non valido. Seleziona un modello dai suggerimenti oppure usa provider:model, ad esempio openai:gpt-4o-mini o ollama:qwen2.5:1.5b.",
                ephemeral=True,
            )
            return
        await ctx.ai.set_model(task.value, model)
        embed = discord.Embed(title="🧠 Modello AI aggiornato", color=discord.Color.green())
        embed.add_field(name="Task", value=task.value, inline=True)
        embed.add_field(name="Model", value=model, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai_group.command(name="fallback-model", description="Imposta il modello AI di fallback per un task")
    @app_commands.describe(task="Task AI", model="Seleziona o cerca un modello (provider:model)")
    @app_commands.choices(task=ai_task_choices)
    @app_commands.autocomplete(model=_autocomplete_ai_model)
    async def ai_fallback_model_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str],
        model: str,
    ) -> None:
        if not await check_permission(interaction, "bm.ai-model", ctx):
            return
        if not _is_valid_provider_model(model):
            await interaction.response.send_message(
                "Formato non valido. Seleziona un modello dai suggerimenti oppure usa provider:model, ad esempio openai:gpt-4o-mini o ollama:qwen2.5:1.5b.",
                ephemeral=True,
            )
            return
        await ctx.ai.set_fallback_model(task.value, model)
        embed = discord.Embed(title="🧠 Fallback AI aggiornato", color=discord.Color.green())
        embed.add_field(name="Task", value=task.value, inline=True)
        embed.add_field(name="Model", value=model, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai_group.command(name="status", description="Mostra stato e modelli AI")
    async def ai_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.ai", ctx):
            return
        status = ctx.ai.status()
        metrics = status.get("metrics", {}) if isinstance(status, dict) else {}
        models = status.get("models", {}) if isinstance(status, dict) else {}
        fallback_models = status.get("fallback_models", {}) if isinstance(status, dict) else {}

        embed = discord.Embed(
            title="🧠 Stato AI",
            description=f"Servizio: **{status.get('state') or 'unknown'}**",
            color=discord.Color.blurple(),
        )
        if isinstance(models, dict) and models:
            primary_text = "\n".join(f"• {task} → {model}" for task, model in sorted(models.items()))
            embed.add_field(name="Primari", value=_truncate_embed_text(primary_text), inline=False)
        if isinstance(fallback_models, dict) and fallback_models:
            fallback_text = "\n".join(f"• {task} → {model}" for task, model in sorted(fallback_models.items()))
            embed.add_field(name="Fallback", value=_truncate_embed_text(fallback_text), inline=False)

        last_usage = (
            f"• task: {metrics.get('last_used_task') or '(n/d)'}\n"
            f"• modello: {metrics.get('last_used_model') or '(n/d)'}"
        )
        embed.add_field(name="Ultimo uso", value=_truncate_embed_text(last_usage), inline=False)

        last_test_state = metrics.get("last_test_ok")
        if last_test_state is None:
            test_outcome = "(n/d)"
        else:
            test_outcome = "ok" if last_test_state else "ko"
        last_test = (
            f"• task: {metrics.get('last_test_task') or '(n/d)'}\n"
            f"• modello: {metrics.get('last_test_model') or '(n/d)'}\n"
            f"• esito: {test_outcome}"
        )
        if metrics.get("last_test_error"):
            last_test += f"\n• errore: {_truncate_embed_text(str(metrics.get('last_test_error')), limit=220)}"
        embed.add_field(name="Ultimo test", value=_truncate_embed_text(last_test), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai_group.command(name="test", description="Esegue un test sul task AI configurato")
    @app_commands.describe(task="Task AI", prompt="Prompt di test", web="Abilita web search")
    @app_commands.choices(
        task=ai_task_choices,
        web=[app_commands.Choice(name="off", value="off"), app_commands.Choice(name="on", value="on")],
    )
    async def ai_test_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str],
        prompt: str,
        web: app_commands.Choice[str] | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.ai", ctx):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        web_value = (web.value if web is not None else "off") == "on"
        result = await ctx.ai.run_test(task.value, prompt, use_web=web_value)

        embed = discord.Embed(title="AI test", color=discord.Color.green() if result.get("ok") else discord.Color.red())
        embed.add_field(name="Task", value=str(result.get("task") or task.value), inline=True)
        embed.add_field(name="Model", value=str(result.get("model") or "(n/d)"), inline=True)
        embed.add_field(name="Web", value="on" if web_value else "off", inline=True)
        embed.add_field(name="Esito", value="ok" if result.get("ok") else "ko", inline=True)
        embed.add_field(name="Output", value=_truncate_embed_text(result.get("output"), limit=900), inline=False)
        if result.get("error"):
            embed.add_field(name="Errore", value=_truncate_embed_text(str(result.get("error")), limit=900), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    footer_group = app_commands.Group(name="footer", description="Gestione footer")
    bm_group.add_command(footer_group)

    @footer_group.command(name="set", description="Configura footer globali e per servizio")
    @app_commands.describe(
        version="Versione branding footer",
        frase_globale="Frase finale globale",
        servizio="Nome servizio per frase specifica",
        frase_servizio="Frase finale specifica servizio (vuota = reset)",
    )
    async def footer_set_command(
        interaction: discord.Interaction,
        version: str | None = None,
        frase_globale: str | None = None,
        servizio: str | None = None,
        frase_servizio: str | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.footer", ctx):
            return
        if ctx.footer is None:
            await interaction.response.send_message("Footer service non disponibile.", ephemeral=True)
            return

        v = _clean_opt(version)
        fg = _clean_opt(frase_globale)
        srv = _clean_opt(servizio)
        fs = _clean_opt(frase_servizio)

        if version is not None:
            await ctx.footer.set_version(v)
        if frase_globale is not None:
            await ctx.footer.set_global_phrase(fg)
        if servizio is not None:
            if srv is None:
                await interaction.response.send_message("Servizio non valido.", ephemeral=True)
                return
            await ctx.footer.set_service_phrase(srv, fs)

        if all(param is None for param in (version, frase_globale, servizio, frase_servizio)):
            current_version = await ctx.footer.get_version()
            current_global = await ctx.footer.get_global_phrase()
            phrases = await ctx.footer.get_service_phrases()
            lines = [
                f"Versione: {_format_value(current_version)}",
                f"Frase globale: {_format_value(current_global)}",
                "Frasi per servizio:",
            ]
            if phrases:
                lines.extend([f"- {name}: {text}" for name, text in phrases.items()])
            else:
                lines.append("- (nessuna)")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            return

        await interaction.response.send_message("Configurazione footer aggiornata.", ephemeral=True)

    @footer_group.command(name="status", description="Mostra footer renderizzato per tutti i servizi")
    async def footer_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "bm.footer_status", ctx):
            return
        if ctx.footer is None:
            await interaction.response.send_message("Footer service non disponibile.", ephemeral=True)
            return

        service_phrases = await ctx.footer.get_service_phrases()
        global_phrase = await ctx.footer.get_global_phrase()
        known_services = await ctx.footer.get_known_services()
        service_sources = await ctx.footer.get_known_service_sources()
        all_variants = await ctx.footer.get_all_service_footer_variants()
        profile_map = await ctx.footer.get_service_footer_profiles()

        if not known_services:
            await interaction.response.send_message("Nessun servizio footer noto.", ephemeral=True)
            return

        services = sorted(set(known_services), key=lambda name: (_service_section(name), name))
        sections: dict[str, list[str]] = {
            "Servizi standard": [],
            "Campagne editoriali": [],
            "Campagne prompt": [],
            "Campagne timer": [],
        }
        minimal_services: list[str] = []

        for service_name in services:
            if not _is_persistable_service_name(service_name):
                continue
            variants = all_variants.get(service_name, {})
            if not variants:
                profile = profile_map.get(service_name)
                if profile is None:
                    profile = await _infer_service_profile(service_name, ctx)
                footer_text, _ = await ctx.footer.render_footer(
                    service_name=service_name,
                    contributors=profile.contributors,
                    used_local_processing=profile.used_local_processing,
                )
                phrase = service_phrases.get(service_name) or global_phrase or "(nessuna)"
                origins = sorted(set(service_sources.get(service_name, [])) | set(profile.origins or set()))
                minimal_services.append(
                    f"**{service_name}**\n"
                    f"label: {_human_service_name(service_name)}\n"
                    f"alias tecnico: `{service_name}`\n"
                    f"→ {footer_text}\n"
                    f"frase: {phrase}\n"
                    f"origine: {','.join(origins) if origins else '(n/d)'}"
                )
                continue

            variant_blocks: list[str] = []
            for variant in sorted(variants.values(), key=lambda item: item.variant_key):
                phrase = service_phrases.get(service_name) or global_phrase or "(nessuna)"
                variant_blocks.append(_format_variant_block(service_name, variant, phrase))

            service_block = f"{_format_service_header(service_name)}\n\n" + "\n\n".join(variant_blocks)
            section_idx = _service_section(service_name)
            if section_idx == 1:
                sections["Campagne editoriali"].append(service_block)
            elif section_idx == 2:
                sections["Campagne prompt"].append(service_block)
            elif section_idx == 3:
                sections["Campagne timer"].append(service_block)
            else:
                sections["Servizi standard"].append(service_block)

        lines: list[str] = []
        for title in ["Servizi standard", "Campagne editoriali", "Campagne prompt", "Campagne timer"]:
            blocks = sections[title]
            if blocks:
                lines.append(f"__{title}__\n" + "\n\n".join(blocks))
        if minimal_services:
            lines.append("__Servizi senza footer personalizzato__\n" + "\n\n".join(minimal_services))

        chunks = _chunk_status_blocks(lines, max_len=1900)
        if not chunks:
            await interaction.response.send_message("Nessun dato footer disponibile.", ephemeral=True)
            return

        await interaction.response.send_message(chunks[0], ephemeral=True)
        for extra in chunks[1:]:
            await interaction.followup.send(extra, ephemeral=True)
