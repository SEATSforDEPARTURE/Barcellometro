from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import discord
from app.services.author import attach_author_meta_to_all
from app.services.embed_images import attach_embed_images_meta
from app.services.footer import attach_footer_meta_to_all
from app.shared.discord.embed_limits import (
    DISCORD_MAX_EMBED_TOTAL_CHARS,
    compute_embed_text_size,
    split_markdown_lines_into_field_values,
)
from app.shared.discord.embed_body import format_standard_description, format_standard_field_name, format_standard_title

DEFAULT_COLOR = 0x2F3136
logger = logging.getLogger(__name__)


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
    "cronaca": "🕵️",
    "politica": "🏛️",
    "sport": "⚽",
    "spettacolo": "🎭",
    "gossip": "👀",
    "tecnologia": "💻",
    "tech": "💻",
    "economia": "💼",
    "mondo": "🌍",
    "viral": "📈",
    "trash": "🗑️",
    "curiosita": "🤔",
    "curiosità": "🤔",
    "varie": "🗂️",
}

WEATHER_AREA_LABELS = {
    "nord": "🧊 NORD",
    "centro": "🏛️ CENTRO",
    "sud": "🌋 SUD",
    "isole": "🏝️ ISOLE",
}

HOROSCOPE_SECTIONS = ["horoscope"]
WEATHER_AREAS = ["nord", "centro", "sud", "isole"]
_SOURCE_TECHNICAL_LABELS = {"www", "xml", "xml2", "api", "rss", "feed"}
_COMMON_TLDS = {"com", "it", "org", "net", "online", "news", "eu", "io", "tv", "co", "uk"}


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


def _clone_embed_without_fields(embed: discord.Embed, *, include_description: bool) -> discord.Embed:
    payload = embed.to_dict()
    payload.pop("fields", None)
    if not include_description:
        payload.pop("description", None)
    return discord.Embed.from_dict(payload)


def _split_field_value_to_fit_budget(value: str, *, budget: int) -> list[str]:
    hard_limit = max(1, min(1024, budget))
    return split_markdown_lines_into_field_values(
        str(value or "").splitlines() or [str(value or "")],
        limit=hard_limit,
        continuation_prefix="",
    )


