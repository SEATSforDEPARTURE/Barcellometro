from __future__ import annotations

import logging
import re

import discord

from app.services.footer import copy_footer_meta

logger = logging.getLogger(__name__)

DISCORD_MAX_EMBED_TOTAL_CHARS: int = 6000
DISCORD_MAX_EMBED_TITLE: int = 256
DISCORD_MAX_EMBED_DESCRIPTION: int = 4096
DISCORD_MAX_FIELD_NAME: int = 256
DISCORD_MAX_FIELD_VALUE: int = 1024
DISCORD_MAX_FIELDS: int = 25
DISCORD_MAX_FOOTER_TEXT: int = 2048
DISCORD_MAX_AUTHOR_NAME: int = 256
DISCORD_MAX_EMBEDS_PER_MESSAGE: int = 10
MAX_EMBED_CHARS: int = 5600
RETRY_MAX_EMBED_CHARS: int = 5200
_MASKED_LINK_TOKEN_PATTERN = r"\*\*\[[^\]]+\]\([^)]+\)\*\*|\[[^\]]+\]\([^)]+\)"
_MASKED_LINK_RE = re.compile(rf"(?:{_MASKED_LINK_TOKEN_PATTERN})")
_SUMMARY_TIME_LABEL_PATTERN = r"(?:\d{2}/\d{2}\s+)?(?:\d{2}:\d{2}|--:--)"
_SUMMARY_TIME_TOKEN_PATTERN = rf"(?:{_MASKED_LINK_TOKEN_PATTERN}|\*\*{_SUMMARY_TIME_LABEL_PATTERN}\*\*|{_SUMMARY_TIME_LABEL_PATTERN})"
_SUMMARY_LINK_PREFIX_RE = re.compile(
    rf"^(?P<prefix>(?:•\s+)?(?:{_SUMMARY_TIME_TOKEN_PATTERN})(?:\s+📞)?(?:\s+\S+\s+\*\*[^*\n]+\*\*)?\s+—\s+)(?P<tail>.*)$"
)


def extract_protected_masked_link_prefix(line: str) -> tuple[str, str] | None:
    match = _MASKED_LINK_RE.search(line)
    if not match:
        return None
    prefix = line[: match.end()]
    tail = line[match.end() :]
    return prefix, tail


def extract_protected_summary_prefix(line: str) -> tuple[str, str] | None:
    match = _SUMMARY_LINK_PREFIX_RE.match(str(line or ""))
    if not match:
        return None
    return match.group("prefix"), match.group("tail")


def _truncate_text(text: str | None, limit: int) -> str:
    if text is None or limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    return f"{text[: max(0, limit - 1)]}…"


def truncate_line_preserve_links(line: str, line_limit: int) -> str:
    if len(line) <= line_limit:
        return line
    if line_limit <= 0:
        return ""
    protected_summary = extract_protected_summary_prefix(line)
    if protected_summary:
        prefix, tail = protected_summary
        if not tail:
            return prefix
        tail_budget = line_limit - len(prefix)
        if tail_budget <= 0:
            return f"{prefix}…"
        return prefix + _truncate_text(tail, tail_budget)
    protected_link = extract_protected_masked_link_prefix(line)
    if protected_link:
        prefix, suffix = protected_link
        if len(prefix) >= line_limit:
            return prefix
        return prefix + _truncate_text(suffix, line_limit - len(prefix))
    return _truncate_text(line, line_limit)


def count_summary_clickable_timestamps_in_values(values: list[str]) -> int:
    total = 0
    for value in values:
        for line in str(value or "").splitlines():
            protected = extract_protected_summary_prefix(line)
            if not protected:
                continue
            prefix, _ = protected
            if _MASKED_LINK_RE.search(prefix):
                total += 1
    return total


def log_summary_clickable_timestamp_loss(
    *,
    expected_values: list[str],
    actual_values: list[str],
    req_id: str,
    field_name: str,
) -> None:
    expected = count_summary_clickable_timestamps_in_values(expected_values)
    if expected <= 0:
        return
    actual = count_summary_clickable_timestamps_in_values(actual_values)
    if actual >= expected:
        return
    logger.warning(
        "summary_clickable_timestamp_loss req_id=%s field_name=%s expected=%s actual=%s",
        req_id,
        field_name,
        expected,
        actual,
    )


def _split_long_token(token: str, limit: int) -> list[str]:
    if limit <= 0:
        return [token]
    if len(token) <= limit or _MASKED_LINK_RE.fullmatch(token):
        return [token]
    return [token[idx : idx + limit] for idx in range(0, len(token), limit)]


