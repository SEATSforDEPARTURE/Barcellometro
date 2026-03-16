from __future__ import annotations

from discord import app_commands

from app.plugins.commands_modular.ctx import CommandContext


def register_attivita_settings(attivita_group: app_commands.Group, ctx: CommandContext) -> None:
    _ = attivita_group
    _ = ctx
    # Namespace /attivita no longer exposes scheduler/configuration commands.
    return