def enforce_embed_size_limit(embeds: list[discord.Embed]) -> list[discord.Embed]:
    bounded: list[discord.Embed] = []
    for embed_index, embed in enumerate(embeds):
        if compute_embed_text_size(embed) <= DISCORD_MAX_EMBED_TOTAL_CHARS:
            bounded.append(embed)
            continue

        logger.debug(
            "campaign content: enforce_embed_size_limit split start embed_index=%s size=%s fields=%s",
            embed_index,
            compute_embed_text_size(embed),
            len(embed.fields),
        )
        current = _clone_embed_without_fields(embed, include_description=True)
        if compute_embed_text_size(current) > DISCORD_MAX_EMBED_TOTAL_CHARS and current.description:
            without_description = _clone_embed_without_fields(embed, include_description=False)
            current.description = (current.description or "")[: max(1, DISCORD_MAX_EMBED_TOTAL_CHARS - compute_embed_text_size(without_description))]
        has_content = bool(current.description)

        for raw_field in embed.fields:
            base_name = str(raw_field.name or "—")
            raw_chunks = _split_field_value_to_fit_budget(str(raw_field.value or "—"), budget=1024)
            for chunk_index, raw_chunk in enumerate(raw_chunks):
                field_name = base_name if chunk_index == 0 else f"{base_name} (cont.)"
                pending_chunks = [raw_chunk or "—"]
                while pending_chunks:
                    field_value = pending_chunks.pop(0)
                    projected_size = compute_embed_text_size(current) + len(field_name) + len(field_value)
                    if len(current.fields) >= 25 or projected_size > DISCORD_MAX_EMBED_TOTAL_CHARS:
                        if has_content:
                            bounded.append(current)
                        current = _clone_embed_without_fields(embed, include_description=False)
                        has_content = False
                        available_budget = max(1, DISCORD_MAX_EMBED_TOTAL_CHARS - compute_embed_text_size(current) - len(field_name))
                        split_chunks = _split_field_value_to_fit_budget(field_value, budget=available_budget)
                        pending_chunks = split_chunks + pending_chunks
                        continue
                    current.add_field(name=field_name, value=field_value, inline=raw_field.inline)
                    has_content = True

        if has_content:
            bounded.append(current)

    return bounded


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
    cleaned = re.sub(rf"(?i)^\s*{re.escape(sign)}\b[\s,:;\-–|]*", "", cleaned)
    cleaned = re.sub(rf"(?i)\b{re.escape(sign)}\b(?=[\s,:;\-–|]+(?:oggi|ora|adesso|qui)\b)", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def extract_main_name(source: str) -> str:
    token = str(source or "").strip().lower()
    if not token:
        return ""
    parsed = urlparse(token)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        token = parsed.netloc.lower()
    token = token.split("/", 1)[0].split(":", 1)[0]
    labels = [part.strip() for part in token.split(".") if part.strip()]
    filtered = [part for part in labels if part not in _SOURCE_TECHNICAL_LABELS]
    if len(filtered) > 1 and filtered[-1] in _COMMON_TLDS:
        filtered = filtered[:-1]
    candidate = filtered[0] if filtered else (labels[0] if labels else token)
    if candidate.endswith("objects") and len(candidate) > len("objects"):
        candidate = candidate[: -len("objects")]
    return candidate.strip("-_ ")


def _title_case_source_name(name: str) -> str:
    chunks = [part for part in str(name or "").split("-") if part]
    if not chunks:
        return ""
    return "-".join(part[:1].upper() + part[1:].lower() for part in chunks)


def format_source_label(source: str, source_type: str) -> str:
    main_name = extract_main_name(source)
    if not main_name:
        return ""
    kind = "RSS" if str(source_type or "").lower() == "rss" else "API"
    return f"{_title_case_source_name(main_name)} {kind}"


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
_NEWS_FIELD_HARD_LIMIT = 1024
_ITALY_TZ = ZoneInfo("Europe/Rome")
NEWS_EXTRA_ORDER = ["barzelletta", "aforisma", "canzone", "meme"]
NEWS_EXTRA_FIELD_TITLES = {
    "barzelletta": ("😂 BARZELLETTA DEL GIORNO", "😂"),
    "aforisma": ("🧠 AFORISMA DEL GIORNO", "🧠"),
    "canzone": ("🎵 CANZONE DEL GIORNO", "🎵"),
    "meme": ("🖼️ MEME DEL GIORNO", "🖼️"),
}
NEWS_EXTRA_CATALOG = {
    "barzelletta": ["Il criceto in redazione: «Promesso, oggi apro solo tre tab». Erano trenta."],
    "aforisma": ["La notizia corre, il criterio decide la direzione."],
    "canzone": ["Heroes — David Bowie\nEnergia da prima pagina per la ruota della redazione."],
    "meme": ["Quando dici «chiudo in 5 minuti» e la breaking spunta al minuto 6."],
}
NEWS_DAYPART_GREETING = {
    "mattina": "Buongiorno",
    "pomeriggio": "Buon pomeriggio",
    "sera": "Buona sera",
    "notte": "Buonanotte",
}
_IMPORTANT_PLATFORM_TERMS = (
    "Netflix",
    "YouTube",
    "Amazon",
    "Prime Video",
    "Disney+",
    "Apple TV+",
    "HBO",
    "Sky",
    "TikTok",
    "Instagram",
    "X",
    "Facebook",
    "Spotify",
    "Twitch",
)
_IMPORTANT_PHRASES = (
    "mix catastrofico",
    "squali assassini",
    "impatto devastante",
    "svolta storica",
    "crisi profonda",
    "allarme rosso",
    "colpo di scena",
    "tensione alle stelle",
    "record assoluto",
)
_NEWS_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]",
    flags=re.UNICODE,
)
_NEWS_DELICATE_KEYWORDS = (
    "morto",
    "morti",
    "morte",
    "deceduto",
    "deceduta",
    "ucciso",
    "uccisa",
    "omicidio",
    "ferito grave",
    "feriti gravi",
    "vittime",
    "tragedia",
    "incidente",
    "incidente grave",
    "esplos",
    "sparatoria",
    "guerra",
    "bombard",
    "attacco",
    "alluvione",
    "terremoto",
    "femminicidio",
    "minore",
    "minori",
    "aggressione",
    "violenza",
)
_STANDARD_NEWS_FINAL_EMOJIS = ("👀", "🤹", "📈", "⚡", "🎭")
_SERIOUS_NEWS_FINAL_EMOJIS = ("😔", "🫥")
_CATEGORY_MATCH_KEYWORDS = {
    "tecnologia": (
        "ai", "intelligenza artificiale", "software", "hardware", "app", "chip", "startup tech",
        "startup", "cybersecurity", "piattaforma", "piattaforme", "device", "internet", "robotica",
        "cloud", "algoritmo", "digitale", "open source",
    ),
    "economia": (
        "mercati", "pil", "inflazione", "fmi", "banche", "debito", "dazi", "crescita", "consumi",
        "lavoro", "borsa", "spread", "macroeconom", "finanza", "economia",
    ),
    "politica": (
        "governo", "parlamento", "senato", "camera", "partiti", "premier", "ministro", "legge",
        "opposizione", "decreto", "maggioranza", "riforma",
    ),
    "cronaca": (
        "incidente", "tribunale", "omicidio", "aggressione", "sequestro", "indagini", "carabinieri",
        "polizia", "procura", "arresto", "ferito", "vittima",
    ),
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


def extract_first_sentences(text: str, max_sentences: int = 1) -> str:
    """
    Normalize HTML/text and return at most the first N complete sentences.
    Never cut a sentence in the middle.
    """
    if max_sentences <= 0:
        return ""
    candidate = sanitize_public_news_text(text)
    if not candidate:
        return ""
    sentence_pattern = re.compile(r'[^.!?]*[.!?](?:["”’»)\]]+)?', flags=re.UNICODE)
    picked: list[str] = [match.group(0).strip() for match in sentence_pattern.finditer(candidate) if match.group(0).strip()]
    if not picked:
        return candidate
    if len(picked) >= max_sentences:
        return " ".join(picked[:max_sentences]).strip()
    consumed = sum(len(match.group(0)) for match in sentence_pattern.finditer(candidate))
    tail = candidate[consumed:].strip()
    if tail:
        picked.append(tail)
    return " ".join(picked[:max_sentences]).strip()


def _first_real_news_sentences(item: dict[str, Any]) -> str:
    for key in ("description", "excerpt", "content", "text"):
        candidate = sanitize_public_news_text(str(item.get(key) or ""))
        if _is_useless_news_text(candidate):
            continue
        return extract_first_sentences(candidate, max_sentences=1)
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


def _build_news_item_summary(
    item: dict[str, Any],
    *,
    display: str,
    used_emojis: set[str] | None = None,
    seed_key: str | None = None,
) -> str:
    ai_summary = sanitize_public_news_text(str(item.get("ai_summary") or ""))
    if not _is_useless_news_text(ai_summary):
        return _normalize_news_summary_for_embed(
            ai_summary,
            item=item,
            display=display,
            used_emojis=used_emojis,
            seed_key=seed_key,
        )
    summary = sanitize_public_news_text(str(item.get("summary") or ""))
    summary = sanitize_plain_text(summary, remove_category_hint=display)
    if _is_useless_news_text(summary):
        return _normalize_news_summary_for_embed(
            _first_real_news_sentences(item),
            item=item,
            display=display,
            used_emojis=used_emojis,
            seed_key=seed_key,
        )
    return _normalize_news_summary_for_embed(
        summary,
        item=item,
        display=display,
        used_emojis=used_emojis,
        seed_key=seed_key,
    )


def _news_summary_contains_emoji(text: str) -> bool:
    return bool(_NEWS_EMOJI_RE.search(text or ""))


def _classify_news_tone(item: dict[str, Any], *, display: str) -> str:
    blob = " ".join(
        sanitize_public_news_text(str(item.get(key) or ""))
        for key in ("title", "summary", "description", "content", "category")
    )
    blob = f"{blob} {display}".lower()
    if any(token in blob for token in _NEWS_DELICATE_KEYWORDS):
        return "serious"
    return "standard"


def _build_news_final_emoji(*, tone: str, item: dict[str, Any]) -> str:
    palette = _SERIOUS_NEWS_FINAL_EMOJIS if tone == "serious" else _STANDARD_NEWS_FINAL_EMOJIS
    key = _news_identity(item) or sanitize_plain_text(str(item.get("title") or "")).lower() or "news"
    idx = abs(hash(key)) % len(palette)
    return palette[idx]


def _pick_news_final_emoji(tone: str, used_comments: set[str], seed_key: str | None = None) -> str:
    palette = _SERIOUS_NEWS_FINAL_EMOJIS if tone == "serious" else _STANDARD_NEWS_FINAL_EMOJIS
    key = sanitize_plain_text(seed_key or "").lower() or tone
    start_idx = abs(hash(key)) % len(palette)
    for offset in range(len(palette)):
        candidate = palette[(start_idx + offset) % len(palette)]
        if candidate not in used_comments:
            used_comments.add(candidate)
            return candidate
    fallback = palette[start_idx]
    used_comments.add(fallback)
    return fallback


def _starts_with_emoji(text: str) -> bool:
    first = re.search(r"\S+", text or "")
    if not first:
        return False
    return _news_summary_contains_emoji(first.group(0))


def _starts_with_bot_comment(text: str) -> bool:
    lowered = sanitize_public_news_text(text).lower().lstrip(" -:;,.")
    return lowered.startswith(
        (
            "qui la faccenda",
            "qui si parla",
            "in pratica",
            "attenzione",
            "notizia pesante",
            "clima teso",
        )
    )


def _build_news_summary_body(raw_summary: str, *, item: dict[str, Any], display: str, tone: str) -> str:
    _ = (display, tone)
    cleaned = sanitize_public_news_text(raw_summary)
    if not cleaned:
        cleaned = "Dettagli in aggiornamento."
    cleaned = re.sub(r"^\s*[:\-–|]+\s*", "", cleaned).strip()
    while _starts_with_emoji(cleaned):
        cleaned = re.sub(r"^\s*\S+\s*", "", cleaned).strip()
    if _starts_with_bot_comment(cleaned):
        cleaned = re.sub(
            r"(?i)^(?:qui la faccenda|qui si parla di|in pratica|attenzione|notizia pesante|clima teso)[^:.\-]*[:.\-]?\s*",
            "",
            cleaned,
        ).strip()
    source_hint = sanitize_public_news_text(str(item.get("summary") or ""))
    if source_hint and SequenceMatcher(None, cleaned.lower(), source_hint.lower()).ratio() >= 0.9:
        cleaned = cleaned[0].lower() + cleaned[1:] if len(cleaned) > 1 else cleaned.lower()
    cleaned = _NEWS_EMOJI_RE.sub("", sanitize_public_news_text(cleaned)).strip()
    if not cleaned:
        cleaned = "Dettagli in aggiornamento."
    cleaned = extract_first_sentences(cleaned, max_sentences=1).strip()
    if not re.search(r"[.!?]\s*$", cleaned):
        cleaned = f"{cleaned}."
    return cleaned


def _compose_news_embed_summary(body: str, final_emoji: str) -> str:
    body_clean = sanitize_public_news_text(body)
    tail = sanitize_public_news_text(final_emoji)
    if not body_clean:
        body_clean = "Dettagli in aggiornamento."
    if not tail:
        tail = _STANDARD_NEWS_FINAL_EMOJIS[0]
    if not re.search(r"[.!?]\s*$", body_clean):
        body_clean = f"{body_clean}."
    body_clean = _NEWS_EMOJI_RE.sub("", body_clean).strip()
    return f"{body_clean} {tail}".strip()


def _normalize_news_summary_for_embed(
    raw_summary: str,
    *,
    item: dict[str, Any],
    display: str,
    used_emojis: set[str] | None = None,
    seed_key: str | None = None,
) -> str:
    tone = _classify_news_tone(item, display=display)
    body = _build_news_summary_body(raw_summary, item=item, display=display, tone=tone)
    if used_emojis is None:
        tail = _build_news_final_emoji(tone=tone, item=item)
    else:
        tail = _pick_news_final_emoji(
            tone,
            used_emojis,
            seed_key=seed_key or _news_identity(item) or sanitize_plain_text(str(item.get("title") or "")),
        )
    logger.info("news_summary_emoji_applied tone=%s title=%s emoji=%s", tone, sanitize_plain_text(str(item.get("title") or ""))[:80], tail[:80])
    return _compose_news_embed_summary(body, tail)


def highlight_key_terms(text: str) -> str:
    cleaned = sanitize_public_news_text(text)
    if not cleaned:
        return ""
    highlights: list[tuple[int, int]] = []

    def _add_span(start: int, end: int) -> None:
        if start >= end:
            return
        for span_start, span_end in highlights:
            if not (end <= span_start or start >= span_end):
                return
        highlights.append((start, end))

    for platform in _IMPORTANT_PLATFORM_TERMS:
        for match in re.finditer(rf"\b{re.escape(platform)}\b", cleaned):
            _add_span(match.start(), match.end())

    for phrase in _IMPORTANT_PHRASES:
        for match in re.finditer(rf"\b{re.escape(phrase)}\b", cleaned, flags=re.IGNORECASE):
            _add_span(match.start(), match.end())

    skip_first_words = {"Il", "Lo", "La", "I", "Gli", "Le", "Un", "Una"}
    for match in re.finditer(r"\b([A-Z][a-z]+) ([A-Z][a-z]+)\b", cleaned):
        if match.group(1) in skip_first_words:
            continue
        _add_span(match.start(), match.end())

    highlights = sorted(highlights, key=lambda span: (span[0], -(span[1] - span[0])))[:4]
    if not highlights:
        return cleaned
    rendered: list[str] = []
    cursor = 0
    for start, end in highlights:
        rendered.append(cleaned[cursor:start])
        rendered.append(f"**{cleaned[start:end]}**")
        cursor = end
    rendered.append(cleaned[cursor:])
    return "".join(rendered)


def _format_news_item_block(
    item: dict[str, Any],
    *,
    display: str,
    numbered: bool,
    index: int,
    used_emojis: set[str] | None = None,
    seed_key: str | None = None,
) -> str:
    link = str(item.get("link") or "").strip()
    title_line = sanitize_plain_text(str(item.get("title") or "Titolo non disponibile"))
    linked_title = f"[{title_line}]({link})" if link else title_line
    summary = _build_news_item_summary(item, display=display, used_emojis=used_emojis, seed_key=seed_key)
    heading = f"• {index}. **{linked_title}**" if numbered else f"• **{linked_title}**"
    source_line = _news_source_line(item, link=link)
    return _fit_news_field_value(heading=heading, summary=summary, source_line=source_line)


def _fit_news_field_value(*, heading: str, summary: str, source_line: str) -> str:
    composed = f"{heading}\n{summary}\n`fonte: {source_line}`"
    if len(composed) <= _NEWS_FIELD_HARD_LIMIT:
        return composed
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", summary) if part.strip()]
    while len(sentences) > 1:
        sentences.pop()
        candidate_summary = " ".join(sentences).strip()
        candidate = f"{heading}\n{candidate_summary}\n`fonte: {source_line}`"
        if len(candidate) <= _NEWS_FIELD_HARD_LIMIT:
            return candidate
    one_sentence = sentences[0] if sentences else summary
    candidate = f"{heading}\n{one_sentence}\n`fonte: {source_line}`"
    if len(candidate) <= _NEWS_FIELD_HARD_LIMIT:
        return candidate
    # Extreme safeguard: preserve structure without cutting a sentence mid-stream.
    return f"{heading}\nDettagli disponibili al link. 👀\n`fonte: {source_line}`"


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
    normalized_link = _normalize_news_url(str(item.get("link") or ""))
    if normalized_link:
        return f"url:{normalized_link}"
    title = " ".join(sanitize_plain_text(str(item.get("title") or "")).lower().split())
    source = _normalize_news_source(str(item.get("source") or ""))
    if title and source:
        return f"title_source:{title}|{source}"
    if title:
        return f"title:{title}"
    return ""


def _normalize_news_source(raw_source: str) -> str:
    source = sanitize_public_news_text(raw_source).lower().strip()
    if source.startswith(("http://", "https://")):
        parsed = urlparse(source)
        source = parsed.netloc or source
    return source.removeprefix("www.").strip("/")


def _normalize_news_url(raw_url: str) -> str:
    candidate = str(raw_url or "").strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if not parsed.scheme or not parsed.netloc:
        return candidate.lower().rstrip("/")
    filtered_query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=parsed.path.rstrip("/"),
        params="",
        query=urlencode(filtered_query, doseq=True),
        fragment="",
    )
    return urlunparse(normalized).rstrip("/")


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
    return _build_single_news_field_value_with_emoji_tracking(item=item, display=display, used_emojis=None, seed_key=None)


