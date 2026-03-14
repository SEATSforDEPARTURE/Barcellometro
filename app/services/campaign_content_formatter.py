from __future__ import annotations

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


def resolve_color(color_raw: str | None) -> int:
    if not color_raw:
        return DEFAULT_COLOR
    value = color_raw.strip().lower().replace("#", "").replace("0x", "")
    try:
        return int(value, 16)
    except ValueError:
        return DEFAULT_COLOR


def _with_footer(embed: discord.Embed, page: int, total: int) -> discord.Embed:
    title = (embed.title or "").strip()
    embed.title = f"{title} • Pagina {page}/{total}" if title else f"Pagina {page}/{total}"
    return embed


def apply_shared_footer_and_pagination(embeds: list[discord.Embed], footer_text: str) -> list[discord.Embed]:
    total = max(1, len(embeds))
    for idx, embed in enumerate(embeds, start=1):
        _with_footer(embed, idx, total)
        embed.set_footer(text=footer_text)
    return embeds


def build_news_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    categories = payload.get("categories", {})
    color = resolve_color(config.get("embed_color"))
    title = config.get("embed_title") or "🗞️ Notizie del giorno"
    embeds: list[discord.Embed] = []
    total_news = sum(len(v) for v in categories.values())
    ordered_categories = sorted(categories.items(), key=lambda item: len(item[1]), reverse=True)
    noisy = ordered_categories[0][0].title() if ordered_categories else "Nessuna"
    top_title = ordered_categories[0][1][0].get("title") if ordered_categories and ordered_categories[0][1] else "Niente di affidabile"
    overview = discord.Embed(title=f"{title} • Overview", color=color)
    overview.description = (
        "Panoramica editoriale della giornata, derivata dalle fonti raccolte.\n"
        f"Categorie monitorate ({len(categories)}): {', '.join(k.title() for k in categories.keys()) or 'nessuna'}\n"
        f"Totale notizie aggregate: **{total_news}**\n"
        f"🔊 Cosa fa più rumore oggi: **{noisy}**\n"
        f"⭐ Top highlight: **{str(top_title)[:140]}**"
    )
    overview.add_field(name="🧭 Intro", value="Scorri le pagine categoria per i dettagli 3-5 notizie con fonte e link.", inline=False)
    overview.add_field(name="🐹 Chicca del giorno", value=f"La categoria **{noisy}** è quella con più movimento in questo run.", inline=False)
    embeds.append(overview)
    for category, items in categories.items():
        embed = discord.Embed(title=f"{title} • {category.title()}", color=color)
        lines: list[str] = []
        for idx, item in enumerate(items[:5], start=1):
            lines.append(f"**{idx}. {item.get('title', 'Titolo')}**")
            lines.append(f"{item.get('summary', 'Nessun riassunto disponibile')[:320]}")
            lines.append(f"Fonte: {item.get('source', 'n/d')} • [Link]({item.get('link', 'https://example.com')})")
            lines.append("")
        embed.description = "\n".join(lines)[:3900] or "Nessuna notizia valida."
        embeds.append(embed)
    return embeds


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

    pages: list[tuple[str, str, str]] = [
        (
            "Overview Italia",
            (
                "🇮🇹 Situazione generale: quadro meteo aggregato dalle aree monitorate.\n"
                f"⚡ Area più instabile: **{most_unstable}**\n"
                f"🌤️ Area più serena: **{most_calm}**\n"
                f"🌡️ Range termico nazionale: **{thermal_range}**\n"
                f"☂️ Nota pratica: {'Porta ombrello pieghevole' if most_unstable != most_calm else 'Giornata gestibile, tieni una felpa leggera'}"
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
    focus_love = next((str(signs.get(s, {}).get("love")) for s in top if signs.get(s, {}).get("love")), "Ascolta di più e reagisci di meno.")
    focus_work = next((str(signs.get(s, {}).get("work")) for s in top if signs.get(s, {}).get("work")), "Scegli priorità chiare.")

    embeds: list[discord.Embed] = []
    overview = discord.Embed(title=f"{title} • Overview", color=color)
    overview.description = (
        "✨ **Mood del giorno**\n"
        f"Atmosfera zodiacale: {mood}.\n\n"
        f"🔥 **Segni più frizzanti**\n{', '.join(f'{SIGN_EMOJIS[s]} {s}' for s in top)}\n\n"
        f"🌧️ **Segni da trattare con dolcezza**\n{', '.join(f'{SIGN_EMOJIS[s]} {s}' for s in delicate)}\n\n"
        f"💘 **Focus amore**\n{focus_love[:220]}\n\n"
        f"💼 **Focus lavoro/energia**\n{focus_work[:220]}\n\n"
        "🐹 **Consiglio cricetoso**\nScegli il tuo segno nei pulsanti: oggi conta la precisione emotiva, non il copia-incolla cosmico."
    )
    embeds.append(overview)
    for sign in SIGN_ORDER:
        data = signs.get(sign, {})
        e = discord.Embed(title=f"{title} • {sign}", color=color)
        e.add_field(name="❤️ Amore", value=str(data.get("love") or "Cuore in fase di analisi")[:1024], inline=False)
        e.add_field(name="💼 Lavoro / Studio", value=str(data.get("work") or "Organizzati per priorità")[:1024], inline=False)
        e.add_field(name="💰 Soldi", value=str(data.get("money") or "Gestione prudente")[:1024], inline=False)
        e.add_field(name="⚡ Energia", value=str(data.get("energy") or "Energia variabile")[:1024], inline=False)
        e.add_field(name="🔥 Con chi barcellerai oggi", value=str(data.get("friction") or "Con chi ti mette fretta")[:1024], inline=False)
        e.add_field(name="🐹 Consiglio cricetoso", value=str(data.get("advice") or "Piccoli passi, grandi risultati")[:1024], inline=False)
        if data.get("tone"):
            e.add_field(name="✨ Tono del giorno", value=str(data.get("tone"))[:200], inline=False)
        embeds.append(e)
    return embeds


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
