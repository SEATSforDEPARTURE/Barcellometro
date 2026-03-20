from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
import json
import re
from typing import Any, Literal

import discord

from app.plugins.commands_modular.time_windows import format_italian_ts, format_rolling_window_label, parse_italian_datetime
from app.services.footer import FooterService, attach_footer_meta, attach_minimal_footer

CommandKind = Literal["info", "success", "warning", "error"]
FooterMode = Literal["minimal", "meta", "none"]

DISPLAY_TOP_LEVEL_OVERRIDES: set[str] = {
    "frasi",
    "campagne",
    "qna",
    "insights",
    "moderazione",
    "inattivi",
    "privacy",
    "roles",
    "attivita",
    "aura",
    "riassunto",
    "resoconto",
    "resocontocanale",
    "resocontoserver",
    "domanda",
    "ask",
}

TOP_LEVEL_EMOJIS: dict[str, str] = {
    "admin": "🫛",
    "campagne": "📣",
    "frasi": "💬",
    "qna": "❓",
    "status": "📊",
    "ai": "🧠",
    "retention": "🗂️",
    "backfill": "♻️",
    "events": "📡",
    "triggers": "⚡",
    "audio_notes": "🎙️",
    "audionotes": "🎙️",
    "voice_ingest": "🎧",
    "privacy": "🔒",
    "roles": "👥",
    "settings": "⚙️",
    "attivita": "📈",
    "aura": "✨",
    "barcello": "❤️",
    "resoconto": "📓",
    "resocontocanale": "📓",
    "resocontoserver": "📓",
    "riassunto": "🗒️",
    "moderazione": "🛠️",
    "moderazione_utenti": "🛠️",
    "inattivi": "🛠️",
    "commandguard": "👥",
    "footer": "🧾",
    "ask": "❓",
    "domanda": "❓",
}

SECTION_EMOJIS: dict[str, str] = {
    "info": "🛠️",
    "status": "🛠️",
    "show": "🛠️",
    "config": "⚙️",
    "success": "✅",
    "result": "✅",
    "error": "❌",
    "warning": "⚠️",
    "metrics": "📊",
    "primary": "🧠",
    "fallback": "🛟",
    "last usage": "📊",
    "last run": "📊",
    "templates": "🧩",
    "channel": "📣",
    "details": "📋",
}

SECTION_FALLBACK_EMOJIS: dict[str, str] = {
    "info": "🛠️",
    "status": "📊",
    "show": "📋",
    "list": "📋",
    "config": "⚙️",
    "set": "🛠️",
    "reset": "🧩",
    "test": "🧪",
    "success": "📋",
    "result": "📋",
    "error": "🧩",
    "warning": "📋",
    "metrics": "📊",
    "templates": "🧩",
    "details": "📋",
    "configuration": "⚙️",
    "defaults": "🧩",
    "schedule": "📋",
    "limits": "📊",
}

_KIND_SECTION_FALLBACKS: dict[CommandKind, tuple[str, ...]] = {
    "info": ("🛠️", "📋", "📊", "🧩"),
    "success": ("📋", "🛠️", "📊", "🧩"),
    "warning": ("📋", "📊", "🛠️", "🧩"),
    "error": ("🧩", "📋", "📊", "🛠️"),
}

KIND_EMOJIS: dict[CommandKind, str] = {
    "info": "ℹ️",
    "success": "✅",
    "warning": "⚠️",
    "error": "❌",
}

KIND_COLORS: dict[CommandKind, int] = {
    "info": 0x3498DB,
    "success": 0x57F287,
    "warning": 0xFEE75C,
    "error": 0xED4245,
}


@dataclass(slots=True)
class CommandEmbedSection:
    title: str
    lines: list[tuple[str, Any]]
    emoji: str | None = None


@dataclass(slots=True)
class DisplayCommandContext:
    visual_top_level: str
    visual_title: str
    title_emoji: str
    visual_subtitle: str
    subtitle_emoji: str
    visual_subtitle_parts: tuple[str, ...]
    subtitle_parameter_parts: tuple[str, ...]