def _build_single_news_field_value_with_emoji_tracking(
    item: dict[str, Any],
    *,
    display: str,
    used_emojis: set[str] | None,
    seed_key: str | None,
) -> str:
    return _format_news_item_block(
        item,
        display=display,
        numbered=False,
        index=0,
        used_emojis=used_emojis,
        seed_key=seed_key,
    )


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
    selected: list[str] = []
    seen: set[str] = set()
    for category in ordered:
        key = category.lower()
        if key in seen:
            continue
        seen.add(key)
        selected.append(category)
    return selected


def _campaign_debug_id(payload: dict[str, Any]) -> Any:
    campaign_id = payload.get("campaign_id")
    if campaign_id is not None:
        return campaign_id
    return payload.get("id")


def _tokenize_news_blob(item: dict[str, Any]) -> str:
    chunks = [
        sanitize_public_news_text(str(item.get("title") or "")),
        sanitize_public_news_text(str(item.get("summary") or "")),
        sanitize_public_news_text(str(item.get("description") or "")),
        sanitize_public_news_text(str(item.get("content") or "")),
    ]
    normalized = " ".join(chunks).lower()
    normalized = re.sub(r"[^a-zàèéìòù0-9\s']", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_keyword_blob(blob: str, keyword: str) -> bool:
    needle = sanitize_public_news_text(keyword).lower().strip()
    if not needle:
        return False
    return re.search(rf"\b{re.escape(needle)}\b", blob) is not None


def _is_known_news_category(category: str) -> bool:
    normalized = slugify_label(category).replace("_", " ")
    return normalized in _CATEGORY_MATCH_KEYWORDS


def _category_keyword_hits(blob: str, category: str) -> int:
    normalized = slugify_label(category).replace("_", " ")
    keywords = _CATEGORY_MATCH_KEYWORDS.get(normalized, ())
    return sum(1 for keyword in keywords if _contains_keyword_blob(blob, keyword))


def _score_item_category_match(item: dict[str, Any], category: str) -> float:
    requested = slugify_label(category).replace("_", " ")
    blob = _tokenize_news_blob(item)
    if not blob:
        return 0.0
    score = 1.0  # candidate comes from the requested bucket
    assigned = slugify_label(str(item.get("category") or "")).replace("_", " ")
    if assigned == requested:
        score += 1.2
    classified = item.get("classified_categories")
    if isinstance(classified, list):
        normalized_classified = {slugify_label(str(value)).replace("_", " ") for value in classified}
        if requested in normalized_classified:
            score += 1.0
    raw_categories = item.get("raw_categories")
    if isinstance(raw_categories, list):
        for raw in raw_categories:
            normalized_raw = sanitize_public_news_text(str(raw)).lower()
            if requested in normalized_raw:
                score += 1.0
                break
    keywords = _CATEGORY_MATCH_KEYWORDS.get(requested, ())
    for keyword in keywords:
        if _contains_keyword_blob(blob, keyword):
            score += 1.1
    # Penalize when another category has much stronger lexical evidence.
    competing_scores: list[float] = []
    for other_category, other_keywords in _CATEGORY_MATCH_KEYWORDS.items():
        if other_category == requested:
            continue
        other_score = 0.0
        for keyword in other_keywords:
            if _contains_keyword_blob(blob, keyword):
                other_score += 1.1
        competing_scores.append(other_score)
    strongest_other = max(competing_scores, default=0.0)
    if strongest_other > score:
        score -= min(2.5, strongest_other - score)
    return round(score, 3)


def _item_matches_requested_category(item: dict[str, Any], category: str, *, strict: bool = False) -> bool:
    requested = slugify_label(category).replace("_", " ")
    if strict:
        score = _score_item_category_match(item, requested)
        return score >= 2.0
    if not _is_known_news_category(requested):
        # For custom/synthetic categories we trust the payload bucket as source-of-truth.
        return True
    blob = _tokenize_news_blob(item)
    requested_hits = _category_keyword_hits(blob, requested)
    strongest_other_hits = 0
    strongest_other_category = ""
    for other_category in _CATEGORY_MATCH_KEYWORDS:
        if other_category == requested:
            continue
        hits = _category_keyword_hits(blob, other_category)
        if hits > strongest_other_hits:
            strongest_other_hits = hits
            strongest_other_category = other_category
    # Soft matching: accept bucket items by default, reject only clear lexical mismatches.
    if strongest_other_hits >= 2 and strongest_other_hits >= requested_hits + 2:
        assigned = slugify_label(str(item.get("category") or "")).replace("_", " ")
        if assigned and assigned not in (requested, strongest_other_category):
            return True
        return False
    score = _score_item_category_match(item, requested)
    return score >= 0.5


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
    category: str,
    used_ids: set[str],
    priority_used_ids: set[str] | None = None,
) -> tuple[dict[str, Any] | None, str, int]:
    candidates = _valid_news_items(category_items)
    if not candidates:
        return None, "no_valid_items", 0
    saw_priority_duplicate = False
    saw_editorial_duplicate = False
    for item in candidates:
        key = _news_identity(item)
        if not key:
            continue
        if key in used_ids:
            if key in (priority_used_ids or set()):
                saw_priority_duplicate = True
            else:
                saw_editorial_duplicate = True
            continue
        if not _item_matches_requested_category(item, category):
            continue
        return item, "selected", len(candidates)
    if saw_priority_duplicate and not saw_editorial_duplicate and len(candidates) == 1:
        return None, "already_used_by_priority_slot", len(candidates)
    if saw_editorial_duplicate and not saw_priority_duplicate and len(candidates) == 1:
        return None, "duplicate_of_existing_slot", len(candidates)
    if saw_priority_duplicate or saw_editorial_duplicate:
        return None, "no_valid_unused_items", len(candidates)
    return None, "selection_returned_none", len(candidates)


