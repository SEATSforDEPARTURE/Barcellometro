from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import discord

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
    total = max(1, len(embeds))
    for idx, embed in enumerate(embeds, start=1):
        _with_footer(embed, idx, total)
        embed.set_footer(text=footer_text)
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


def build_news_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    categories = payload.get("categories", {})
    color = resolve_color(config.get("embed_color"))
    title = config.get("embed_title") or "🗞️ Notizie del giorno"
    embeds: list[discord.Embed] = []
    seen_titles: set[str] = set()
    highlights: list[str] = []
    for category, items in categories.items():
        display = get_category_display_name(category)
        emoji = get_category_emoji(category)
        for item in items:
            title_clean = sanitize_plain_text(item.get("title", ""))[:160]
            if not title_clean:
                continue
            dedupe_key = title_clean.casefold()
            if dedupe_key in seen_titles:
                continue
            seen_titles.add(dedupe_key)
            highlights.append(f"• {emoji} {display} — {title_clean}")
            if len(highlights) >= 3:
                break
        if len(highlights) >= 3:
            break

    overview = discord.Embed(title=f"{title} • Inizio", color=color)
    tone = _time_of_day_label(_overview_now(payload))
    if highlights:
        overview.description = (
            f"🐹 Edizione di **{tone}**: il Barcellometro è in conduzione e la redazione oggi gira come una ruota da corsa.\n"
            "Ecco i titoli che stanno facendo squittire il notiziario:\n\n"
            + "\n".join(highlights)
            + "\n\nPer l'approfondimento categoria per categoria, clicca i pulsanti qui sotto."
        )
    else:
        overview.description = (
            f"🐹 Turno di **{tone}** in redazione: il Barcellometro ha trovato pochi lanci solidi, ma niente panico.\n"
            "Apri i pulsanti in basso e controlla le categorie: può sempre saltare fuori la chicca dell'ultimo minuto."
        )
    embeds.append(overview)
    for category, items in categories.items():
        display = get_category_display_name(category)
        emoji = get_category_emoji(category)
        embed = discord.Embed(title=f"{title} • {display}", color=color)
        lines: list[str] = []
        for idx, item in enumerate(items[:5], start=1):
            summary = trim_sentence_block(item.get("summary", "Nessun riassunto disponibile"), limit=280)
            summary = sanitize_plain_text(summary, remove_category_hint=display)
            lines.append(f"**{idx}. {sanitize_plain_text(item.get('title', 'Titolo'))[:160]}**")
            lines.append(summary or "Aggiornamento in arrivo.")
            lines.append(f"`Fonte: {sanitize_plain_text(item.get('source', 'n/d'))[:80]}` • [Apri link]({item.get('link', 'https://example.com')})")
            lines.append("")
        embed.description = "\n".join(lines)[:3900] or f"Nessuna notizia valida per {emoji} {display}."
        embeds.append(embed)
    return embeds


def build_news_page_map(payload: dict[str, Any]) -> list[dict[str, Any]]:
    page_map: list[dict[str, Any]] = [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]
    for index, category in enumerate(payload.get("categories", {}).keys(), start=1):
        page_map.append(
            {
                "type": "category",
                "key": slugify_label(category),
                "label": f"{get_category_emoji(category)} {get_category_display_name(category).upper()}",
                "page": index,
            }
        )
    return page_map


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
        e = discord.Embed(title=f"{title} • {page_title}", description=description[:3900], color=color)
        e.add_field(name="Commento", value=comment[:1024], inline=False)
        embeds.append(e)
    return embeds


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
    overview = discord.Embed(title=f"{title} • Inizio", color=color)
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
        e = discord.Embed(title=f"{title} • {sign}", color=color)
        e.add_field(name="❤️ Amore", value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("love") or "Cuore in fase di analisi")), limit=280)[:1024], inline=False)
        e.add_field(name="💼 Lavoro / Studio", value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("work") or "Organizzati per priorità")), limit=280)[:1024], inline=False)
        e.add_field(name="💰 Soldi", value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("money") or "Gestione prudente")), limit=240)[:1024], inline=False)
        e.add_field(name="⚡ Energia", value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("energy") or "Energia variabile")), limit=220)[:1024], inline=False)
        e.add_field(name="🔥 Con chi barcellerai oggi", value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("friction") or "Con chi ti mette fretta")), limit=220)[:1024], inline=False)
        e.add_field(name="🐹 Consiglio cricetoso", value=trim_sentence_block(sanitize_horoscope_text(sign, str(data.get("advice") or "Piccoli passi, grandi risultati")), limit=220)[:1024], inline=False)
        embeds.append(e)
    return embeds


def build_horoscope_page_map() -> list[dict[str, Any]]:
    page_map: list[dict[str, Any]] = [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]
    for i, sign in enumerate(SIGN_ORDER, start=1):
        page_map.append({"type": "sign", "key": slugify_label(sign), "label": f"{SIGN_EMOJIS.get(sign, '✨')} {sign.upper()}", "page": i})
    return page_map


def build_fallback_embed(config: dict[str, Any], sources: list[str]) -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
    title = config.get("embed_title") or "Servizio campagne"
    embed = discord.Embed(
        title=title,
        description="Oggi il servizio non è riuscito a raccogliere contenuti affidabili.",
        color=color,
    )
    embed.add_field(name="Fonti tentate", value="\n".join(sources) or "n/d", inline=False)
    return [embed]
