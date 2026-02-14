from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.services.message_scheduler import calculate_initial_next_run


def register_triggers(trigger_group: app_commands.Group, ctx: CommandContext) -> None:
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

    @trigger_group.command(name="status", description="Stato trigger nel canale corrente")
    async def trigger_status(interaction: discord.Interaction) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        data = await ctx.database.list_triggers(guild_id, channel_id)
        order = ["barcello", "frasi", "prompt", "qna"]
        lines = [f"- {k}: {'on' if data.get(k, False) else 'off'}" for k in order]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @trigger_group.command(name="barcello_on", description="Abilita trigger barcello")
    async def barcello_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "barcello", "on")

    @trigger_group.command(name="barcello_off", description="Disabilita trigger barcello")
    async def barcello_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "barcello", "off")

    @trigger_group.command(name="barcello_status", description="Stato trigger barcello")
    async def barcello_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "barcello", "status")

    @trigger_group.command(name="frasi_on", description="Abilita trigger frasi")
    async def frasi_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "frasi", "on")

    @trigger_group.command(name="frasi_off", description="Disabilita trigger frasi")
    async def frasi_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "frasi", "off")

    @trigger_group.command(name="frasi_status", description="Stato trigger frasi")
    async def frasi_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "frasi", "status")

    @trigger_group.command(name="frasi_add", description="Aggiungi frase trigger")
    @app_commands.describe(phrase="Frase", match_mode="EXACT|CONTAINS|REGEX", case_sensitive="Case sensitive")
    async def frasi_add(interaction: discord.Interaction, phrase: str, match_mode: str = "CONTAINS", case_sensitive: bool = False) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        await ctx.database.add_trigger_phrase(guild_id, channel_id, phrase, match_mode.upper(), case_sensitive)
        await interaction.response.send_message("Frase aggiunta.", ephemeral=True)

    @trigger_group.command(name="frasi_remove", description="Rimuovi frase trigger")
    async def frasi_remove(interaction: discord.Interaction, phrase: str) -> None:
        scope = await _require_channel(interaction)
        if scope is None:
            return
        guild_id, channel_id = scope
        await ctx.database.remove_trigger_phrase(guild_id, channel_id, phrase)
        await interaction.response.send_message("Frase rimossa.", ephemeral=True)

    @trigger_group.command(name="frasi_list", description="Lista frasi")
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

    @trigger_group.command(name="prompt_on", description="Abilita trigger prompt")
    async def prompt_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "prompt", "on")

    @trigger_group.command(name="prompt_off", description="Disabilita trigger prompt")
    async def prompt_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "prompt", "off")

    @trigger_group.command(name="prompt_status", description="Stato trigger prompt")
    async def prompt_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "prompt", "status")

    @trigger_group.command(name="prompt_create", description="Crea campagna AI_PROMPT")
    async def prompt_create(
        interaction: discord.Interaction,
        name: str,
        time_local: str,
        interval_minutes: int,
        prompt: str,
    ) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa in una guild.", ephemeral=True)
            return
        next_run = calculate_initial_next_run(datetime.now(timezone.utc), time_local, interval_minutes, ctx.timezone)
        campaign_id = await ctx.database.create_message_campaign(
            guild_id=str(interaction.guild_id),
            campaign_type="AI_PROMPT",
            name=name,
            text=prompt,
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

    @trigger_group.command(name="prompt_list", description="Lista campagne AI_PROMPT")
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
            "\n".join([f"ID {r['id']} {'on' if r['enabled'] else 'off'} {r['name'] or '-'}" for r in rows]),
            ephemeral=True,
        )

    @trigger_group.command(name="prompt_delete", description="Elimina campagna AI_PROMPT")
    async def prompt_delete(interaction: discord.Interaction, id: int) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message("Usa in una guild.", ephemeral=True)
            return
        await ctx.database.soft_delete_message_campaign(str(interaction.guild_id), id)
        await interaction.response.send_message("Campagna eliminata.", ephemeral=True)

    @trigger_group.command(name="qna_on", description="Abilita trigger qna")
    async def qna_on(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "qna", "on")

    @trigger_group.command(name="qna_off", description="Disabilita trigger qna")
    async def qna_off(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "qna", "off")

    @trigger_group.command(name="qna_status", description="Stato trigger qna")
    async def qna_status(interaction: discord.Interaction) -> None:
        await _set_toggle(interaction, "qna", "status")