def _split_markdown_text_chunks(
    text: str,
    *,
    limit: int,
    first_prefix: str = "",
    continuation_prefix: str = "",
) -> list[str]:
    budget = max(1, limit - len(first_prefix))
    current = first_prefix
    chunks: list[str] = []
    tokens = re.findall(rf"{_MASKED_LINK_TOKEN_PATTERN}|\s+|\S+", text)
    for token in tokens:
        remaining_tokens = _split_long_token(token, budget if current == first_prefix else max(1, limit - len(continuation_prefix)))
        for piece in remaining_tokens:
            prefix = first_prefix if current == first_prefix else continuation_prefix
            piece_budget = max(1, limit - len(prefix))
            if current == prefix and piece.isspace():
                continue
            candidate = f"{current}{piece}"
            if len(candidate) <= limit:
                current = candidate
                continue
            if current.strip():
                chunks.append(current.rstrip())
            current = prefix
            if piece.isspace():
                continue
            if len(piece) > piece_budget and not _MASKED_LINK_RE.fullmatch(piece):
                for extra_piece in _split_long_token(piece, piece_budget):
                    if len(f"{current}{extra_piece}") > limit and current.strip():
                        chunks.append(current.rstrip())
                        current = continuation_prefix
                    current = f"{current}{extra_piece}"
                    if len(current) == limit:
                        chunks.append(current.rstrip())
                        current = continuation_prefix
            else:
                current = f"{current}{piece}"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or [first_prefix.rstrip() or text[:limit]]


def _split_markdown_aware_line(line: str, limit: int, *, continuation_prefix: str = "↳ ") -> list[str]:
    if len(line) <= limit:
        return [line]
    protected_summary = extract_protected_summary_prefix(line)
    if protected_summary:
        prefix, tail = protected_summary
        if len(prefix) >= limit:
            return [f"{prefix}…" if tail else prefix]
        return _split_markdown_text_chunks(
            tail,
            limit=limit,
            first_prefix=prefix,
            continuation_prefix=continuation_prefix,
        )
    return _split_markdown_text_chunks(line, limit=limit, continuation_prefix=continuation_prefix)


