from __future__ import annotations

from app.plugins.commands_modular.ctx import CommandContext


async def set_setting(ctx: CommandContext, key: str, value: str) -> None:
    await ctx.database.set_setting(key, value)


async def reset_setting(ctx: CommandContext, key: str) -> None:
    await ctx.database.delete_setting(key)


async def get_setting(ctx: CommandContext, key: str, default: str) -> str:
    stored = await ctx.database.get_setting(key)
    return stored if stored is not None else default
