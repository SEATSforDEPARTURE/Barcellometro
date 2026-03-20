from __future__ import annotations

from collections.abc import Iterable

import discord

from app.shared.discord.command_embeds import send_legacy_standard_response
from app.plugins.commands_modular.ctx import CommandContext


def canonical_permission_key(command_name: str) -> str:
    # Legacy `bm` keys are normalized to the canonical `admin` namespace.
    normalized = str(command_name or "").strip().lower()
    if normalized == "bm":
        return "admin"
    if normalized.startswith("bm."):
        return f"admin.{normalized[3:]}"
    return normalized


def legacy_permission_candidates(command_name: str) -> list[str]:
    # Emit only backward-compatibility aliases; callers should persist/use `admin.*`.
    canonical = canonical_permission_key(command_name)
    if canonical == "admin":
        return ["bm"]
    if canonical.startswith("admin."):
        return [f"bm.{canonical[6:]}"]
    return []


async def check_permission(
    interaction: discord.Interaction,
    command_name: str,
    ctx: CommandContext,
    *,
    legacy_aliases: Iterable[str] = (),
) -> bool:
    guild = interaction.guild
    is_admin = bool(guild and interaction.user.guild_permissions.administrator)
    role_ids = [role.id for role in getattr(interaction.user, "roles", [])]
    canonical_name = canonical_permission_key(command_name)
    command_candidates = list(
        dict.fromkeys(
            [
                canonical_name,
                *legacy_permission_candidates(canonical_name),
                *[str(alias).strip().lower() for alias in legacy_aliases if str(alias).strip()],
            ]
        )
    )
    result = None
    for candidate in command_candidates:
        result = await ctx.guard.check_command(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            role_ids=role_ids,
            command=candidate,
            is_admin=is_admin,
        )
        if result.allowed:
            return True
        if result.reason != "Solo admin o policy configurata.":
            break

    assert result is not None
    message = result.reason
    if result.remaining is not None:
        message += f" Utilizzi rimanenti: {result.remaining}."
    if result.cooldown_remaining is not None:
        message += f" Cooldown: {result.cooldown_remaining}s."
    ephemeral = interaction.guild_id is not None
    await send_legacy_standard_response(
        interaction,
        top_level="admin",
        path_parts=["warning"],
        entries=[("Reason", message)],
        tone="warning",
        service_name="status",
        ephemeral=ephemeral,
    )
    return False