_MAX_DESCRIPTION = 3800
_MAX_SUBTITLE_ARG_LENGTH = 80
_RAW_OBJECT_HINTS = ("{", "}", "[", "]", "\n")
_MENTION_RE = re.compile(r"^<@!?(?P<user_id>\d+)>$")
_ROLE_MENTION_RE = re.compile(r"^<@&(?P<role_id>\d+)>$")
_CHANNEL_MENTION_RE = re.compile(r"^<#(?P<channel_id>\d+)>$")
_NARRATIVE_LABELS = {"detail", "dettaglio", "warning", "result", "results", "error", "info"}
_GENERIC_STATUS_TEXT = {
    "updated": "Updated.",
    "removed": "Removed.",
    "reset": "Reset.",
    "created": "Created.",
    "saved": "Saved.",
    "enabled": "Enabled.",
    "disabled": "Disabled.",
    "sent": "Sent.",
    "running": "Running.",
    "added": "Added.",
    "on": "Enabled.",
    "off": "Disabled.",
}
_USER_LABELS = {"user", "utente"}
_ROLE_LABELS = {"role"}
_CHANNEL_LABELS = {"channel"}
_IDENTITY_LABELS = {
    *_USER_LABELS,
    *_ROLE_LABELS,
    *_CHANNEL_LABELS,
    "tier",
    "quantita",
    "quantity",
    "unita",
    "unit",
    "periodo",
    "scope",
    "schedule_id",
    "id",
    "id_or_name",
    "template_name",
}
_FOOTER_SERVICE_FALLBACKS: dict[str, str] = {
    "ask": "qna",
    "domanda": "qna",
    "resocontocanale": "resoconto",
    "resocontoserver": "resoconto",
    "moderazione": "status",
    "roles": "status",
    "settings": "status",
    "permissions": "status",
    "commandguard": "status",
}


def _choice_or_value(value: object) -> object:
    choice_value = getattr(value, "value", None)
    return choice_value if choice_value is not None else value


def _coerce_temporal_quantity(value: object) -> int | None:
    raw = _choice_or_value(value)
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, float):
        coerced = int(raw)
        return coerced if coerced > 0 else None
    text = str(raw or "").strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def _coerce_temporal_unit(value: object) -> str | None:
    raw = _choice_or_value(value)
    normalized = str(raw or "").strip().lower()
    return normalized or None


def _format_range_subtitle(start_value: object, end_value: object) -> str | None:
    start_dt = parse_italian_datetime(str(_choice_or_value(start_value) or ""))
    end_dt = parse_italian_datetime(str(_choice_or_value(end_value) or ""))
    if start_dt is None or end_dt is None:
        return None
    start_label = format_italian_ts(start_dt.isoformat())
    end_label = format_italian_ts(end_dt.isoformat())
    return f"Dal {start_label} al {end_label}"


def _apply_temporal_subtitle_rules(
    subtitle_parts: list[str],
    raw_parameters: Sequence[object],
) -> tuple[list[str], set[int]]:
    if not subtitle_parts:
        return subtitle_parts, set()
    last_part = _normalize_command_token(subtitle_parts[-1])
    if last_part == "ultimi" and len(raw_parameters) >= 2:
        quantity = _coerce_temporal_quantity(raw_parameters[0])
        unit = _coerce_temporal_unit(raw_parameters[1])
        if quantity is not None and unit:
            rendered = format_rolling_window_label(quantity, unit, include_equivalence=False)
            return [*subtitle_parts[:-1], rendered], {0, 1}
    if last_part == "range" and len(raw_parameters) >= 2:
        rendered = _format_range_subtitle(raw_parameters[0], raw_parameters[1])
        if rendered:
            return [*subtitle_parts[:-1], rendered], {0, 1}
    return subtitle_parts, set()


