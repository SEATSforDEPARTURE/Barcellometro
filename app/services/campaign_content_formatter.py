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


def _valid_news_items(items: Any) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return valid
    for item in items:
        if not isinstance(item, dict):
            continue
        title = sanitize_plain_text(str(item.get("title") or ""))
        if title:
            valid.append(item)
    return valid


def _normalized_story_identity(item: dict[str, Any]) -> str:
    link = str(item.get("link") or "").strip().lower().rstrip("/")
    if link:
        return f"url:{link}"
    title = sanitize_plain_text(str(item.get("title") or "")).lower()
    if title:
        return f"title:{title}"
    return ""


def _parse_news_datetime(raw: Any) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _news_item_sort_key(item: dict[str, Any]) -> tuple[float, float]:
    published = _parse_news_datetime(item.get("published_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
    quality = len(sanitize_plain_text(str(item.get("title") or ""))) + len(_build_news_item_summary(item, display=""))
    return (published.timestamp(), float(quality))


def _score_news_item(item: dict[str, Any], *, now_utc: datetime) -> float:
    title = sanitize_plain_text(str(item.get("title") or ""))
    summary = _build_news_item_summary(item, display="")
    source = str(item.get("source") or "").lower()
    published = _parse_news_datetime(item.get("published_at"))
    age_hours = 72.0
    if published is not None:
        age_hours = max(0.0, (now_utc - published.astimezone(timezone.utc)).total_seconds() / 3600.0)
    recency_score = max(0.0, 40.0 - min(age_hours, 40.0))
    title_quality = min(len(title), 120) / 4.0
    summary_quality = min(len(summary), 220) / 8.0
    reliability = 6.0 if any(token in source for token in ["ansa", "repubblica", "corriere", "ilpost"]) else 0.0
    return recency_score + title_quality + summary_quality + reliability


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


def _iter_all_news_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    categories = payload.get("categories", {})
    if not isinstance(categories, dict):
        return []
    merged: list[dict[str, Any]] = []
    for items in categories.values():
        merged.extend(_valid_news_items(items))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(merged, key=_news_item_sort_key, reverse=True):
        key = _normalized_story_identity(item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _select_editorial_categories(
    payload: dict[str, Any],
    *,
    excluded_story_keys: set[str],
) -> list[tuple[str, str, str, dict[str, Any]]]:
    selected: list[tuple[str, str, str, dict[str, Any]]] = []
    categories = payload.get("categories", {})
    if not isinstance(categories, dict):
        return selected
    configured = payload.get("configured_categories")
    configured_order = [str(category).strip().lower() for category in configured] if isinstance(configured, list) else []
    if not configured_order:
        configured_order = [str(cat).strip().lower() for cat in categories.keys()]
    available = {str(category).strip().lower(): category for category in categories.keys()}
    for configured_category in configured_order:
        mapped_category = available.get(configured_category)
        if mapped_category is None:
            continue
        valid_items = sorted(_valid_news_items(categories.get(mapped_category)), key=_news_item_sort_key, reverse=True)
        chosen_item: dict[str, Any] | None = None
        for item in valid_items:
            key = _normalized_story_identity(item)
            if not key or key in excluded_story_keys:
                continue
            chosen_item = item
            excluded_story_keys.add(key)
            break
        if chosen_item is None:
            continue
        display = get_category_display_name(mapped_category)
        selected.append((mapped_category, display, get_category_emoji(mapped_category), chosen_item))
        if len(selected) >= _NEWS_MAX_EDITORIAL_CATEGORIES:
            break
    return selected


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
    title = "📰 HAMSTER NEWS"
    now_utc = _overview_now(payload)
    edition_label, daypart = news_edition_label_for_datetime(now_utc)
    overview = discord.Embed(title=format_standard_title(f"{title} • {edition_label}"), color=color)
    overview.description = format_standard_description(
        (
            f"🐹 Buona **{daypart}**: qui Barcellometro in regia, con la redazione più rumorosa del quartiere. "
            "Titoli caldi, pochi giri di parole e dritti al punto.\n"
            "**Che ci dice il mondo quest'oggi?**"
        ),
        blank_line_before_fields=True,
    )
    all_items = _iter_all_news_items(payload)
    excluded_keys: set[str] = set()
    latest_item = all_items[0] if all_items else None
    if latest_item is not None:
        latest_key = _normalized_story_identity(latest_item)
        if latest_key:
            excluded_keys.add(latest_key)
        overview.add_field(
            name=format_standard_field_name("ULTIM'ORA", emoji="⚡"),
            value=_build_single_news_field_value(latest_item, display="ULTIM'ORA"),
            inline=False,
        )
    highlighted: dict[str, Any] | None = None
    for item in sorted(all_items, key=lambda candidate: _score_news_item(candidate, now_utc=now_utc), reverse=True):
        item_key = _normalized_story_identity(item)
        if not item_key or item_key in excluded_keys:
            continue
        highlighted = item
        excluded_keys.add(item_key)
        break
    if highlighted is not None:
        overview.add_field(
            name=format_standard_field_name("IN EVIDENZA", emoji="🌟"),
            value=_build_single_news_field_value(highlighted, display="IN EVIDENZA"),
            inline=False,
        )
    editorial_categories = _select_editorial_categories(payload, excluded_story_keys=excluded_keys)
    for _, display, _, item in editorial_categories:
        overview.add_field(
            name=format_standard_field_name(f"{display} IN PRIMO PIANO"),
            value=_build_single_news_field_value(item, display=display),
            inline=False,
        )
    extras_enabled = _normalize_news_extras(config.get("extras_json"))
    for extra in NEWS_EXTRA_ORDER:
        if extra not in extras_enabled:
            continue
        title_text, emoji = NEWS_EXTRA_FIELD_TITLES[extra]
        content = _daily_rotating_pick(NEWS_EXTRA_CATALOG[extra], base_dt=now_utc)
        if not content:
            continue
        overview.add_field(
            name=format_standard_field_name(title_text, emoji=emoji),
            value=content[:_NEWS_FIELD_HARD_LIMIT],
            inline=False,
        )
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
