from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

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
_NEWS_MAX_ITEMS_PER_FIELD = 2
_NEWS_FIELD_SOFT_LIMIT = 900
_NEWS_FIELD_HARD_LIMIT = 1024
_NEWS_MAX_CATEGORIES = 5
_NEWS_MAX_TOTAL_ITEMS = 10


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


def _build_news_category_field_value(items: list[dict[str, Any]], *, display: str) -> str:
    limited_items = items[:_NEWS_MAX_ITEMS_PER_FIELD]
    if not limited_items:
        return ""
    summary_limits = [320, 220, 170, 130, 100]
    for summary_limit in summary_limits:
        blocks = [
            _format_news_item_block(
                item,
                display=display,
                numbered=False,
                index=0,
                max_summary_chars=summary_limit,
            )
            for item in limited_items
        ]
        candidate = "\n\n".join(blocks)
        if len(candidate) <= _NEWS_FIELD_HARD_LIMIT:
            return candidate
    fallback = _format_news_item_block(
        limited_items[0],
        display=display,
        numbered=False,
        index=0,
        max_summary_chars=220,
    )
    return fallback[:_NEWS_FIELD_HARD_LIMIT]


def chunk_news_items_for_embed(items: list[dict[str, Any]], *, display: str) -> list[str]:
    blocks = [_format_news_item_block(item, display=display, numbered=True, index=idx) for idx, item in enumerate(items[:5], start=1)]
    if not blocks:
        return []
    chunks: list[str] = []
    current: list[str] = []
    for block in blocks:
        candidate = "\n\n".join([*current, block]) if current else block
        force_new_chunk = bool(current) and (
            len(current) >= _NEWS_MAX_ITEMS_PER_FIELD
            or len(candidate) > _NEWS_FIELD_SOFT_LIMIT
        )
        if force_new_chunk:
            chunks.append("\n\n".join(current))
            current = [block]
        else:
            current.append(block)
    if current:
        chunks.append("\n\n".join(current))

    sanitized_chunks: list[str] = []
    for chunk in chunks:
        if len(chunk) <= _NEWS_FIELD_HARD_LIMIT:
            sanitized_chunks.append(chunk)
            continue
        split_blocks = chunk.split("\n\n")
        rolling: list[str] = []
        for block in split_blocks:
            rolling_candidate = "\n\n".join([*rolling, block]) if rolling else block
            if rolling and len(rolling_candidate) > _NEWS_FIELD_HARD_LIMIT:
                sanitized_chunks.append("\n\n".join(rolling))
                rolling = [block]
            else:
                rolling.append(block)
        if rolling:
            sanitized_chunks.append("\n\n".join(rolling))
    return sanitized_chunks


def similarity_title(a: str, b: str) -> float:
    return SequenceMatcher(None, sanitize_plain_text(a).lower(), sanitize_plain_text(b).lower()).ratio()


def _time_of_day_label(dt: datetime) -> str:
    hour = dt.hour
    if 6 <= hour < 12:
        return "mattina"
    if 12 <= hour < 18:
        return "pomeriggio"
    if 18 <= hour < 23:
        return "sera"
    return "notte"


def _overview_now(payload: dict[str, Any]) -> datetime:
    raw = payload.get("generated_at") or payload.get("published_at") or payload.get("created_at")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
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


def _iter_news_categories(payload: dict[str, Any], *, max_categories: int = _NEWS_MAX_CATEGORIES) -> list[tuple[str, str, str, list[dict[str, Any]]]]:
    selected: list[tuple[str, str, str, list[dict[str, Any]]]] = []
    categories = payload.get("categories", {})
    if not isinstance(categories, dict):
        return selected
    configured = payload.get("configured_categories")
    configured_order = [str(category).strip().lower() for category in configured] if isinstance(configured, list) else []
    ordered_categories = list(categories.keys())
    if configured_order:
        known = {str(category).strip().lower(): category for category in ordered_categories}
        ordered_categories = [known[key] for key in configured_order if key in known]
    seen_story_keys: set[str] = set()
    total_selected_items = 0
    for category in ordered_categories:
        items = categories.get(category)
        valid_items = _valid_news_items(items)
        if not valid_items:
            continue
        display = get_category_display_name(str(category))
        if display.upper() in {"VARIE", "TITOLI IN EVIDENZA"}:
            continue
        category_items: list[dict[str, Any]] = []
        for item in valid_items:
            if len(category_items) >= _NEWS_MAX_ITEMS_PER_FIELD:
                break
            if total_selected_items >= _NEWS_MAX_TOTAL_ITEMS:
                break
            story_key = _normalized_story_identity(item)
            if not story_key or story_key in seen_story_keys:
                continue
            category_items.append(item)
            seen_story_keys.add(story_key)
            total_selected_items += 1
        if not category_items:
            continue
        emoji = get_category_emoji(str(category))
        selected.append((str(category), display, emoji, category_items))
        if len(selected) >= max_categories or total_selected_items >= _NEWS_MAX_TOTAL_ITEMS:
            break
    return selected


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
    embeds: list[discord.Embed] = []
    category_rows = _iter_news_categories(payload)
    overview = discord.Embed(title=format_standard_title(f"{title} • Panoramica"), color=color)
    tone = _time_of_day_label(_overview_now(payload))
    daypart = tone if tone in {"mattina", "pomeriggio", "sera"} else "sera"
    if category_rows:
        overview.description = format_standard_description(
            (
                f"🐹 Buona **{daypart}**: qui Barcellometro in regia, con la redazione più rumorosa del quartiere. "
                "Titoli caldi, pochi giri di parole e dritti al punto.\n"
                "**Che ci dice il mondo quest'oggi?**"
            ),
            blank_line_before_fields=True,
        )
    else:
        overview.description = format_standard_description(
            (
                f"🐹 Buona **{daypart}**: Barcellometro è in redazione, oggi è più calma ma il radar resta acceso. "
                "Se spunta qualcosa di succoso, noi ci siamo.\n"
                "**Che ci dice il mondo quest'oggi?**"
            ),
        )
    for _, display, emoji, items in category_rows:
        field_value = _build_news_category_field_value(items, display=display)
        if not field_value:
            continue
        overview.add_field(
            name=format_standard_field_name(display, emoji=emoji),
            value=field_value,
            inline=False,
        )
    first_image_url = _first_story_image_url(category_rows)
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