def select_final_news_slots(payload: dict[str, Any]) -> list[dict[str, Any]]:
    all_items = _collect_deduped_news_pool(payload)
    identity_counts = _collect_news_identity_counts(payload) or _news_identity_counts(all_items)
    discouraged_featured_ids = _first_editorial_story_ids(payload)
    selected_slots: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    latest_item = _select_breaking_news_item(all_items, identity_counts=identity_counts)
    if latest_item is not None:
        latest_key = _news_identity(latest_item)
        if latest_key:
            used_ids.add(latest_key)
        selected_slots.append({"slot": "ultimora", "display": "ULTIM'ORA", "emoji": "⚡", "item": latest_item})

    highlighted = _select_featured_news_item(
        all_items,
        used_ids=used_ids,
        now_utc=_overview_now(payload),
        identity_counts=identity_counts,
        discouraged_ids=discouraged_featured_ids,
    )
    if highlighted is not None:
        highlighted_key = _news_identity(highlighted)
        if highlighted_key:
            used_ids.add(highlighted_key)
        selected_slots.append({"slot": "featured", "display": "IN EVIDENZA", "emoji": "🌟", "item": highlighted})
    priority_used_ids = set(used_ids)

    categories = payload.get("categories", {})
    if isinstance(categories, dict):
        normalized_available = {str(category).strip().lower(): str(category) for category in categories.keys()}
        campaign_id = _campaign_debug_id(payload)
        for category in _iter_configured_editorial_categories(payload):
            normalized_category = str(category).strip().lower()
            if not normalized_category:
                logger.debug(
                    "campaign_news editorial category skip: campaign_id=%s category=%s reason=empty_category_key candidates=0",
                    campaign_id,
                    category,
                )
                continue
            mapped = normalized_available.get(normalized_category)
            if mapped is None:
                logger.debug(
                    "campaign_news editorial category skip: campaign_id=%s category=%s reason=no_bucket_for_category candidates=0",
                    campaign_id,
                    category,
                )
                continue
            category_items = categories.get(mapped)
            if not isinstance(category_items, list) or not category_items:
                logger.debug(
                    "campaign_news editorial category skip: campaign_id=%s category=%s reason=no_items_in_bucket candidates=0",
                    campaign_id,
                    mapped,
                )
                continue
            selected_item, reason, candidates = _select_editorial_category_item(
                category_items,
                category=mapped,
                used_ids=used_ids,
                priority_used_ids=priority_used_ids,
            )
            if selected_item is None:
                logger.debug(
                    "campaign_news editorial category skip: campaign_id=%s category=%s reason=%s candidates=%s",
                    campaign_id,
                    mapped,
                    reason or "selection_returned_none",
                    candidates,
                )
                continue
            story_id = _news_identity(selected_item)
            if story_id:
                used_ids.add(story_id)
            display = get_category_display_name(mapped)
            logger.debug(
                "campaign_news editorial category selected: campaign_id=%s category=%s item_id=%s",
                campaign_id,
                mapped,
                story_id or "unknown",
            )
            selected_slots.append(
                {
                    "slot": "category",
                    "category": mapped,
                    "display": display,
                    "emoji": get_category_emoji(mapped),
                    "item": selected_item,
                }
            )
    return selected_slots


