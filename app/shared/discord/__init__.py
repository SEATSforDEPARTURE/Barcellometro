"""Shared Discord/UI infrastructure helpers."""

from .command_embeds import (
    CommandEmbedSection,
    CommandKind,
    build_command_embed,
    build_command_embeds,
    send_command_embed,
    send_command_embeds,
    send_standard_response,
)
from .component_notices import send_standard_component_notice
from .delivery import safe_followup_send, send_dm_or_followup
from .embed_limits import (
    MAX_EMBED_CHARS,
    RETRY_MAX_EMBED_CHARS,
    _clone_embed_shell,
    _ensure_embed_limits,
    _estimate_embed_size,
    _split_field_chunks,
    estimate_embeds_total_size,
    normalize_embeds_for_discord,
)
from .footer_pipeline import finalize_embed, finalize_embeds, install_footer_auto_finalize
from .report_embeds import apply_standard_report_style, build_report_cover_embed, send_report_dm_chunks

__all__ = [
    "CommandEmbedSection",
    "CommandKind",
    "MAX_EMBED_CHARS",
    "RETRY_MAX_EMBED_CHARS",
    "_clone_embed_shell",
    "_ensure_embed_limits",
    "_estimate_embed_size",
    "_split_field_chunks",
    "apply_standard_report_style",
    "build_command_embed",
    "build_command_embeds",
    "build_report_cover_embed",
    "estimate_embeds_total_size",
    "finalize_embed",
    "finalize_embeds",
    "install_footer_auto_finalize",
    "normalize_embeds_for_discord",
    "safe_followup_send",
    "send_command_embed",
    "send_command_embeds",
    "send_dm_or_followup",
    "send_report_dm_chunks",
    "send_standard_component_notice",
    "send_standard_response",
]
