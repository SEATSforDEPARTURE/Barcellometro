from __future__ import annotations

import discord
from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext
from app.plugins.commands_modular.permissions import check_permission


def register_roles(role_group: app_commands.Group, ctx: CommandContext) -> None:
    @role_group.command(name="set-role", description="Limiti ruolo comando")
    @app_commands.describe(role="Ruolo", command="Nome comando", usage_limit="Limite usi (vuoto=∞)", cooldown_seconds="Cooldown sec")
    async def role_set_command(
        interaction: discord.Interaction,
        role: discord.Role,
        command: str,
        usage_limit: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.role.set_role", ctx):
            return
        if usage_limit is not None and usage_limit <= 0:
            await interaction.response.send_message("Specifica un limite utilizzi valido.", ephemeral=True)
            return
        if cooldown_seconds is not None and cooldown_seconds < 0:
            await interaction.response.send_message("Specifica un cooldown valido.", ephemeral=True)
            return
        await ctx.database.upsert_role_policy(
            guild_id=str(interaction.guild_id),
            role_id=str(role.id),
            command=command,
            usage_limit=usage_limit,
            cooldown_seconds=cooldown_seconds,
        )
        await interaction.response.send_message("Policy ruolo aggiornata.", ephemeral=True)

    @role_group.command(name="set-user", description="Limiti utente comando")
    @app_commands.describe(user="Utente", command="Nome comando", usage_limit="Limite usi (vuoto=∞)", cooldown_seconds="Cooldown sec")
    async def user_set_command(
        interaction: discord.Interaction,
        user: discord.User,
        command: str,
        usage_limit: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "bm.role.set_user", ctx):
            return
        if usage_limit is not None and usage_limit <= 0:
            await interaction.response.send_message("Specifica un limite utilizzi valido.", ephemeral=True)
            return
        if cooldown_seconds is not None and cooldown_seconds < 0:
            await interaction.response.send_message("Specifica un cooldown valido.", ephemeral=True)
            return
        await ctx.database.upsert_user_policy(
            guild_id=str(interaction.guild_id),
            user_id=str(user.id),
            command=command,
            usage_limit=usage_limit,
            cooldown_seconds=cooldown_seconds,
        )
        await interaction.response.send_message("Policy utente aggiornata.", ephemeral=True)

    @role_group.command(name="clear-role", description="Rimuove la policy di un ruolo")
    @app_commands.describe(role="Ruolo", command="Nome comando")
    async def role_clear_command(
        interaction: discord.Interaction,
        role: discord.Role,
        command: str,
    ) -> None:
        if not await check_permission(interaction, "bm.role.clear_role", ctx):
            return
        await ctx.database.delete_role_policy(
            guild_id=str(interaction.guild_id),
            role_id=str(role.id),
            command=command,
        )
        await interaction.response.send_message("Policy ruolo rimossa.", ephemeral=True)

    @role_group.command(name="clear-user", description="Rimuove la policy di un utente")
    @app_commands.describe(user="Utente", command="Nome comando")
    async def user_clear_command(
        interaction: discord.Interaction,
        user: discord.User,
        command: str,
    ) -> None:
        if not await check_permission(interaction, "bm.role.clear_user", ctx):
            return
        await ctx.database.delete_user_policy(
            guild_id=str(interaction.guild_id),
            user_id=str(user.id),
            command=command,
        )
        await interaction.response.send_message("Policy utente rimossa.", ephemeral=True)

    @role_group.command(name="show-role", description="Mostra le policy di un ruolo")
    @app_commands.describe(role="Ruolo")
    async def role_show_command(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await check_permission(interaction, "bm.role.show_role", ctx):
            return
        rows = await ctx.database.fetch_role_policies(str(interaction.guild_id), str(role.id))
        if not rows:
            await interaction.response.send_message("Nessuna policy per questo ruolo.", ephemeral=True)
            return
        lines = []
        for row in rows:
            limit = row["usage_limit"] if row["usage_limit"] is not None else "∞"
            cooldown = row["cooldown_seconds"] if row["cooldown_seconds"] is not None else "∞"
            lines.append(f"{row['command']}: limit={limit} cooldown={cooldown}")
        await interaction.response.send_message("\\n".join(lines), ephemeral=True)

    @role_group.command(name="show-user", description="Mostra le policy di un utente")
    @app_commands.describe(user="Utente")
    async def user_show_command(interaction: discord.Interaction, user: discord.User) -> None:
        if not await check_permission(interaction, "bm.role.show_user", ctx):
            return
        rows = await ctx.database.fetch_user_policies(str(interaction.guild_id), str(user.id))
        if not rows:
            await interaction.response.send_message("Nessuna policy per questo utente.", ephemeral=True)
            return
        lines = []
        for row in rows:
            limit = row["usage_limit"] if row["usage_limit"] is not None else "∞"
            cooldown = row["cooldown_seconds"] if row["cooldown_seconds"] is not None else "∞"
            lines.append(f"{row['command']}: limit={limit} cooldown={cooldown}")
        await interaction.response.send_message("\\n".join(lines), ephemeral=True)