def split_markdown_lines_into_field_values(
    lines: list[str],
    limit: int = 1024,
    *,
    continuation_prefix: str = "↳ ",
) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for raw_line in lines:
        line = str(raw_line or "")
        if not line:
            continue
        for expanded_line in _split_markdown_aware_line(line, limit, continuation_prefix=continuation_prefix):
            line_len = len(expanded_line) + (1 if current else 0)
            if current and current_len + line_len > limit:
                chunks.append("\n".join(current))
                current = [expanded_line]
                current_len = len(expanded_line)
                continue
            current.append(expanded_line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _split_field_chunks(value: str, max_len: int = 1024) -> list[str]:
    if len(value) <= max_len:
        return [value]

    stripped = value.strip()
    if stripped.startswith("```"):
        inner = stripped[3:]
        if inner.startswith("\n"):
            inner = inner[1:]
        if inner.endswith("```"):
            inner = inner[:-3]
        if inner.endswith("\n"):
            inner = inner[:-1]
        prefix = "```\n"
        suffix = "\n```"
        inner_limit = max_len - len(prefix) - len(suffix)
        inner_chunks = split_markdown_lines_into_field_values(inner.splitlines() or [inner], inner_limit)
        return [f"{prefix}{chunk}{suffix}" for chunk in inner_chunks]
    return split_markdown_lines_into_field_values(value.splitlines() or [value], max_len)


def _clone_embed_shell(source: discord.Embed, *, title: str | None = None) -> discord.Embed:
    new_embed = discord.Embed(
        title=title if title is not None else source.title,
        description=source.description,
        url=source.url,
        color=source.color,
    )
    if source.author:
        new_embed.set_author(
            name=source.author.name or "",
            url=source.author.url,
            icon_url=source.author.icon_url,
        )
    if source.thumbnail and source.thumbnail.url:
        new_embed.set_thumbnail(url=source.thumbnail.url)
    if source.image and source.image.url:
        new_embed.set_image(url=source.image.url)
    copy_footer_meta(source, new_embed)
    return new_embed


def _build_embed_shell(
    source: discord.Embed,
    *,
    title: str | None,
    description: str | None = None,
    preserve_rendered_footer: bool = False,
) -> discord.Embed:
    new_embed = discord.Embed(
        title=title,
        description=description,
        url=source.url,
        color=source.color,
    )
    if source.author and source.author.name:
        new_embed.set_author(
            name=_truncate_text(source.author.name, DISCORD_MAX_AUTHOR_NAME),
            url=source.author.url,
            icon_url=source.author.icon_url,
        )
    if source.thumbnail and source.thumbnail.url:
        new_embed.set_thumbnail(url=source.thumbnail.url)
    if source.image and source.image.url:
        new_embed.set_image(url=source.image.url)
    if preserve_rendered_footer and source.footer and source.footer.text:
        new_embed.set_footer(
            text=_truncate_text(source.footer.text, DISCORD_MAX_FOOTER_TEXT),
            icon_url=source.footer.icon_url,
        )
    copy_footer_meta(source, new_embed)
    return new_embed


def _estimate_embed_size(embed: discord.Embed) -> int:
    total = len(embed.title or "") + len(embed.description or "")
    for field in embed.fields:
        total += len(field.name or "") + len(field.value or "")
    total += len(embed.footer.text or "") if embed.footer else 0
    total += len(embed.author.name or "") if embed.author else 0
    return total


def estimate_embeds_total_size(embeds: list[discord.Embed]) -> int:
    return sum(_estimate_embed_size(embed) for embed in embeds)


def is_valid_embed(
    embed: discord.Embed,
    *,
    max_chars: int | None = None,
) -> bool:
    if max_chars is None:
        max_chars = MAX_EMBED_CHARS
    if len(embed.title or "") > DISCORD_MAX_EMBED_TITLE:
        return False
    if len(embed.description or "") > DISCORD_MAX_EMBED_DESCRIPTION:
        return False
    if len(embed.fields) > DISCORD_MAX_FIELDS:
        return False
    if len(embed.footer.text or "") > DISCORD_MAX_FOOTER_TEXT:
        return False
    if len(embed.author.name or "") > DISCORD_MAX_AUTHOR_NAME:
        return False
    for field in embed.fields:
        if len(field.name or "") > DISCORD_MAX_FIELD_NAME:
            return False
        if len(field.value or "") > DISCORD_MAX_FIELD_VALUE:
            return False
    return _estimate_embed_size(embed) <= max_chars


def _split_description_chunks(description: str | None, *, limit: int = DISCORD_MAX_EMBED_DESCRIPTION) -> list[str]:
    text = str(description or "").strip()
    if not text:
        return []
    return split_markdown_lines_into_field_values(
        text.splitlines() or [text],
        limit=limit,
        continuation_prefix="",
    )


def _truncate_field_name(name: str | None, *, continuation: bool = False) -> str:
    suffix = " (cont.)" if continuation else ""
    budget = DISCORD_MAX_FIELD_NAME - len(suffix)
    truncated = _truncate_text(str(name or ""), budget) or "…"
    return f"{truncated}{suffix}"


def _sanitize_textual_limits(embed: discord.Embed) -> discord.Embed:
    clone = _build_embed_shell(
        embed,
        title=_truncate_text(embed.title, DISCORD_MAX_EMBED_TITLE) or None,
        description=_truncate_text(embed.description, DISCORD_MAX_EMBED_DESCRIPTION) or None,
        preserve_rendered_footer=True,
    )
    for field in embed.fields[:DISCORD_MAX_FIELDS]:
        clone.add_field(
            name=_truncate_text(field.name, DISCORD_MAX_FIELD_NAME) or "…",
            value=_truncate_text(field.value, DISCORD_MAX_FIELD_VALUE) or "…",
            inline=field.inline,
        )
    return clone


def _normalize_single_embed(
    embed: discord.Embed,
    *,
    max_chars: int,
    preserve_rendered_footer: bool = False,
) -> list[discord.Embed]:
    safe_title = _truncate_text(embed.title, DISCORD_MAX_EMBED_TITLE) or None
    description_chunks = _split_description_chunks(embed.description, limit=DISCORD_MAX_EMBED_DESCRIPTION)
    shell = _build_embed_shell(embed, title=safe_title, description=None, preserve_rendered_footer=preserve_rendered_footer)
    shell_size = _estimate_embed_size(shell)
    description_budget = max(1, min(DISCORD_MAX_EMBED_DESCRIPTION, max_chars - shell_size))
    if description_budget < DISCORD_MAX_EMBED_DESCRIPTION and embed.description:
        description_chunks = _split_description_chunks(embed.description, limit=description_budget)

    output: list[discord.Embed] = []
    current = _build_embed_shell(embed, title=safe_title, description=None, preserve_rendered_footer=preserve_rendered_footer)
    if len(description_chunks) > 1:
        for chunk in description_chunks[:-1]:
            output.append(
                _build_embed_shell(
                    embed,
                    title=safe_title,
                    description=chunk,
                    preserve_rendered_footer=preserve_rendered_footer,
                )
            )
        current.description = description_chunks[-1]
    elif description_chunks:
        current.description = description_chunks[0]

    for field in embed.fields:
        field_chunks = _split_field_chunks(field.value or "", DISCORD_MAX_FIELD_VALUE)
        for idx, chunk in enumerate(field_chunks):
            field_name = _truncate_field_name(field.name, continuation=idx > 0)
            candidate = discord.Embed.from_dict(current.to_dict())
            copy_footer_meta(current, candidate)
            candidate.add_field(name=field_name, value=_truncate_text(chunk, DISCORD_MAX_FIELD_VALUE), inline=field.inline)
            if len(candidate.fields) > DISCORD_MAX_FIELDS or _estimate_embed_size(candidate) > max_chars:
                if current.description or current.fields or not output:
                    output.append(current)
                current = _build_embed_shell(embed, title=safe_title, description=None, preserve_rendered_footer=preserve_rendered_footer)
                current.add_field(name=field_name, value=_truncate_text(chunk, DISCORD_MAX_FIELD_VALUE), inline=field.inline)
            else:
                current = candidate

    if current.description or current.fields or not output:
        output.append(current)
    return [_sanitize_textual_limits(item) if not is_valid_embed(item, max_chars=max_chars) else item for item in output]


def _split_embed_fields(embed: discord.Embed, *, max_chars: int) -> list[discord.Embed]:
    if _estimate_embed_size(embed) < max_chars and len(embed.fields) <= 25:
        return [embed]
    output: list[discord.Embed] = []
    current = _clone_embed_shell(embed)
    for field in embed.fields:
        chunks = _split_field_chunks(field.value or "", 1024)
        for idx, chunk in enumerate(chunks):
            field_name = field.name if idx == 0 else f"{field.name} (cont.)"
            candidate = _clone_embed_shell(current)
            for existing in current.fields:
                candidate.add_field(name=existing.name, value=existing.value, inline=existing.inline)
            candidate.add_field(name=field_name, value=chunk, inline=False)
            if _estimate_embed_size(candidate) >= max_chars or len(candidate.fields) > 25:
                if current.fields:
                    output.append(current)
                    current = _clone_embed_shell(embed)
                current.add_field(name=field_name, value=chunk, inline=False)
            else:
                current = candidate
    if current.fields:
        output.append(current)
    return output


def _ensure_embed_limits(embeds: list[discord.Embed], *, max_chars: int) -> list[discord.Embed]:
    output: list[discord.Embed] = []
    for embed in embeds:
        preserve_rendered_footer = bool(getattr(embed.footer, "text", None))
        normalized = _normalize_single_embed(
            embed,
            max_chars=max_chars,
            preserve_rendered_footer=preserve_rendered_footer,
        )
        if any(not is_valid_embed(item, max_chars=max_chars) for item in normalized):
            output.extend(_split_embed_fields(embed, max_chars=max_chars))
            continue
        output.extend(normalized)
    return output


def normalize_embeds_for_discord(
    embeds: list[discord.Embed],
    *,
    max_chars: int | None = None,
) -> list[discord.Embed]:
    if max_chars is None:
        max_chars = MAX_EMBED_CHARS
    normalized = _ensure_embed_limits(embeds, max_chars=max_chars)
    if any(_estimate_embed_size(embed) >= DISCORD_MAX_EMBED_TOTAL_CHARS for embed in normalized):
        normalized = _ensure_embed_limits(normalized, max_chars=min(max_chars, 5600))
    return normalized


def chunk_embeds_for_message_batches(
    embeds: list[discord.Embed],
    *,
    max_embeds: int = DISCORD_MAX_EMBEDS_PER_MESSAGE,
    max_total_chars: int = MAX_EMBED_CHARS,
) -> list[list[discord.Embed]]:
    batches: list[list[discord.Embed]] = []
    current: list[discord.Embed] = []
    current_total = 0
    for embed in embeds:
        embed_size = _estimate_embed_size(embed)
        should_split = bool(current) and (
            len(current) >= max_embeds or current_total + embed_size > max_total_chars
        )
        if should_split:
            batches.append(current)
            current = []
            current_total = 0
        current.append(embed)
        current_total += embed_size
    if current:
        batches.append(current)
    return batches
