from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import discord
from app.services.author import attach_author_meta_to_all
from app.services.embed_images import attach_embed_images_meta
from app.services.footer import attach_footer_meta_to_all
from app.shared.discord.embed_body import format_standard_description, format_standard_field_name, format_standard_title

DEFAULT_COLOR = 0x2F3136


SIGN_ORDER = [
    "Ariete",
    "Toro",
    "Gemelli",
    "Cancro",
    "Leone",
    "Vergine",
    "Bilancia",
    "Scorpione",
    "Sagittario",
    "Capricorno",
    "Acquario",
    "Pesci",
]

SIGN_EMOJIS = {
    "Ariete": "♈",
    "Toro": "♉",
    "Gemelli": "♊",
    "Cancro": "♋",
    "Leone": "♌",
    "Vergine": "♍",
    "Bilancia": "♎",
    "Scorpione": "♏",
    "Sagittario": "♐",
    "Capricorno": "♑",
    "Acquario": "♒",
    "Pesci": "♓",
}

CATEGORY_DISPLAY_NAMES = {
    "cronaca": "Cronaca",
    "politica": "Politica",
    "sport": "Sport",
    "spettacolo": "Spettacolo",
    "gossip": "Gossip",
    "tecnologia": "Tecnologia",
    "tech": "Tecnologia",
    "economia": "Economia",
    "mondo": "Mondo",
    "viral": "Viral",
    "trash": "Trash",
    "curiosita": "Curiosità",
    "curiosità": "Curiosità",
    "varie": "Varie",
}

CATEGORY_EMOJIS = {
    "cronaca": "📰",
    "politica": "🏛️",
    "sport": "⚽",
    "spettacolo": "🎭",
    "gossip": "👀",
    "tecnologia": "💻",
    "tech": "💻",
    "economia": "💸",
    "mondo": "🌍",
    "viral": "🚀",
    "trash": "🐔",
    "curiosita": "✨",
    "curiosità": "✨",
    "varie": "📌",
}

WEATHER_AREA_LABELS = {
    "nord": "🧊 NORD",
    "centro": "🏛️ CENTRO",
    "sud e isole": "🌋 SUD E ISOLE",
}

HOROSCOPE_SECTIONS = ["love", "work", "money", "energy", "friction", "advice"]


def resolve_color(color_raw: str | None) -> int:
    if not color_raw:
        return DEFAULT_COLOR
    value = color_raw.strip().lower().replace("#", "").replace("0x", "")
    try:
        return int(value, 16)
    except ValueError:
        return DEFAULT_COLOR


def _with_footer(embed: discord.Embed, page: int, total: int) -> discord.Embed:
    # Keep signature for backwards compatibility: pagination numbering removed.
    _ = (page, total)
    return embed


def apply_shared_footer_and_pagination(embeds: list[discord.Embed], footer_text: str) -> list[discord.Embed]:
    # Footer rendering now happens through the centralized footer pipeline before
    # payload persistence and dispatch. Keep this helper as a no-op shim because
    # older call sites still invoke it for pagination compatibility.
    _ = footer_text
    total = max(1, len(embeds))
    for idx, embed in enumerate(embeds, start=1):
        _with_footer(embed, idx, total)
    return embeds


def _apply_campaign_footer(embeds: list[discord.Embed], *, service_name: str) -> list[discord.Embed]:
    attach_footer_meta_to_all(embeds, service_name=service_name, used_local_processing=True)
    attach_author_meta_to_all(embeds, service_name=service_name, canonical_top_level_command="campaigns")
    return embeds


def slugify_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "default"


def get_category_display_name(category: str) -> str:
    key = slugify_label(category).replace("_", " ")
    if key in CATEGORY_DISPLAY_NAMES:
        return CATEGORY_DISPLAY_NAMES[key]
    return " ".join(part.capitalize() for part in key.split()) or "Varie"


def get_category_emoji(category: str) -> str:
    key = slugify_label(category).replace("_", " ")
    return CATEGORY_EMOJIS.get(key, "📌")


def get_weather_area_label(area: str) -> str:
    key = slugify_label(area).replace("_", " ")
    return WEATHER_AREA_LABELS.get(key, f"📍 {get_category_display_name(area).upper()}")


