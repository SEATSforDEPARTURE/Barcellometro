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
    overview = discord.Embed(title=title, color=color)
    overview.description = (
        "Raccolta fresca fresca per le cricetine/polle.\n"
        f"Categorie trovate: {', '.join(categories.keys()) or 'nessuna'}\n"
        f"Numero notizie: {total_news}\n"
        f"Chicca del giorno: {next(iter(categories.keys()), 'niente drammi, oggi chill')}"
    )
    overview.add_field(name="Fonti", value="\n".join(payload.get("sources", [])[:8]) or "n/d", inline=False)
    embeds.append(overview)
    for category, items in categories.items():
        embed = discord.Embed(title=f"{title} • {category.title()}", color=color)
        lines: list[str] = []
        for item in items[:5]:
            lines.append(f"• **{item.get('title', 'Titolo')}**")
            lines.append(f"{item.get('summary', 'Nessun riassunto')[:220]}")
            lines.append(f"Fonte: {item.get('source', 'n/d')} • [Link]({item.get('link', 'https://example.com')})")
            lines.append("")
        embed.description = "\n".join(lines)[:3900] or "Nessuna notizia valida."
        embeds.append(embed)
    return embeds


def build_weather_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
    title = config.get("embed_title") or "🌦️ Meteo Italia"
    regions = payload.get("regions", {})
    pages: list[tuple[str, str]] = [("Overview Italia", "Nord, Centro, Sud e Isole in pillole.")]
    for region in ["Nord", "Centro", "Sud e Isole"]:
        entries = regions.get(region, [])
        row = []
        for entry in entries:
            row.append(f"**{entry['city']}**: {entry.get('temperature', 'n/d')}°C, vento {entry.get('windspeed', 'n/d')} km/h")
        pages.append((region, "\n".join(row) or "Dati non disponibili"))
    embeds: list[discord.Embed] = []
    for idx, (page_title, description) in enumerate(pages, start=1):
        e = discord.Embed(title=f"{title} • {page_title}", description=description[:3900], color=color)
        e.add_field(name="Commento", value="Ombrellino in borsa e drama sotto controllo.", inline=False)
        embeds.append(e)
    return embeds


def build_horoscope_embeds(config: dict[str, Any], payload: dict[str, Any]) -> list[discord.Embed]:
    color = resolve_color(config.get("embed_color"))
    title = config.get("embed_title") or "🔮 Oroscopo cricetoso"
    signs = payload.get("signs", {})
    embeds: list[discord.Embed] = []
    overview = discord.Embed(title=f"{title} • Overview", description="Scegli il tuo segno dai bottoni qui sotto ✨", color=color)
    embeds.append(overview)
    for sign in SIGN_ORDER:
        text = str(signs.get(sign, {}).get("text") or "Giornata soft.")
        e = discord.Embed(title=f"{title} • {sign}", color=color)
        e.add_field(name="Amore", value=text[:250], inline=False)
        e.add_field(name="Lavoro", value="Muoviti smart, niente panico.", inline=True)
        e.add_field(name="Soldi", value="Occhio alle spese impulsive.", inline=True)
        e.add_field(name="Energia", value="Media-alta con snack tattico.", inline=True)
        e.add_field(name="Con chi barcellerai oggi", value="Con chi ti fa ridere davvero.", inline=False)
        e.add_field(name="Consiglio cricetoso", value="Respira, sorridi, poi conquista il feed.", inline=False)
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
