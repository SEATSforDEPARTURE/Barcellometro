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
    "barzelletta": ["Il criceto in redazione: «Promesso, oggi apro solo tre tab». Erano trenta."],
    "aforisma": ["La notizia corre, il criterio decide la direzione."],
    "canzone": ["Heroes — David Bowie\nEnergia da prima pagina per la ruota della redazione."],
    "meme": ["Quando dici «chiudo in 5 minuti» e la breaking spunta al minuto 6."],
}
NEWS_DAYPART_COPY = {
    "mattina": "mattino",
    "pomeriggio": "pomeriggio",
    "sera": "sera",
    "notte": "sera",
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
_SERIOUS_NEWS_TAIL_COMMENTS = (
    "Una vicenda che lascia addosso parecchio gelo 🫥",
    "Qui il quadro è davvero pesante, purtroppo 😔",
    "Una storia che colpisce duro, senza girarci attorno 🫥",
    "Il clima resta cupo, e si sente tutto 😔",
    "Qui c’è poco da alleggerire, purtroppo 🫥",
    "Notizia durissima da mandare giù 😔",
    "Una notizia davvero pesante, purtroppo 🫥",
    "Qui il quadro è doloroso, senza girarci attorno 😔",
)
_STANDARD_NEWS_TAIL_COMMENTS = (
    "Insomma, aria bella tesa 🐹",
    "Qui la ruota gira veloce 👀",
    "Tema che farà ancora discutere parecchio 🤹",
    "La faccenda resta bella calda 👀",
    "Qui si continua a girare forte sulla ruota 🐹",
    "Insomma, il brusio non manca di certo 👀",
    "Tema che farà discutere ancora un bel po’ 🤹",
)
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


def extract_first_sentences(text: str, max_sentences: int = 2) -> str:
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
        return extract_first_sentences(candidate, max_sentences=2)
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
    used_tail_comments: set[str] | None = None,
    seed_key: str | None = None,
) -> str:
    ai_summary = sanitize_public_news_text(str(item.get("ai_summary") or ""))
    if not _is_useless_news_text(ai_summary):
        return _normalize_news_summary_for_embed(
            ai_summary,
            item=item,
            display=display,
            used_tail_comments=used_tail_comments,
            seed_key=seed_key,
        )
    summary = sanitize_public_news_text(str(item.get("summary") or ""))
    summary = sanitize_plain_text(summary, remove_category_hint=display)
    if _is_useless_news_text(summary):
        return _normalize_news_summary_for_embed(
            _first_real_news_sentences(item),
            item=item,
            display=display,
            used_tail_comments=used_tail_comments,
            seed_key=seed_key,
        )
    return _normalize_news_summary_for_embed(
        summary,
        item=item,
        display=display,
        used_tail_comments=used_tail_comments,
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


def _build_news_tail_comment(*, tone: str, item: dict[str, Any]) -> str:
    palette = _SERIOUS_NEWS_TAIL_COMMENTS if tone == "serious" else _STANDARD_NEWS_TAIL_COMMENTS
    key = _news_identity(item) or sanitize_plain_text(str(item.get("title") or "")).lower() or "news"
    idx = abs(hash(key)) % len(palette)
    return palette[idx]


def _pick_news_tail_comment(tone: str, used_comments: set[str], seed_key: str | None = None) -> str:
    palette = _SERIOUS_NEWS_TAIL_COMMENTS if tone == "serious" else _STANDARD_NEWS_TAIL_COMMENTS
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
    cleaned = sanitize_public_news_text(cleaned)
    if not cleaned:
        cleaned = "Dettagli in aggiornamento."
    cleaned = cleaned.strip()
    if not re.search(r"[.!?]\s*$", cleaned):
        cleaned = f"{cleaned}."
    return cleaned


def _compose_news_embed_summary(body: str, tail_comment: str) -> str:
    body_clean = sanitize_public_news_text(body)
    tail = sanitize_public_news_text(tail_comment)
    if not body_clean:
        body_clean = "Dettagli in aggiornamento."
    if not tail:
        tail = _STANDARD_NEWS_TAIL_COMMENTS[0]
    if not re.search(r"[.!?]\s*$", body_clean):
        body_clean = f"{body_clean}."
    if body_clean.endswith(f" {tail}"):
        return body_clean
    return f"{body_clean} {tail}".strip()


def _normalize_news_summary_for_embed(
    raw_summary: str,
    *,
    item: dict[str, Any],
    display: str,
    used_tail_comments: set[str] | None = None,
    seed_key: str | None = None,
) -> str:
    tone = _classify_news_tone(item, display=display)
    body = _build_news_summary_body(raw_summary, item=item, display=display, tone=tone)
    if used_tail_comments is None:
        tail = _build_news_tail_comment(tone=tone, item=item)
    else:
        tail = _pick_news_tail_comment(
            tone,
            used_tail_comments,
            seed_key=seed_key or _news_identity(item) or sanitize_plain_text(str(item.get("title") or "")),
        )
    logger.info("news_summary_tail_applied tone=%s title=%s tail=%s", tone, sanitize_plain_text(str(item.get("title") or ""))[:80], tail[:80])
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

    for match in re.finditer(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", cleaned):
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
    used_tail_comments: set[str] | None = None,
    seed_key: str | None = None,
) -> str:
    link = str(item.get("link") or "").strip()
    title_line = sanitize_plain_text(str(item.get("title") or "Titolo non disponibile"))
    linked_title = f"[{title_line}]({link})" if link else title_line
    summary = highlight_key_terms(
        _build_news_item_summary(item, display=display, used_tail_comments=used_tail_comments, seed_key=seed_key)
    )
    heading = f"{index}. **{linked_title}**" if numbered else f"**{linked_title}**"
    source_line = _news_source_line(item, link=link)
    return _fit_news_field_value(heading=heading, summary=summary, source_line=source_line)


def _fit_news_field_value(*, heading: str, summary: str, source_line: str) -> str:
    composed = f"{heading}\n• {summary}\n`fonte: {source_line}`"
    if len(composed) <= _NEWS_FIELD_HARD_LIMIT:
        return composed
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", summary) if part.strip()]
    while len(sentences) > 1:
        sentences.pop()
        candidate_summary = " ".join(sentences).strip()
        candidate = f"{heading}\n• {candidate_summary}\n`fonte: {source_line}`"
        if len(candidate) <= _NEWS_FIELD_HARD_LIMIT:
            return candidate
    one_sentence = sentences[0] if sentences else summary
    candidate = f"{heading}\n• {one_sentence}\n`fonte: {source_line}`"
    if len(candidate) <= _NEWS_FIELD_HARD_LIMIT:
        return candidate
    # Extreme safeguard: preserve structure without cutting a sentence mid-stream.
    return f"{heading}\n• Dettagli disponibili al link.\n`fonte: {source_line}`"


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
    return _build_single_news_field_value_with_tail_tracking(item=item, display=display, used_tail_comments=None, seed_key=None)


def _build_single_news_field_value_with_tail_tracking(
    item: dict[str, Any],
    *,
    display: str,
    used_tail_comments: set[str] | None,
    seed_key: str | None,
) -> str:
    return _format_news_item_block(
        item,
        display=display,
        numbered=False,
        index=0,
        used_tail_comments=used_tail_comments,
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
            if sum(1 for slot in selected_slots if slot.get("slot") == "category") >= _NEWS_MAX_EDITORIAL_CATEGORIES:
                break
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


def build_news_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
    now_utc = _overview_now(payload)
    edition_label, daypart = news_edition_label_for_datetime(now_utc)
    overview = discord.Embed(title=_format_news_title(f"HAMSTER NEWS • {edition_label}"), color=color)
    time_of_day = NEWS_DAYPART_COPY.get(daypart, NEWS_DAYPART_COPY["pomeriggio"])
    overview.description = format_standard_description(
        (
            f"Buon {time_of_day}: qui Barcellometro in regia 🐹, con la redazione più rumorosa del quartiere. "
            "Titoli caldi, pochi giri di parole e dritti al punto. 📰\n"
            "Che ci racconta il mondo oggi?"
        ),
        blank_line_before_fields=True,
    )
    selected_slots = payload.get("selected_news_slots")
    if not isinstance(selected_slots, list):
        selected_slots = select_final_news_slots(payload)
    editorial_categories: list[tuple[str, str, str, dict[str, Any]]] = []
    latest_item: dict[str, Any] | None = None
    used_tail_comments: set[str] = set()
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
            overview.add_field(
                name=format_standard_field_name("ULTIM'ORA", emoji="⚡"),
                value=_build_single_news_field_value_with_tail_tracking(
                    item,
                    display="ULTIM'ORA",
                    used_tail_comments=used_tail_comments,
                    seed_key=f"ultimora:{_news_identity(item)}",
                ),
                inline=False,
            )
            continue
        if slot_type == "featured":
            overview.add_field(
                name=format_standard_field_name("IN EVIDENZA", emoji="🌟"),
                value=_build_single_news_field_value_with_tail_tracking(
                    item,
                    display="IN EVIDENZA",
                    used_tail_comments=used_tail_comments,
                    seed_key=f"featured:{_news_identity(item)}",
                ),
                inline=False,
            )
            continue
        editorial_categories.append((str(slot.get("category") or ""), display, emoji, item))
        category_key = str(slot.get("category") or "")
        overview.add_field(
            name=format_standard_field_name(f"{display} IN PRIMO PIANO", emoji=emoji),
            value=_build_single_news_field_value_with_tail_tracking(
                item,
                display=display,
                used_tail_comments=used_tail_comments,
                seed_key=f"{category_key}:{_news_identity(item)}",
            ),
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
