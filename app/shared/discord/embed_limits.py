from __future__ import annotations

import discord

from app.services.footer import copy_footer_meta

MAX_EMBED_CHARS: int = 5800
RETRY_MAX_EMBED_CHARS: int = 5200


def _split_field_chunks(value: str, max_len: int = 1024) -> list[str]:
    if len(value) <= max_len:
        return [value]

    def split_plain(text: str, limit: int) -> list[str]:
        lines = text.splitlines() or [text]
        chunks: list[str] = []
        current = ""
        for line in lines:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
                current = ""
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            current = line
        if current:
            chunks.append(current)
        return chunks

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
        inner_chunks = split_plain(inner, inner_limit)
        return [f"{prefix}{chunk}{suffix}" for chunk in inner_chunks]
    return split_plain(value, max_len)


def _clone_embed_shell(source: discord.Embed, *, title: str | None = None) -> discord.Embed:
    new_embed = discord.Embed(
        title=title if title is not None else source.title,
        description=source.description,
        color=source.color,
    )
    if source.author:
        new_embed.set_author(name=source.author.name or "")
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
        output.extend(_split_embed_fields(embed, max_chars=max_chars))
    return output


def normalize_embeds_for_discord(
    embeds: list[discord.Embed],
    *,
    max_chars: int | None = None,
) -> list[discord.Embed]:
    if max_chars is None:
        max_chars = MAX_EMBED_CHARS
    normalized = _ensure_embed_limits(embeds, max_chars=max_chars)
    if any(_estimate_embed_size(embed) >= 6000 for embed in normalized):
        normalized = _ensure_embed_limits(normalized, max_chars=min(max_chars, 5600))
    return normalized