def _clean_narrative_text(value: Any) -> str:
    text = stringify_value(value).strip()
    if not text:
        return "Nessun dettaglio disponibile."
    lowered = text.lower()
    if lowered in _GENERIC_STATUS_TEXT:
        return _GENERIC_STATUS_TEXT[lowered]
    return text


def _strip_duplicate_leading_emoji(text: str, *, emoji: str | None) -> str:
    cleaned = str(text or "").strip()
    target_emoji = str(emoji or "").strip()
    if not cleaned or not target_emoji:
        return cleaned
    pattern = rf"^(?P<prefix>•\s*)?{re.escape(target_emoji)}\s*[:\-–—]?\s*"
    return re.sub(pattern, lambda match: match.group("prefix") or "", cleaned, count=1).strip()


def _strip_duplicate_kind_emoji(text: str, *, kind: CommandKind) -> str:
    return _strip_duplicate_leading_emoji(text, emoji=KIND_EMOJIS[kind])


def _has_entity_argument(raw_parameters: Sequence[object], *, labels: set[str]) -> bool:
    for parameter in raw_parameters:
        if parameter is None:
            continue
        if labels is _USER_LABELS and (
            isinstance(parameter, (discord.Member, discord.User))
            or _discord_entity_display_name(parameter) is not None
        ):
            return True
        if labels is _ROLE_LABELS and isinstance(parameter, discord.Role):
            return True
        if labels is _CHANNEL_LABELS and isinstance(parameter, (discord.abc.GuildChannel, discord.Thread)):
            return True
    return False


def _should_skip_primary_line(
    label: str,
    value: Any,
    *,
    display_context: DisplayCommandContext,
    raw_subtitle_parameters: Sequence[object],
) -> bool:
    normalized_label = _normalize_command_token(label)
    if normalized_label not in _IDENTITY_LABELS:
        return False

    normalized_value = _normalize_relevant_parameter(value)
    if normalized_value and any(
        _normalize_command_token(part) == _normalize_command_token(normalized_value)
        for part in display_context.subtitle_parameter_parts
    ):
        return True

    if normalized_label in _USER_LABELS and _has_entity_argument(raw_subtitle_parameters, labels=_USER_LABELS):
        return True
    if normalized_label in _ROLE_LABELS and _has_entity_argument(raw_subtitle_parameters, labels=_ROLE_LABELS):
        return True
    if normalized_label in _CHANNEL_LABELS and _has_entity_argument(raw_subtitle_parameters, labels=_CHANNEL_LABELS):
        return True

    if normalized_label in {"tier", "quantita", "quantity", "unita", "unit", "periodo", "scope"} and display_context.subtitle_parameter_parts:
        return True
    return False


def _format_primary_bullet(
    label: str,
    value: Any,
    *,
    display_context: DisplayCommandContext,
    raw_subtitle_parameters: Sequence[object],
    kind: CommandKind,
    line_formatter: Callable[[str, Any], str],
) -> str | None:
    if _should_skip_primary_line(
        label,
        value,
        display_context=display_context,
        raw_subtitle_parameters=raw_subtitle_parameters,
    ):
        return None
    normalized_label = _normalize_command_token(label)
    if normalized_label in _NARRATIVE_LABELS:
        return _strip_duplicate_kind_emoji(f"• {_clean_narrative_text(value)}", kind=kind)
    return _strip_duplicate_kind_emoji(line_formatter(label, value), kind=kind)


def humanize_key(key: str) -> str:
    parts = str(key).replace(".", " ").replace("_", " ").replace("-", " ").split()
    if not parts:
        return "Value"
    human = " ".join(parts)
    for source, target in {
        "db": "DB",
        "id": "ID",
        "ids": "IDs",
        "ai": "AI",
        "qna": "QnA",
        "dm": "DM",
        "url": "URL",
        "ts": "TS",
    }.items():
        human = human.replace(source.title(), target)
    return human.title().replace("Qna", "QnA")