def sanitize_plain_text(text: str, *, remove_category_hint: str | None = None) -> str:
    cleaned = re.sub(r"[`*_>#\-]{1,3}\s*", "", str(text or ""), flags=re.MULTILINE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if remove_category_hint:
        cleaned = re.sub(rf"^{re.escape(remove_category_hint)}\s*[:\-–|]+\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def sanitize_horoscope_text(sign: str, text: str) -> str:
    cleaned = sanitize_plain_text(text)
    if not cleaned:
        return ""
    heading_pattern = (
        rf"^({re.escape(sign)}\s*[:\-–|]+\s*|{re.escape(sign)}\s+)?"
        r"(love\s*alert|money\s*vibes|energia\s*del\s*genio|amore|lavoro|soldi|energia|consiglio|friction)\s*[:\-–|]+\s*"
    )
    cleaned = re.sub(heading_pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def trim_sentence_block(text: str, *, limit: int = 320) -> str:
    normalized = sanitize_plain_text(text)
    if len(normalized) <= limit:
        return normalized
    clipped = normalized[:limit]
    cut = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if cut >= int(limit * 0.6):
        return clipped[: cut + 1].strip()
    return clipped.rstrip() + "…"


_NEWS_META_PREFIX_RE = re.compile(
    r"(?im)^\s*(?:[-•*]\s*)?(?:🧃\s*)?"
    r"(?:in breve|riassunto|sintesi|ecco(?:\s+la)?\s+riscrizione|testo riformulato|riscrittura)\s*:\s*"
)
_NEWS_META_LINE_RE = re.compile(
    r"(?im)^\s*(?:ecco(?:\s+la)?\s+riscrizione(?:\s+del\s+testo)?|testo riformulato|riassunto editoriale|"
    r"output finale|versione finale|assistente editoriale)\b[^\n]*$"
)
_NEWS_BAD_FALLBACKS = {
    "aggiornamento in arrivo.",
    "aggiornamento in arrivo",
    "nessun riassunto disponibile",
    "nessun riassunto disponibile.",
}
_NEWS_MAX_SENTENCES = 2
_NEWS_FIELD_HARD_LIMIT = 1024
_NEWS_MAX_EDITORIAL_CATEGORIES = 3
_ITALY_TZ = ZoneInfo("Europe/Rome")
NEWS_EXTRA_ORDER = ["barzelletta", "aforisma", "canzone", "meme"]
NEWS_EXTRA_FIELD_TITLES = {
    "barzelletta": ("😂 BARZELLETTA DEL GIORNO", "😂"),
    "aforisma": ("🧠 AFORISMA DEL GIORNO", "🧠"),
    "canzone": ("🎵 CANZONE DEL GIORNO", "🎵"),
    "meme": ("🖼️ MEME DEL GIORNO", "🖼️"),
}
NEWS_EXTRA_CATALOG = {
    "barzelletta": [
        "Perché il criceto non litiga mai col meteo? Perché tiene sempre il sangue freddo.",
        "Il giornalista chiede al criceto: «Hai fonti?» — «Sì, ma non le rosicchio.»",
        "«Ultim’ora?» «No, ultima ruota: quella della mia corsa in redazione.»",
    ],
    "aforisma": [
        "La chiarezza è la forma più elegante della verità.",
        "Le notizie passano, il criterio resta.",
        "Chi ascolta bene capisce prima del rumore.",
    ],
    "canzone": [
        "Viva La Vida — Coldplay\nUna spinta epica per la prossima corsa in redazione.",
        "La Cura — Franco Battiato\nParole misurate e atmosfera da chiusura stampa.",
        "Heroes — David Bowie\nEnergia da prima pagina e sguardo lungo.",
    ],
    "meme": [
        "Quando dici «solo un titolo» e apri 14 tab in 30 secondi.",
        "Io: «Controllo una notizia al volo». Anche io, due ore dopo: «Edizione straordinaria».",
        "Il criceto in regia quando arriva il breaking: modalità turbo attivata.",
    ],
}


def sanitize_public_news_text(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"```(?:\w+)?", "", cleaned, flags=re.IGNORECASE).replace("```", "")
    cleaned = _NEWS_META_PREFIX_RE.sub("", cleaned)
    cleaned = _NEWS_META_LINE_RE.sub("", cleaned)
    cleaned = re.sub(r"(?im)^\s*(?:nota|istruzione|prompt|spiegazione)\s*:\s*[^\n]*$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \n\t-•")
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    return cleaned.strip()


def _is_useless_news_text(text: str) -> bool:
    normalized = sanitize_public_news_text(text).lower()
    return not normalized or normalized in _NEWS_BAD_FALLBACKS


def _take_news_sentences(text: str, *, max_sentences: int = _NEWS_MAX_SENTENCES) -> str:
    candidate = sanitize_public_news_text(text)
    if not candidate:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", candidate)
    picked: list[str] = []
    for sentence in sentences:
        normalized = sentence.strip()
        if not normalized:
            continue
        picked.append(normalized)
        if len(picked) >= max_sentences:
            break
    return " ".join(picked) if picked else candidate


def _first_real_news_sentences(item: dict[str, Any]) -> str:
    for key in ("summary", "description", "excerpt", "content", "text"):
        candidate = sanitize_public_news_text(str(item.get(key) or ""))
        if _is_useless_news_text(candidate):
            continue
        return _take_news_sentences(candidate)
    return "Dettagli in aggiornamento."


def _news_source_line(item: dict[str, Any], *, link: str) -> str:
    source_raw = sanitize_plain_text(str(item.get("source") or "")).lower()
    source_line = source_raw
    if "http" in source_line:
        parsed_source = urlparse(source_line)
        source_line = parsed_source.netloc or source_line
    if "." not in source_line and link:
        parsed_link = urlparse(link)
        source_line = parsed_link.netloc or source_line
    if source_line and not source_line.startswith("www."):
        source_line = f"www.{source_line}"
    return source_line.strip() or "www.nd.it"


def _build_news_item_summary(item: dict[str, Any], *, display: str) -> str:
    summary = sanitize_public_news_text(str(item.get("summary") or ""))
    summary = sanitize_plain_text(summary, remove_category_hint=display)
    if _is_useless_news_text(summary):
        return _first_real_news_sentences(item)
    return _take_news_sentences(summary)


def _truncate_news_summary(summary: str, *, max_chars: int) -> str:
    if len(summary) <= max_chars:
        return summary
    clipped = summary[:max_chars].rstrip()
    cut = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
    if cut >= int(max_chars * 0.6):
        return clipped[: cut + 1].strip()
    return clipped.rstrip(" ,;:") + "…"


def _format_news_item_block(
    item: dict[str, Any],
    *,
    display: str,
    numbered: bool,
    index: int,
    max_summary_chars: int | None = None,
) -> str:
    link = str(item.get("link") or "").strip()
    title_line = sanitize_plain_text(str(item.get("title") or "Titolo non disponibile"))
    linked_title = f"[{title_line}]({link})" if link else title_line
    summary = _build_news_item_summary(item, display=display)
    if max_summary_chars is not None and max_summary_chars > 0:
        summary = _truncate_news_summary(summary, max_chars=max_summary_chars)
    source_line = _news_source_line(item, link=link)
    heading = f"{index}. **{linked_title}**" if numbered else f"**{linked_title}**"
    return f"{heading}\n• {summary}\n`fonte: {source_line}`"


def similarity_title(a: str, b: str) -> float:
    return SequenceMatcher(None, sanitize_plain_text(a).lower(), sanitize_plain_text(b).lower()).ratio()


def news_edition_label_for_datetime(dt: datetime) -> tuple[str, str]:
    local_dt = dt.astimezone(_ITALY_TZ)
    minute_of_day = local_dt.hour * 60 + local_dt.minute
    if 5 * 60 <= minute_of_day <= 11 * 60 + 59:
        return "EDIZIONE MATTUTINA", "mattina"
    if 12 * 60 <= minute_of_day <= 17 * 60 + 59:
        return "EDIZIONE POMERIDIANA", "pomeriggio"
    if 18 * 60 <= minute_of_day <= 22 * 60 + 59:
        return "EDIZIONE SERALE", "sera"
    return "EDIZIONE NOTTURNA", "notte"


def _time_of_day_label(dt: datetime) -> str:
    return news_edition_label_for_datetime(dt)[1]


def _overview_now(payload: dict[str, Any]) -> datetime:
    raw = payload.get("generated_at") or payload.get("published_at") or payload.get("created_at")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            base = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            return base.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _news_identity(item: dict[str, Any]) -> str:
    link = " ".join(str(item.get("link") or "").strip().split())
    normalized_link = link.lower().rstrip("/")
    if normalized_link:
        return f"url:{normalized_link}"
    title = " ".join(sanitize_plain_text(str(item.get("title") or "")).lower().split())
    if title:
        return f"title:{title}"
    return ""


def _is_valid_news_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    title = sanitize_plain_text(str(item.get("title") or ""))
    if not title:
        return False
    link = str(item.get("link") or "").strip()
    if link:
        return True
    return bool(_first_real_news_sentences(item).strip())


def _valid_news_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items if _is_valid_news_item(item)]


def _parse_news_datetime(raw: Any) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _build_single_news_field_value(item: dict[str, Any], *, display: str) -> str:
    for summary_limit in [280, 220, 170]:
        value = _format_news_item_block(
            item,
            display=display,
            numbered=False,
            index=0,
            max_summary_chars=summary_limit,
        )
        if len(value) <= _NEWS_FIELD_HARD_LIMIT:
            return value
    return _format_news_item_block(item, display=display, numbered=False, index=0, max_summary_chars=120)[:_NEWS_FIELD_HARD_LIMIT]


def _iter_configured_editorial_categories(payload: dict[str, Any]) -> list[str]:
    categories = payload.get("categories", {})
    if not isinstance(categories, dict):
        return []
    configured = payload.get("configured_categories")
    ordered: list[str]
    if isinstance(configured, list):
        ordered = [str(category).strip() for category in configured]
    else:
        ordered = [str(category).strip() for category in categories.keys()]
    normalized_available = {str(category).strip().lower(): str(category) for category in categories.keys()}
    selected: list[str] = []
    seen: set[str] = set()
    for category in ordered:
        key = category.lower()
        if not key or key == "varie":
            continue
        mapped = normalized_available.get(key)
        if mapped is None:
            continue
        if key in seen:
            continue
        seen.add(key)
        selected.append(mapped)
    return selected


def _collect_deduped_news_pool(payload: dict[str, Any]) -> list[dict[str, Any]]:
    categories = payload.get("categories", {})
    if not isinstance(categories, dict):
        return []
    merged: list[dict[str, Any]] = []
    for category_items in categories.values():
        merged.extend(_valid_news_items(category_items))
    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in merged:
        key = _news_identity(item)
        if not key or key in seen:
            continue
        seen.add(key)
        pool.append(item)
    return pool


def _collect_news_identity_counts(payload: dict[str, Any]) -> dict[str, int]:
    categories = payload.get("categories", {})
    if not isinstance(categories, dict):
        return {}
    counts: dict[str, int] = {}
    for category_items in categories.values():
        for item in _valid_news_items(category_items):
            key = _news_identity(item)
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
    return counts


def _news_identity_counts(pool: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in pool:
        key = _news_identity(item)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _select_breaking_news_item(pool: list[dict[str, Any]], *, identity_counts: dict[str, int] | None = None) -> dict[str, Any] | None:
    if not pool:
        return None
    dated = [item for item in pool if _parse_news_datetime(item.get("published_at")) is not None]
    if dated:
        return max(
            dated,
            key=lambda item: (_parse_news_datetime(item.get("published_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc)).timestamp(),
        )
    counts = identity_counts or _news_identity_counts(pool)
    for item in pool:
        key = _news_identity(item)
        if key and counts.get(key, 0) == 1:
            return item
    return pool[0]


def _score_featured_news_item(item: dict[str, Any], *, now_utc: datetime) -> tuple[float, float, float]:
    title_len = len(sanitize_plain_text(str(item.get("title") or "")))
    summary_len = len(_build_news_item_summary(item, display=""))
    published = _parse_news_datetime(item.get("published_at"))
    recency = 0.0
    if published is not None:
        age_hours = max(0.0, (now_utc - published.astimezone(timezone.utc)).total_seconds() / 3600.0)
        recency = max(0.0, 48.0 - min(age_hours, 48.0))
    return (recency, float(min(summary_len, 240)), float(min(title_len, 120)))


def _select_featured_news_item(
    pool: list[dict[str, Any]],
    *,
    used_ids: set[str],
    now_utc: datetime,
    identity_counts: dict[str, int] | None = None,
    discouraged_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    counts = identity_counts or _news_identity_counts(pool)
    candidates = [item for item in pool if (key := _news_identity(item)) and key not in used_ids]
    if not candidates:
        return None
    discouraged = discouraged_ids or set()
    preferred = [item for item in candidates if _news_identity(item) not in discouraged]
    candidate_pool = preferred if preferred else candidates
    return max(
        candidate_pool,
        key=lambda item: (_score_featured_news_item(item, now_utc=now_utc), 1 if counts.get(_news_identity(item), 0) == 1 else 0),
    )


def _select_editorial_category_item(
    category_items: Any,
    *,
    top_used_ids: set[str],
    category_used_ids: set[str],
    allow_top_duplicates: bool = False,
) -> dict[str, Any] | None:
    fallback: dict[str, Any] | None = None
    for item in _valid_news_items(category_items):
        key = _news_identity(item)
        if not key or key in category_used_ids:
            continue
        if fallback is None:
            fallback = item
        if key in top_used_ids and not allow_top_duplicates:
            continue
        return item
    return fallback if allow_top_duplicates else None


def _build_news_extra_fields(config: dict[str, Any], *, base_dt: datetime) -> list[tuple[str, str]]:
    extras_enabled = _normalize_news_extras(config.get("extras_json"))
    fields: list[tuple[str, str]] = []
    for extra in NEWS_EXTRA_ORDER:
        if extra not in extras_enabled:
            continue
        title_text, emoji = NEWS_EXTRA_FIELD_TITLES[extra]
        content = _daily_rotating_pick(NEWS_EXTRA_CATALOG[extra], base_dt=base_dt)
        if not content:
            continue
        label_text = title_text
        if label_text.startswith(f"{emoji} "):
            label_text = label_text[len(emoji) + 1 :]
        fields.append((format_standard_field_name(label_text, emoji=emoji), content[:_NEWS_FIELD_HARD_LIMIT]))
    return fields


def _first_editorial_story_ids(payload: dict[str, Any]) -> set[str]:
    categories = payload.get("categories", {})
    if not isinstance(categories, dict):
        return set()
    first_ids: set[str] = set()
    for category in _iter_configured_editorial_categories(payload):
        first_item = _select_editorial_category_item(
            categories.get(category),
            top_used_ids=set(),
            category_used_ids=set(),
            allow_top_duplicates=True,
        )
        if first_item is None:
            continue
        story_id = _news_identity(first_item)
        if story_id:
            first_ids.add(story_id)
    return first_ids


def _daily_rotating_pick(pool: list[str], *, base_dt: datetime) -> str:
    if not pool:
        return ""
    day_index = int(base_dt.astimezone(_ITALY_TZ).strftime("%Y%m%d"))
    return pool[day_index % len(pool)]


def _normalize_news_extras(raw: Any) -> list[str]:
    if isinstance(raw, list):
        tokens = [str(item).strip().lower() for item in raw]
    else:
        text = str(raw or "").strip()
        parsed_tokens: list[str] | None = None
        if text.startswith("["):
            try:
                import json

                parsed = json.loads(text)
                if isinstance(parsed, list):
                    parsed_tokens = [str(item).strip().lower() for item in parsed]
            except Exception:
                parsed_tokens = None
        tokens = parsed_tokens if parsed_tokens is not None else [str(item).strip().lower() for item in text.split(",")]
    normalized: list[str] = []
    for token in tokens:
        if token in NEWS_EXTRA_ORDER and token not in normalized:
            normalized.append(token)
    return normalized


def _next_news_run_field(config: dict[str, Any], *, generated_at: datetime) -> str | None:
    interval = int(config.get("interval_minutes") or 0)
    if interval <= 0:
        return None
    next_run = generated_at.astimezone(_ITALY_TZ) + timedelta(minutes=interval)
    return (
        "Il criceto chiude il taccuino per ora. "
        f"Ci rivediamo alle **{next_run.strftime('%H:%M')}** con la prossima edizione."
    )


def _first_story_image_url(categories: list[tuple[str, str, str, list[dict[str, Any]]]]) -> str | None:
    image_keys = ("image", "image_url", "imageUrl", "urlToImage", "thumbnail", "thumbnail_url", "media_url")
    for _, _, _, items in categories:
        for pool_item in items:
            for key in image_keys:
                candidate = str(pool_item.get(key) or "").strip()
                if not candidate:
                    continue
                parsed = urlparse(candidate)
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    return candidate
    return None


def build_news_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
    now_utc = _overview_now(payload)
    edition_label, daypart = news_edition_label_for_datetime(now_utc)
    overview = discord.Embed(title=format_standard_title(f"📰 HAMSTER NEWS • {edition_label}"), color=color)
    overview.description = format_standard_description(
        (
            f"🐹 Buona **{daypart}**: qui Barcellometro in regia, con la redazione più rumorosa del quartiere. "
            "Titoli caldi, pochi giri di parole e dritti al punto.\n"
            "**Che ci dice il mondo quest'oggi?**"
        ),
        blank_line_before_fields=True,
    )
    all_items = _collect_deduped_news_pool(payload)
    identity_counts = _collect_news_identity_counts(payload) or _news_identity_counts(all_items)
    discouraged_featured_ids = _first_editorial_story_ids(payload)
    used_ids: set[str] = set()
    latest_item = _select_breaking_news_item(all_items, identity_counts=identity_counts)
    if latest_item is not None:
        latest_key = _news_identity(latest_item)
        if latest_key:
            used_ids.add(latest_key)
        overview.add_field(
            name=format_standard_field_name("ULTIM'ORA", emoji="⚡"),
            value=_build_single_news_field_value(latest_item, display="ULTIM'ORA"),
            inline=False,
        )
    highlighted = _select_featured_news_item(
        all_items,
        used_ids=used_ids,
        now_utc=now_utc,
        identity_counts=identity_counts,
        discouraged_ids=discouraged_featured_ids,
    )
    if highlighted is not None:
        highlighted_key = _news_identity(highlighted)
        if highlighted_key:
            used_ids.add(highlighted_key)
        overview.add_field(
            name=format_standard_field_name("IN EVIDENZA", emoji="🌟"),
            value=_build_single_news_field_value(highlighted, display="IN EVIDENZA"),
            inline=False,
        )
    editorial_categories: list[tuple[str, str, str, dict[str, Any]]] = []
    categories = payload.get("categories", {})
    if isinstance(categories, dict):
        configured_editorial_categories = _iter_configured_editorial_categories(payload)
        allow_top_duplicates = True
        top_used_ids = set(used_ids)
        category_used_ids: set[str] = set()
        for category in configured_editorial_categories:
            selected_item = _select_editorial_category_item(
                categories.get(category),
                top_used_ids=top_used_ids,
                category_used_ids=category_used_ids,
                allow_top_duplicates=allow_top_duplicates,
            )
            if selected_item is None:
                continue
            story_id = _news_identity(selected_item)
            if story_id:
                category_used_ids.add(story_id)
            display = get_category_display_name(category)
            editorial_categories.append((category, display, get_category_emoji(category), selected_item))
            if len(editorial_categories) >= _NEWS_MAX_EDITORIAL_CATEGORIES:
                break
    for _, display, _, item in editorial_categories:
        overview.add_field(
            name=format_standard_field_name(f"{display} IN PRIMO PIANO"),
            value=_build_single_news_field_value(item, display=display),
            inline=False,
        )
    for field_name, field_value in _build_news_extra_fields(config, base_dt=now_utc):
        overview.add_field(name=field_name, value=field_value, inline=False)
    next_run_field = _next_news_run_field(config, generated_at=now_utc)
    if next_run_field:
        overview.add_field(
            name=format_standard_field_name("PROSSIMA EDIZIONE", emoji="🔜"),
            value=next_run_field,
            inline=False,
        )
    first_image_url = _first_story_image_url([(cat, d, e, [item]) for cat, d, e, item in editorial_categories])
    if first_image_url is None and latest_item is not None:
        first_image_url = _first_story_image_url([("ultimora", "Ultim'ora", "⚡", [latest_item])])
    attach_embed_images_meta(
        overview,
        service_name="campagne_notizie",
        image_url=first_image_url,
    )
    return _apply_campaign_footer([overview], service_name="campagne_notizie")


def build_news_page_map(payload: dict[str, Any]) -> list[dict[str, Any]]:
    _ = payload
    return [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]


def build_weather_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
    title = config.get("embed_title") or "🌦️ Meteo Italia"
    regions = payload.get("regions", {})

    all_temps: list[float] = []
    area_scores: dict[str, float] = {}
    area_notes: dict[str, str] = {}
    for area, area_payload in regions.items():
        area_payload = area_payload if isinstance(area_payload, dict) else {"sampled_cities": area_payload}
        sampled = area_payload.get("sampled_cities", [])
        temps = [float(e["temperature"]) for e in sampled if isinstance(e.get("temperature"), (int, float))]
        winds = [float(e["windspeed"]) for e in sampled if isinstance(e.get("windspeed"), (int, float))]
        rainy = sum(1 for e in sampled if any(token in str(e.get("condition", "")) for token in ["piogg", "roves", "tempor"]))
        all_temps.extend(temps)
        area_scores[area] = rainy * 2 + (sum(winds) / len(winds) / 10 if winds else 0)
        area_notes[area] = area_payload.get("summary") or f"{area}: dati in consolidamento"

    most_unstable = max(area_scores.items(), key=lambda x: x[1])[0] if area_scores else "n/d"
    most_calm = min(area_scores.items(), key=lambda x: x[1])[0] if area_scores else "n/d"
    thermal_range = f"{round(min(all_temps), 1)}°C - {round(max(all_temps), 1)}°C" if all_temps else "n/d"
    tone = _time_of_day_label(_overview_now(payload))

    pages: list[tuple[str, str, str]] = [
        (
            "Overview Italia",
            (
                "🇮🇹 Situazione generale aggregata dalle aree monitorate.\n"
                f"🐹 Buona {tone}: il Barcellometro ha preso il microfono del meteo nazionale.\n"
                f"⚡ Area più instabile: **{most_unstable}**\n"
                f"🌤️ Area più serena: **{most_calm}**\n"
                f"🌡️ Range termico nazionale: **{thermal_range}**\n"
                "Clicca i pulsanti qui sotto per il dettaglio di ogni area."
            ),
            "Consiglio cricetoso: controlla il meteo prima di uscire e vesti a strati intelligenti.",
        )
    ]
    for region in ["Nord", "Centro", "Sud e Isole"]:
        area_payload = regions.get(region, {})
        area_payload = area_payload if isinstance(area_payload, dict) else {"sampled_cities": area_payload}
        entries = area_payload.get("sampled_cities", [])
        row = [f"🧾 {area_notes.get(region, region)}"]
        for entry in entries[:4]:
            row.append(
                f"**{entry.get('city', 'Città')}** · {entry.get('temperature', 'n/d')}°C · vento {entry.get('windspeed', 'n/d')} km/h · {entry.get('condition', 'condizioni variabili')}"
            )
        pages.append(
            (
                region,
                "\n".join(row) or "Dati non disponibili",
                f"🐹 Focus area: {area_payload.get('precipitation_summary', 'situazione in aggiornamento')} · {area_payload.get('wind_summary', 'vento in osservazione')}",
            )
        )
    embeds: list[discord.Embed] = []
    for page_title, description, comment in pages:
        page_intro = description[:1024] if page_title == "Overview Italia" else "Dettaglio meteo sintetico dell'area selezionata."
        e = discord.Embed(
            title=format_standard_title(f"{title} • {page_title}"),
            description=page_intro,
            color=color,
        )
        e.add_field(name=format_standard_field_name("Situazione", emoji="🧾"), value=description[:1024], inline=False)
        e.add_field(name=format_standard_field_name("Commento"), value=comment[:1024], inline=False)
        embeds.append(e)
    return _apply_campaign_footer(embeds, service_name="campagne_meteo")


def build_weather_page_map() -> list[dict[str, Any]]:
    return [
        {"type": "overview", "key": "overview", "label": "Overview Italia", "page": 0},
        {"type": "area", "key": "nord", "label": get_weather_area_label("Nord"), "page": 1},
        {"type": "area", "key": "centro", "label": get_weather_area_label("Centro"), "page": 2},
        {"type": "area", "key": "sud_e_isole", "label": get_weather_area_label("Sud e Isole"), "page": 3},
    ]


def build_horoscope_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
    title = config.get("embed_title") or "🔮 Oroscopo cricetoso"
    signs = payload.get("signs", {})
    scored: list[tuple[str, float]] = []
    for sign in SIGN_ORDER:
        sp = signs.get(sign, {})
        conf = float(sp.get("confidence") or 0.0)
        fallback_penalty = 0.5 if sp.get("fallback_used") else 0.0
        score = conf + (0.2 if "alta" in str(sp.get("energy", "")).lower() else 0) - fallback_penalty
        scored.append((sign, score))
    top = [name for name, _ in sorted(scored, key=lambda x: x[1], reverse=True)[:3]]
    delicate = [name for name, _ in sorted(scored, key=lambda x: x[1])[:3]]

    mood_parts = [str(signs.get(sign, {}).get("tone") or "") for sign in SIGN_ORDER if signs.get(sign)]
    mood = ", ".join(mood_parts[:4]) or "variegato"
    tone = _time_of_day_label(_overview_now(payload))

    embeds: list[discord.Embed] = []
    overview = discord.Embed(title=format_standard_title(f"{title} • Inizio"), color=color)
    overview.description = (
        f"🐹 Speciale oroscopo di **{tone}**: il Barcellometro ha lucidato le sfere e acceso lo studio stellare.\n"
        f"Clima zodiacale generale: **{mood}**.\n"
        f"Segni in forma: {', '.join(f'{SIGN_EMOJIS[s]} {s}' for s in top)}\n"
        f"Segni da trattare con più tatto: {', '.join(f'{SIGN_EMOJIS[s]} {s}' for s in delicate)}\n"
        "Per il dettaglio del tuo segno, clicca i pulsanti qui sotto."
    )
    embeds.append(overview)
    for sign in SIGN_ORDER:
        data = signs.get(sign, {})
        e = discord.Embed(title=format_standard_title(f"{title} • {sign}"), color=color)
        e.add_field(name=format_standard_field_name("Amore", emoji="❤️"), value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("love") or "Cuore in fase di analisi")), limit=280)[:1024], inline=False)
        e.add_field(name=format_standard_field_name("Lavoro / Studio", emoji="💼"), value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("work") or "Organizzati per priorità")), limit=280)[:1024], inline=False)
        e.add_field(name=format_standard_field_name("Soldi", emoji="💰"), value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("money") or "Gestione prudente")), limit=240)[:1024], inline=False)
        e.add_field(name=format_standard_field_name("Energia", emoji="⚡"), value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("energy") or "Energia variabile")), limit=220)[:1024], inline=False)
        e.add_field(name=format_standard_field_name("Con chi barcellerai oggi", emoji="🔥"), value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("friction") or "Con chi ti mette fretta")), limit=220)[:1024], inline=False)
        e.add_field(name=format_standard_field_name("Consiglio cricetoso", emoji="🐹"), value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("advice") or "Piccoli passi, grandi risultati")), limit=220)[:1024], inline=False)
        embeds.append(e)
    return _apply_campaign_footer(embeds, service_name="campagne_oroscopo")


def build_horoscope_page_map() -> list[dict[str, Any]]:
    page_map: list[dict[str, Any]] = [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]
    for i, sign in enumerate(SIGN_ORDER, start=1):
        page_map.append({"type": "sign", "key": slugify_label(sign), "label": f"{SIGN_EMOJIS.get(sign, '✨')} {sign.upper()}", "page": i})
    return page_map


def build_fallback_embed(config: dict[str, Any], sources: list[str], *, service_name: str = "campagne_notizie") -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
    title = config.get("embed_title") or "Servizio campagne"
    embed = discord.Embed(
        title=format_standard_title(title),
        description="Oggi il servizio non è riuscito a raccogliere contenuti affidabili.",
        color=color,
    )
    embed.add_field(name=format_standard_field_name("Fonti tentate"), value="\n".join(sources) or "n/d", inline=False)
    return _apply_campaign_footer([embed], service_name=service_name)