def _build_news_extra_fields(config: dict[str, Any], *, base_dt: datetime) -> list[tuple[str, str]]:
    extras_enabled = _normalize_news_extras(config.get("extras_json"))
    extras_payload = config.get("extras_payload")
    live_extras = extras_payload if isinstance(extras_payload, dict) else {}
    fields: list[tuple[str, str]] = []
    for extra in NEWS_EXTRA_ORDER:
        if extra not in extras_enabled:
            continue
        title_text, emoji = NEWS_EXTRA_FIELD_TITLES[extra]
        content = sanitize_plain_text(str(live_extras.get(extra) or ""))
        if not content:
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
    normalized_available = {str(category).strip().lower(): str(category) for category in categories.keys()}
    for category in _iter_configured_editorial_categories(payload):
        normalized_category = str(category).strip().lower()
        if not normalized_category:
            continue
        mapped = normalized_available.get(normalized_category)
        if mapped is None:
            continue
        first_item, _reason, _candidates = _select_editorial_category_item(
            categories.get(mapped),
            category=mapped,
            used_ids=set(),
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
    _ = generated_at
    next_run_raw = str(config.get("next_scheduled_run_at") or "").strip()
    if not next_run_raw:
        return None
    try:
        parsed = datetime.fromisoformat(next_run_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    next_run = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    next_run = next_run.astimezone(_ITALY_TZ)
    return (
        "Il criceto chiude il taccuino per ora. "
        f"Ci rivediamo alle **{next_run.strftime('%H:%M')}** con la prossima edizione."
    )


def _next_campaign_run_time(config: dict[str, Any]) -> datetime | None:
    next_run_raw = str(config.get("next_scheduled_run_at") or "").strip()
    if not next_run_raw:
        return None
    try:
        parsed = datetime.fromisoformat(next_run_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    next_run = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return next_run.astimezone(_ITALY_TZ)


def _next_weather_run_field(config: dict[str, Any], *, generated_at: datetime) -> str | None:
    _ = generated_at
    next_run = _next_campaign_run_time(config)
    if next_run is None:
        return None
    return (
        "Il criceto chiude il taccuino meteo per ora.\n"
        f"Ci rivediamo alle **{next_run.strftime('%H:%M')}** con la prossima edizione."
    )


def _next_horoscope_run_field(config: dict[str, Any], *, generated_at: datetime) -> str | None:
    _ = generated_at
    next_run = _next_campaign_run_time(config)
    if next_run is None:
        return None
    return (
        "Il criceto chiude il taccuino per ora.\n"
        f"Ci rivediamo alle **{next_run.strftime('%H:%M')}** con la prossima edizione."
    )


def _format_news_title(text: str) -> str:
    return f"📰 {format_standard_title(text)}"


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


def _news_item_source(item: dict[str, Any]) -> str:
    return str(item.get("source") or "").strip()


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value or "").strip()
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def build_news_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
    now_utc = _overview_now(payload)
    _edition_label, daypart = news_edition_label_for_datetime(now_utc)
    overview = discord.Embed(title=_format_news_title("HAMSTER NEWS • PANORAMICA"), color=color)
    greeting = NEWS_DAYPART_GREETING.get(daypart, NEWS_DAYPART_GREETING["pomeriggio"])
    overview.description = format_standard_description(
        (
            f"**{greeting}**: qui **Barcellometro in regia** 🐹, con la redazione più rumorosa del quartiere. "
            "**Titoli caldi**, pochi giri di parole e **dritti al punto**. 📰"
        ),
        blank_line_before_fields=True,
    )
    selected_slots = payload.get("selected_news_slots")
    if not isinstance(selected_slots, list):
        selected_slots = select_final_news_slots(payload)
    editorial_categories: list[tuple[str, str, str, dict[str, Any]]] = []
    latest_item: dict[str, Any] | None = None
    used_emojis: set[str] = set()
    rendered_sources: list[str] = []
    for slot in selected_slots:
        if not isinstance(slot, dict):
            continue
        item = slot.get("item")
        if not isinstance(item, dict):
            continue
        slot_type = str(slot.get("slot") or "")
        display = str(slot.get("display") or "")
        emoji = str(slot.get("emoji") or "📌")
        if slot_type == "ultimora":
            latest_item = item
            rendered_sources.append(_news_item_source(item))
            overview.add_field(
                name=format_standard_field_name("ULTIM'ORA", emoji="⚡"),
                value=_build_single_news_field_value_with_emoji_tracking(
                    item,
                    display="ULTIM'ORA",
                    used_emojis=used_emojis,
                    seed_key=f"ultimora:{_news_identity(item)}",
                ),
                inline=False,
            )
            continue
        if slot_type == "featured":
            rendered_sources.append(_news_item_source(item))
            overview.add_field(
                name=format_standard_field_name("IN EVIDENZA", emoji="🌟"),
                value=_build_single_news_field_value_with_emoji_tracking(
                    item,
                    display="IN EVIDENZA",
                    used_emojis=used_emojis,
                    seed_key=f"featured:{_news_identity(item)}",
                ),
                inline=False,
            )
            continue
        editorial_categories.append((str(slot.get("category") or ""), display, emoji, item))

    detail_title = _format_news_title("HAMSTER NEWS • LE NOTIZIE")
    secondary_fields: list[tuple[str, str, str | None]] = []
    for category_key, display, emoji, item in editorial_categories:
        secondary_fields.append(
            (
                format_standard_field_name(display, emoji=emoji),
                _build_single_news_field_value_with_emoji_tracking(
                    item,
                    display=display,
                    used_emojis=used_emojis,
                    seed_key=f"{category_key}:{_news_identity(item)}",
                ),
                _news_item_source(item),
            )
        )
    secondary_fields.extend((field_name, field_value, None) for field_name, field_value in _build_news_extra_fields(config, base_dt=now_utc))
    next_run_field = _next_news_run_field(config, generated_at=now_utc)
    if next_run_field:
        secondary_fields.append((format_standard_field_name("PROSSIMA EDIZIONE", emoji="🔜"), next_run_field, None))

    embeds: list[discord.Embed] = [overview]
    detail = discord.Embed(title=detail_title, color=color)
    detail.description = format_standard_description("Che ci racconta il mondo oggi?")
    for field_name, field_value, field_source in secondary_fields:
        candidate = discord.Embed.from_dict(detail.to_dict())
        candidate.add_field(name=field_name, value=field_value, inline=False)
        if len(candidate.fields) > 25 or len(candidate) > 6000:
            if detail.fields:
                embeds.append(detail)
            detail = discord.Embed(title=detail_title, color=color)
            detail.description = format_standard_description("Che ci racconta il mondo oggi?")
            detail.add_field(name=field_name, value=field_value, inline=False)
            if field_source:
                rendered_sources.append(field_source)
            continue
        detail = candidate
        if field_source:
            rendered_sources.append(field_source)
    embeds.append(detail)
    payload["rendered_sources"] = _dedupe_preserve_order(rendered_sources)
    first_image_url = _first_story_image_url([(cat, d, e, [item]) for cat, d, e, item in editorial_categories])
    if first_image_url is None and latest_item is not None:
        first_image_url = _first_story_image_url([("ultimora", "Ultim'ora", "⚡", [latest_item])])
    attach_embed_images_meta(
        overview,
        service_name="campagne_notizie",
        image_url=first_image_url,
    )
    return _apply_campaign_footer(embeds, service_name="campagne_notizie")


def build_news_page_map(payload: dict[str, Any], total_pages: int = 1) -> list[dict[str, Any]]:
    _ = payload
    safe_total = max(1, int(total_pages or 1))
    page_map = [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]
    for idx in range(1, safe_total):
        page_map.append(
            {
                "type": "news",
                "key": f"news_{idx}",
                "label": f"Notizie · Pagina {idx}",
                "page": idx,
            }
        )
    return page_map

def build_weather_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
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
    thermal_range = f"{round(min(all_temps), 1)}°C – {round(max(all_temps), 1)}°C" if all_temps else "n/d"
    now_utc = _overview_now(payload)
    _edition_label, daypart = news_edition_label_for_datetime(now_utc)
    greeting = NEWS_DAYPART_GREETING.get(daypart, NEWS_DAYPART_GREETING["pomeriggio"])

    selected_areas = {slugify_label(item) for item in str(config.get("categories_json") or "").split(",") if str(item).strip()}
    if not selected_areas:
        selected_areas = set(WEATHER_AREAS)

    overview = discord.Embed(title=f"🌦️ {format_standard_title('METEO CRICETOSO • PANORAMICA')}", color=color)
    overview.description = format_standard_description(
        (
            f"**{greeting}** 🐹: qui **Barcellometro in regia**, con il quadro del meteo nazionale. "
            "**Pochi giri di parole**, **zone più mosse** e **temperature sotto controllo**."
        ),
        blank_line_before_fields=True,
    )
    overview.add_field(
        name=format_standard_field_name("AREA PIÙ INSTABILE", emoji="🌩️"),
        value=f"• **{most_unstable}**",
        inline=False,
    )
    overview.add_field(
        name=format_standard_field_name("AREA PIÙ SERENA", emoji="🌤️"),
        value=f"• **{most_calm}**",
        inline=False,
    )
    detail_fields: list[tuple[str, str]] = []
    for region in ["Nord", "Centro", "Sud", "Isole"]:
        if slugify_label(region) not in selected_areas:
            continue
        area_payload = regions.get(region, {})
        area_payload = area_payload if isinstance(area_payload, dict) else {"sampled_cities": area_payload}
        entries = area_payload.get("sampled_cities", [])
        region_key = slugify_label(region)
        short_openers = {
            "nord": "Settimana movimentata e cielo ancora capriccioso sul Nord. 👀",
            "centro": "Giornata un po' ballerina al Centro, con ombrelli ancora protagonisti. 🌧️",
            "sud": "Al Sud prevale un cielo più tranquillo, con qualche nuvola di passaggio. 🙂",
            "isole": "Sulle Isole il quadro è più aperto, tra pause serene e qualche incertezza. 🌤️",
        }
        row = [f"• {short_openers.get(region_key, area_notes.get(region, region))}"]
        for entry in entries[:4]:
            city = entry.get("city", "Città")
            temperature = entry.get("temperature", "n/d")
            windspeed = entry.get("windspeed", "n/d")
            condition = entry.get("condition", "condizioni variabili")
            row.append(
                f"• **{city}** · **{temperature}°C** · vento **{windspeed} km/h** · {condition}"
            )
        if len(entries) == 0:
            row.append("• Dati città in aggiornamento.")
        precipitation_summary = area_payload.get("precipitation_summary", "situazione in aggiornamento")
        wind_summary = area_payload.get("wind_summary", "vento in osservazione")
        focus = f"• **Focus area:** {precipitation_summary} · {wind_summary}"
        value = "\n".join(row)
        detail_fields.append(
            (
                format_standard_field_name(region.upper(), emoji="📍"),
                f"{value[:780]}\n{focus[:220]}",
            )
        )

    trailing_fields: list[tuple[str, str]] = [
        (format_standard_field_name("RANGE TERMICO", emoji="🌡️"), f"• **{thermal_range}**")
    ]
    next_run_field = _next_weather_run_field(config, generated_at=now_utc)
    if next_run_field:
        trailing_fields.append((format_standard_field_name("PROSSIMA EDIZIONE", emoji="🔜"), next_run_field))

    embeds: list[discord.Embed] = [overview]
    details_title = f"🌦️ {format_standard_title('METEO CRICETOSO • LE AREE')}"
    details_description = format_standard_description("Vediamo nel dettaglio le zone climatiche...", blank_line_before_fields=True)
    detail_pages: list[discord.Embed] = []
    current = discord.Embed(title=details_title, color=color)
    current.description = details_description
    for field_name, field_value in detail_fields:
        candidate = discord.Embed.from_dict(current.to_dict())
        candidate.add_field(name=field_name, value=field_value, inline=False)
        if len(candidate.fields) > 25 or len(candidate) > 6000:
            if current.fields:
                detail_pages.append(current)
            current = discord.Embed(title=details_title, color=color)
            current.description = details_description
            current.add_field(name=field_name, value=field_value, inline=False)
            continue
        current = candidate

    if current.fields:
        detail_pages.append(current)
    elif trailing_fields:
        detail_pages.append(discord.Embed(title=details_title, color=color))
        detail_pages[-1].description = details_description

    if trailing_fields:
        if not detail_pages:
            detail_pages.append(discord.Embed(title=details_title, color=color))
            detail_pages[-1].description = details_description
        final_page = detail_pages[-1]
        for field_name, field_value in trailing_fields:
            final_page.add_field(name=field_name, value=field_value, inline=False)

    embeds.extend(detail_pages)
    return _apply_campaign_footer(embeds, service_name="campagne_meteo")


def build_weather_page_map(total_pages: int = 1) -> list[dict[str, Any]]:
    safe_total = max(1, int(total_pages or 1))
    page_map = [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]
    for idx in range(1, safe_total):
        page_map.append(
            {
                "type": "areas",
                "key": f"areas_{idx}",
                "label": f"Aree · Pagina {idx}",
                "page": idx,
            }
        )
    return page_map


def build_horoscope_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
    signs = payload.get("signs", {})

    def _score_sign(sign: str, sign_payload: dict[str, Any]) -> float:
        confidence_raw = sign_payload.get("confidence")
        try:
            confidence = float(confidence_raw) if confidence_raw is not None else 0.0
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(confidence, 1.0))
        base = confidence * 1.6

        positive_markers = (
            "alta", "buona", "bene", "ok", "ottim", "focus", "slancio", "stabile", "seren", "favore", "opportun"
        )
        negative_markers = (
            "bassa", "calo", "tensione", "attrit", "rallenta", "prudenza", "incerto", "fatica", "evita", "caos"
        )
        text = sanitize_horoscope_text(sign, str(sign_payload.get("horoscope") or "")).lower()
        pos_hits = sum(1 for marker in positive_markers if marker in text)
        neg_hits = sum(1 for marker in negative_markers if marker in text)
        lexical = 0.7 * (pos_hits - neg_hits * 1.1)
        if sign_payload.get("fallback_used"):
            lexical -= 0.35
        deterministic_jitter = (sum(ord(ch) for ch in sign) % 17) / 100.0
        return round(base + lexical + deterministic_jitter, 4)

    scored: list[tuple[str, float]] = []
    for sign in SIGN_ORDER:
        sp = signs.get(sign, {})
        sign_payload = sp if isinstance(sp, dict) else {}
        scored.append((sign, _score_sign(sign, sign_payload)))
    ranked = sorted(scored, key=lambda item: item[1], reverse=True)
    top = [name for name, _ in ranked[:3]]
    delicate = [name for name, _ in sorted(scored, key=lambda item: item[1]) if name not in top][:3]
    if len(delicate) < 3:
        delicate = [name for name, _ in sorted(scored, key=lambda item: item[1])[:3]]

    now_utc = _overview_now(payload)
    edition_label, daypart = news_edition_label_for_datetime(now_utc)
    greeting = NEWS_DAYPART_GREETING.get(daypart, NEWS_DAYPART_GREETING["pomeriggio"])

    selected_signs = {slugify_label(item) for item in str(config.get("categories_json") or "").split(",") if str(item).strip()}
    if not selected_signs:
        selected_signs = {slugify_label(sign) for sign in SIGN_ORDER}

    overview_title = f"🔮 {format_standard_title('OROSCOPO CRICETOSO • PANORAMICA')}"
    overview = discord.Embed(title=overview_title, color=color)
    overview.description = format_standard_description((
        f"**{greeting}** 🐹: qui **Barcellometro in regia**, con il quadro zodiacale della giornata. "
        f"**Segni in forma**, **vibrazioni da tenere d'occhio** e **stelle dritte al punto**."
    ), blank_line_before_fields=True)
    def _sign_with_symbol(sign: str) -> str:
        symbol = SIGN_EMOJIS.get(sign, "✨")
        return f"{symbol} {sign}"

    top_list = ", ".join(f"**{_sign_with_symbol(sign)}**" for sign in top) or "**n/d**"
    delicate_list = ", ".join(f"**{_sign_with_symbol(sign)}**" for sign in delicate) or "**n/d**"
    overview.add_field(
        name=format_standard_field_name("SEGNI IN FORMA", emoji="🤗"),
        value=f"• {top_list}",
        inline=False,
    )
    overview.add_field(
        name=format_standard_field_name("SEGNI IRREQUIETI", emoji="🤬"),
        value=f"• {delicate_list}",
        inline=False,
    )

    def _single_bullet(value: str) -> str:
        return f"- {str(value or '')}"

    sign_fields: list[tuple[str, str]] = []
    for sign in SIGN_ORDER:
        if slugify_label(sign) not in selected_signs:
            continue
        data = signs.get(sign, {})
        summary = _single_bullet(str(data.get("horoscope") or ""))
        sign_fields.append((format_standard_field_name(sign.upper(), emoji=SIGN_EMOJIS.get(sign, "✨")), summary))
    embeds: list[discord.Embed] = [overview]
    if sign_fields:
        signs_title = f"🔮 {format_standard_title('OROSCOPO CRICETOSO • I SEGNI')}"
        current = discord.Embed(title=signs_title, color=color)
        current.description = format_standard_description("*Leggiamo l’oroscopo segno per segno...*", blank_line_before_fields=True)
        for field_name, field_value in sign_fields:
            candidate = discord.Embed.from_dict(current.to_dict())
            candidate.add_field(name=field_name, value=field_value, inline=False)
            if len(candidate.fields) > 25 or len(candidate) > 6000:
                if current.fields:
                    embeds.append(current)
                current = discord.Embed(title=signs_title, color=color)
                current.description = format_standard_description("*Leggiamo l’oroscopo segno per segno...*", blank_line_before_fields=True)
                current.add_field(name=field_name, value=field_value, inline=False)
                continue
            current = candidate
        if current.fields:
            embeds.append(current)
    next_run_field = _next_horoscope_run_field(config, generated_at=now_utc)
    if next_run_field:
        target_embed = embeds[-1] if embeds else overview
        target_embed.add_field(
            name=format_standard_field_name("PROSSIMA EDIZIONE", emoji="🔜"),
            value=next_run_field,
            inline=False,
        )
    return _apply_campaign_footer(embeds, service_name="campagne_oroscopo")


def build_horoscope_page_map(total_pages: int = 1) -> list[dict[str, Any]]:
    safe_total = max(1, int(total_pages or 1))
    page_map = [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]
    for idx in range(1, safe_total):
        page_map.append(
            {
                "type": "signs",
                "key": f"signs_{idx}",
                "label": f"Segni · Pagina {idx}",
                "page": idx,
            }
        )
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