def normalize_command_path(*parts: str | None) -> str:
    values = [str(part).strip() for part in parts if part and str(part).strip()]
    return " ".join(values).upper()


def _normalize_command_token(value: str | None) -> str:
    return str(value or "").strip().lower()


def _split_command_path(path: str | None) -> list[str]:
    return [part.strip() for part in str(path or "").split() if part and str(part).strip()]


def _normalize_relevant_parameter(value: object) -> str | None:
    normalized = _normalize_subtitle_argument(value)
    if not normalized:
        return None
    if ":" in normalized:
        _, tail = normalized.rsplit(":", 1)
        normalized = tail.strip() or normalized
    return normalized


def _normalize_subtitle_string(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith(("discord.", "<class ", "namespace(")):
        return None
    mention_match = _MENTION_RE.fullmatch(raw)
    if mention_match:
        return f"USER {mention_match.group('user_id')}"
    role_match = _ROLE_MENTION_RE.fullmatch(raw)
    if role_match:
        return f"ROLE {role_match.group('role_id')}"
    channel_match = _CHANNEL_MENTION_RE.fullmatch(raw)
    if channel_match:
        return f"CHANNEL {channel_match.group('channel_id')}"
    if any(token in raw for token in _RAW_OBJECT_HINTS) and len(raw) > 32:
        return None
    compact = " ".join(raw.split())
    if len(compact) > _MAX_SUBTITLE_ARG_LENGTH:
        return None
    return compact


def _discord_entity_display_name(value: object) -> str | None:
    for attr in ("display_name", "global_name", "name"):
        candidate = getattr(value, attr, None)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _normalize_subtitle_argument(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _normalize_subtitle_string(value)
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    if isinstance(value, (int, float)):
        return stringify_value(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC") if value.tzinfo is not None else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.isoformat()

    choice_value = getattr(value, "value", None)
    choice_name = getattr(value, "name", None)
    if choice_value is not None:
        normalized_choice = _normalize_subtitle_argument(choice_value)
        if normalized_choice:
            return normalized_choice
        if isinstance(choice_name, str):
            return _normalize_subtitle_string(choice_name)

    if isinstance(value, discord.Role):
        return _normalize_subtitle_string(value.name)
    if isinstance(value, (discord.Member, discord.User)):
        return _normalize_subtitle_string(_discord_entity_display_name(value))
    if isinstance(value, (discord.abc.GuildChannel, discord.Thread)):
        channel_name = getattr(value, "name", None)
        if isinstance(channel_name, str) and channel_name.strip():
            return _normalize_subtitle_string(channel_name)
        channel_id = getattr(value, "id", None)
        return _normalize_subtitle_string(str(channel_id)) if channel_id is not None else None

    entity_name = _discord_entity_display_name(value)
    if entity_name:
        return _normalize_subtitle_string(entity_name)

    return _normalize_subtitle_string(str(value))


def get_command_emoji(command: str | None) -> str:
    key = str(command or "").strip().lower()
    return TOP_LEVEL_EMOJIS.get(key, "🫛")


def get_section_emoji(title: str | None, *, kind: CommandKind = "info") -> str:
    key = str(title or "").strip().lower()
    return SECTION_EMOJIS.get(key, KIND_EMOJIS[kind])


def _iter_section_emoji_candidates(
    title: str | None,
    *,
    kind: CommandKind,
    explicit_emoji: str | None = None,
) -> Iterable[str]:
    normalized_title = _normalize_command_token(title)
    tokens = [token for token in re.split(r"[\s_-]+", normalized_title) if token]
    if explicit_emoji:
        yield explicit_emoji
    semantic_emoji = get_section_emoji(title, kind=kind)
    if semantic_emoji:
        yield semantic_emoji
    for token in (normalized_title, *tokens):
        fallback = SECTION_FALLBACK_EMOJIS.get(token)
        if fallback:
            yield fallback
    yield from _KIND_SECTION_FALLBACKS[kind]


def _resolve_section_emoji(
    title: str | None,
    *,
    kind: CommandKind,
    explicit_emoji: str | None = None,
    subtitle_emoji: str | None = None,
) -> str:
    blocked = {str(subtitle_emoji or "").strip()} - {""}
    seen: set[str] = set()
    for candidate in _iter_section_emoji_candidates(title, kind=kind, explicit_emoji=explicit_emoji):
        clean_candidate = str(candidate or "").strip()
        if not clean_candidate or clean_candidate in seen:
            continue
        seen.add(clean_candidate)
        if clean_candidate not in blocked:
            return clean_candidate
    return "📋" if "📋" not in blocked else "🧩"


def get_semantic_color(kind: CommandKind) -> int:
    return KIND_COLORS[kind]


def normalize_display_command_context(
    *,
    top_level: str,
    subcommand_path: str,
    kind: CommandKind = "info",
    visual_top_level: str | None = None,
    subtitle_args: Sequence[object] | None = None,
    relevant_parameters: Sequence[object] | None = None,
    top_level_emoji: str | None = None,
    subcommand_emoji: str | None = None,
) -> DisplayCommandContext:
    path_parts = _split_command_path(subcommand_path)
    raw_top_level = _normalize_command_token(top_level)
    inferred_visual_top_level = _normalize_command_token(visual_top_level)
    raw_parameters = [*(subtitle_args or ()), *(relevant_parameters or ())]

    if not inferred_visual_top_level and path_parts:
        candidate = _normalize_command_token(path_parts[0])
        if candidate in DISPLAY_TOP_LEVEL_OVERRIDES:
            inferred_visual_top_level = candidate

    if not inferred_visual_top_level:
        inferred_visual_top_level = raw_top_level or _normalize_command_token(path_parts[0] if path_parts else "")

    subtitle_parts = list(path_parts)
    if subtitle_parts and _normalize_command_token(subtitle_parts[0]) == inferred_visual_top_level:
        subtitle_parts = subtitle_parts[1:]
    subtitle_parts, consumed_parameter_indexes = _apply_temporal_subtitle_rules(subtitle_parts, raw_parameters)
    subtitle_parameter_parts: list[str] = []

    for index, raw_parameter in enumerate(raw_parameters):
        if index in consumed_parameter_indexes:
            continue
        normalized_parameter = _normalize_relevant_parameter(raw_parameter)
        if normalized_parameter is None:
            continue
        if any(_normalize_command_token(part) == _normalize_command_token(normalized_parameter) for part in subtitle_parts):
            continue
        subtitle_parts.append(normalized_parameter)
        subtitle_parameter_parts.append(normalized_parameter)

    if consumed_parameter_indexes and subtitle_parts:
        temporal_tail = subtitle_parts[-1]
        if temporal_tail not in subtitle_parameter_parts:
            subtitle_parameter_parts.insert(0, temporal_tail)

    visual_subtitle = normalize_command_path(*subtitle_parts)
    resolved_subtitle_emoji = subcommand_emoji or KIND_EMOJIS[kind]
    resolved_title_emoji = top_level_emoji or get_command_emoji(inferred_visual_top_level or raw_top_level)

    return DisplayCommandContext(
        visual_top_level=inferred_visual_top_level.upper(),
        visual_title=inferred_visual_top_level.upper(),
        title_emoji=resolved_title_emoji,
        visual_subtitle=visual_subtitle,
        subtitle_emoji=resolved_subtitle_emoji,
        visual_subtitle_parts=tuple(normalize_command_path(part) for part in subtitle_parts),
        subtitle_parameter_parts=tuple(normalize_command_path(part) for part in subtitle_parameter_parts),
    )


def stringify_value(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, dict, tuple, set)):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return str(value)
    return str(value)


def format_bullet(label: str, value: Any, *, kind: CommandKind = "info") -> str:
    rendered_value = stringify_value(value)
    if isinstance(value, str):
        rendered_value = _strip_duplicate_kind_emoji(rendered_value, kind=kind)
    return _strip_duplicate_kind_emoji(f"• {humanize_key(label)}: **{rendered_value}**", kind=kind)


def build_section(
    title: str,
    lines: Sequence[tuple[str, Any]] | Sequence[str],
    emoji: str | None = None,
    *,
    kind: CommandKind = "info",
    line_formatter: Callable[[str, Any], str] | None = None,
    subtitle_emoji: str | None = None,
) -> str:
    header_emoji = _resolve_section_emoji(title, kind=kind, explicit_emoji=emoji, subtitle_emoji=subtitle_emoji)
    rendered = [f"**{header_emoji} {title.upper()}**"]
    for line in lines:
        if isinstance(line, str):
            cleaned_line = _strip_duplicate_kind_emoji(line, kind=kind)
            rendered.append(_strip_duplicate_leading_emoji(cleaned_line, emoji=subtitle_emoji))
        else:
            formatter = line_formatter or (lambda label, value: format_bullet(label, value, kind=kind))
            cleaned_line = _strip_duplicate_kind_emoji(formatter(line[0], line[1]), kind=kind)
            rendered.append(_strip_duplicate_leading_emoji(cleaned_line, emoji=subtitle_emoji))
    return "\n".join(rendered)



async def _resolve_brand_text(footer_service: FooterService | None) -> str:
    if footer_service is None:
        return "Barcellometro"
    version = await footer_service.get_version()
    return f"Barcellometro {version}" if version else "Barcellometro"


def _resolve_footer_service_name(
    *,
    footer_service_name: str | None,
    visual_top_level: str | None,
    top_level: str,
) -> str:
    explicit = _normalize_command_token(footer_service_name)
    if explicit:
        return explicit
    for candidate in (
        _normalize_command_token(visual_top_level),
        _normalize_command_token(top_level),
    ):
        if not candidate:
            continue
        mapped = _FOOTER_SERVICE_FALLBACKS.get(candidate, candidate)
        if mapped:
            return mapped
    return "status"


async def build_command_embeds(
    *,
    top_level: str,
    subcommand_path: str,
    visual_top_level: str | None = None,
    subtitle_args: Sequence[object] | None = None,
    relevant_parameters: Sequence[object] | None = None,
    lines: Sequence[tuple[str, Any]] | None = None,
    sections: Sequence[CommandEmbedSection | dict[str, Any]] | None = None,
    kind: CommandKind = "info",
    top_level_emoji: str | None = None,
    subcommand_emoji: str | None = None,
    footer_service: FooterService | None = None,
    footer_mode: FooterMode = "minimal",
    footer_service_name: str | None = None,
    compact_lines: bool = False,
    line_formatter: Callable[[str, Any], str] | None = None,
    section_title_formatter: Callable[[str], str] | None = None,
) -> list[discord.Embed]:
    display_context = normalize_display_command_context(
        top_level=top_level,
        subcommand_path=subcommand_path,
        kind=kind,
        visual_top_level=visual_top_level,
        subtitle_args=subtitle_args,
        relevant_parameters=relevant_parameters,
        top_level_emoji=top_level_emoji,
        subcommand_emoji=subcommand_emoji,
    )
    title = f"{display_context.title_emoji} {display_context.visual_title}"
    raw_subtitle_parameters = [*(subtitle_args or ()), *(relevant_parameters or ())]
    blocks: list[str] = []
    header = f"**{display_context.subtitle_emoji} {display_context.visual_subtitle}**" if display_context.visual_subtitle else ""
    resolved_line_formatter = line_formatter or (lambda label, value: format_bullet(label, value, kind=kind))
    rendered_lines = [
        _strip_duplicate_leading_emoji(rendered, emoji=display_context.subtitle_emoji)
        for label, value in lines or []
        if (rendered := _format_primary_bullet(
            label,
            value,
            display_context=display_context,
            raw_subtitle_parameters=raw_subtitle_parameters,
            kind=kind,
            line_formatter=resolved_line_formatter,
        )) is not None
    ]
    if header:
        blocks.append(header)
    if compact_lines and rendered_lines:
        blocks.append("\n".join(rendered_lines))
    else:
        blocks.extend(rendered_lines)
    for section in sections or []:
        if isinstance(section, dict):
            item = CommandEmbedSection(
                title=str(section.get("title") or "Section"),
                lines=list(section.get("lines") or []),
                emoji=section.get("emoji"),
            )
        else:
            item = section
        section_title = (section_title_formatter or str)(item.title)
        blocks.append(
            build_section(
                section_title,
                item.lines,
                item.emoji,
                kind=kind,
                line_formatter=line_formatter,
                subtitle_emoji=display_context.subtitle_emoji,
            )
        )

    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= _MAX_DESCRIPTION:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(block) <= _MAX_DESCRIPTION:
            current = block
            continue
        lines_split = block.splitlines()
        current = ""
        for line in lines_split:
            candidate_line = line if not current else f"{current}\n{line}"
            if len(candidate_line) <= _MAX_DESCRIPTION:
                current = candidate_line
            else:
                if current:
                    chunks.append(current)
                current = line[:_MAX_DESCRIPTION]
        
    if current:
        chunks.append(current)

    brand_text = await _resolve_brand_text(footer_service)
    resolved_footer_service_name = _resolve_footer_service_name(
        footer_service_name=footer_service_name,
        visual_top_level=visual_top_level or display_context.visual_top_level,
        top_level=top_level,
    )
    embeds: list[discord.Embed] = []
    color = get_semantic_color(kind)
    for chunk in chunks or [blocks[0]]:
        embed = discord.Embed(title=title, description=chunk, color=color)
        if footer_mode == "minimal":
            if footer_service is None:
                attach_minimal_footer(embed, text=brand_text)
            else:
                attach_footer_meta(
                    embed,
                    service_name=resolved_footer_service_name,
                    used_local_processing=True,
                )
        elif footer_mode == "meta":
            if footer_service is None:
                attach_minimal_footer(embed, text=brand_text)
            else:
                attach_footer_meta(
                    embed,
                    service_name=resolved_footer_service_name,
                    used_local_processing=True,
                )
        embeds.append(embed)
    return embeds


async def build_command_embed(**kwargs: Any) -> discord.Embed:
    embeds = await build_command_embeds(**kwargs)
    return embeds[0]


async def send_command_embed(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed,
    ephemeral: bool = True,
    content: str | None = None,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)


async def send_command_embeds(
    interaction: discord.Interaction,
    *,
    embeds: Iterable[discord.Embed],
    ephemeral: bool = True,
    content: str | None = None,
    files: list[discord.File] | None = None,
) -> None:
    embed_list = list(embeds)
    if not embed_list:
        return
    first = embed_list[0]
    extras = embed_list[1:]
    kwargs: dict[str, Any] = {
        "content": content,
        "embed": first,
        "ephemeral": ephemeral,
    }
    if files:
        kwargs["files"] = files
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)
    for extra in extras:
        await interaction.followup.send(embed=extra, ephemeral=ephemeral)


async def send_standard_response(
    interaction: discord.Interaction,
    *,
    top_level: str,
    subcommand_path: str,
    visual_top_level: str | None = None,
    subtitle_args: Sequence[object] | None = None,
    relevant_parameters: Sequence[object] | None = None,
    lines: Sequence[tuple[str, Any]] | None = None,
    sections: Sequence[CommandEmbedSection | dict[str, Any]] | None = None,
    kind: CommandKind = "info",
    footer_service: FooterService | None = None,
    ephemeral: bool = True,
    files: list[discord.File] | None = None,
    footer_mode: FooterMode = "minimal",
    footer_service_name: str | None = None,
    compact_lines: bool = False,
    line_formatter: Callable[[str, Any], str] | None = None,
    section_title_formatter: Callable[[str], str] | None = None,
    top_level_emoji: str | None = None,
    subcommand_emoji: str | None = None,
) -> None:
    embeds = await build_command_embeds(
        top_level=top_level,
        subcommand_path=subcommand_path,
        visual_top_level=visual_top_level,
        subtitle_args=subtitle_args,
        relevant_parameters=relevant_parameters,
        lines=lines,
        sections=sections,
        kind=kind,
        footer_service=footer_service,
        footer_mode=footer_mode,
        footer_service_name=footer_service_name,
        compact_lines=compact_lines,
        line_formatter=line_formatter,
        section_title_formatter=section_title_formatter,
        top_level_emoji=top_level_emoji,
        subcommand_emoji=subcommand_emoji,
    )
    await send_command_embeds(interaction, embeds=embeds, ephemeral=ephemeral, files=files)


_LEGACY_TOP_LEVEL_EMOJIS: dict[str, str] = {
    "admin": "🧭",
}

_LEGACY_CONTEXT_EMOJIS: dict[str, str] = {
    "status": "📊",
    "events": "📡",
    "retention": "🗃️",
    "backfill": "♻️",
    "ai": "🧠",
    "audionotes": "🎙️",
    "voice_ingest": "🎤",
    "footer": "🧩",
    "config": "⚙️",
    "run": "▶️",
    "error": "❌",
    "warning": "⚠️",
    "success": "✅",
    "info": "ℹ️",
}


def _legacy_display_value(value: object) -> str:
    if isinstance(value, bool):
        return "On" if value else "Off"
    if value is None:
        return "(n/a)"
    text = str(value).strip()
    return text or "(empty)"


def _legacy_format_bullet(label: str, value: Any) -> str:
    normalized = str(label).replace("_", " ").replace("-", " ").strip().title()
    return f"• {normalized}: **{_legacy_display_value(value)}**"


def _legacy_section_title(section_key: str) -> str:
    return str(section_key).replace("_", " ").replace("-", " ").upper()


def _legacy_context_emoji(path_parts: Sequence[str], tone: CommandKind) -> str:
    for key in reversed(path_parts):
        if key in _LEGACY_CONTEXT_EMOJIS:
            return _LEGACY_CONTEXT_EMOJIS[key]
    return _LEGACY_CONTEXT_EMOJIS.get(tone, "ℹ️")


async def send_legacy_standard_response(
    interaction: discord.Interaction,
    *,
    top_level: str,
    path_parts: Sequence[str],
    entries: Iterable[tuple[str, object]],
    tone: CommandKind = "info",
    sections: Sequence[tuple[str, Sequence[tuple[str, object]]]] | None = None,
    service_name: str = "status",
    footer_service: FooterService | None = None,
    ephemeral: bool = True,
) -> None:
    normalized_path = [part.strip().lower() for part in path_parts if part and part.strip()]
    subcommand_path = " ".join(part.replace("-", " ").upper() for part in normalized_path) or top_level.strip().upper()
    context_emoji = _legacy_context_emoji(normalized_path, tone)
    legacy_sections = [
        CommandEmbedSection(
            title=_legacy_section_title(section_name),
            lines=list(section_entries),
            emoji=context_emoji,
        )
        for section_name, section_entries in sections or ()
        if section_entries
    ]
    await send_standard_response(
        interaction,
        top_level=top_level,
        subcommand_path=subcommand_path,
        lines=list(entries),
        sections=legacy_sections,
        kind=tone,
        ephemeral=ephemeral,
        compact_lines=True,
        line_formatter=_legacy_format_bullet,
        footer_service=footer_service,
        footer_mode="meta",
        footer_service_name=service_name,
        top_level_emoji=_LEGACY_TOP_LEVEL_EMOJIS.get(top_level.strip().lower(), "🧭"),
        subcommand_emoji=KIND_EMOJIS[tone],
    )
