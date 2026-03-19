# TODO remove after import migration
from app.shared.discord.embed_limits import (
    MAX_EMBED_CHARS,
    RETRY_MAX_EMBED_CHARS,
    _clone_embed_shell,
    _ensure_embed_limits,
    _estimate_embed_size,
    _split_field_chunks,
    estimate_embeds_total_size,
    normalize_embeds_for_discord,
)
