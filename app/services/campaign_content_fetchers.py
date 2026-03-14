from __future__ import annotations

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

NEWS_SOURCE_MAP = {
    "ansa": "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",
    "repubblica": "https://www.repubblica.it/rss/homepage/rss2.0.xml",
    "ilpost": "https://www.ilpost.it/feed/",
    "open": "https://www.open.online/feed/",
    "fanpage": "https://www.fanpage.it/feed/",
    "wired": "https://www.wired.it/feed/rss",
    "corriere": "https://xml2.corriereobjects.it/rss/homepage.xml",
}

WEATHER_SOURCE_MAP = {
    "open-meteo": "open-meteo",
    "meteoam": "meteoam",
    "3bmeteo": "3bmeteo",
    "ilmeteo": "ilmeteo",
}

HOROSCOPE_SOURCE_MAP = {
    "ohmanda": "https://ohmanda.com/api/horoscope",
    "astrocenter": "astrocenter",
    "horoscope": "horoscope",
}

DEFAULT_NEWS_SOURCES = ["ansa", "repubblica"]
DEFAULT_WEATHER_SOURCES = ["open-meteo", "meteoam", "3bmeteo"]
DEFAULT_HOROSCOPE_SOURCES = ["ohmanda"]

SIGNS = [
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


def _http_get(url: str, *, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Barcellometro/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def _normalize_source_tokens(sources: list[str], defaults: list[str]) -> list[str]:
    tokens = sources or defaults
    normalized: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        candidate = token.strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered not in seen:
            seen.add(lowered)
            normalized.append(lowered)
    return normalized


def _resolve_news_sources(sources: list[str]) -> list[str]:
    resolved: list[str] = []
    for token in _normalize_source_tokens(sources, DEFAULT_NEWS_SOURCES):
        mapped = NEWS_SOURCE_MAP.get(token)
        if mapped:
            resolved.append(mapped)
            continue
        if token.startswith(("http://", "https://")):
            resolved.append(token)
    return resolved


def _resolve_weather_sources(sources: list[str]) -> list[str]:
    resolved: list[str] = []
    for token in _normalize_source_tokens(sources, DEFAULT_WEATHER_SOURCES):
        mapped = WEATHER_SOURCE_MAP.get(token)
        if mapped:
            resolved.append(mapped)
            continue
        if token.startswith(("http://", "https://")):
            resolved.append(token)
    return resolved


def _resolve_horoscope_sources(sources: list[str]) -> list[str]:
    resolved: list[str] = []
    for token in _normalize_source_tokens(sources, DEFAULT_HOROSCOPE_SOURCES):
        mapped = HOROSCOPE_SOURCE_MAP.get(token)
        if mapped:
            resolved.append(mapped)
            continue
        if token.startswith(("http://", "https://")):
            resolved.append(token)
    return resolved


def fetch_news_content(sources: list[str], categories: list[str]) -> dict[str, Any]:
    normalized_categories = [c.strip().lower() for c in categories if c.strip()]
    effective_sources = _resolve_news_sources(sources)
    items: list[dict[str, str]] = []
    attempted: list[str] = []
    for source in effective_sources:
        attempted.append(source)
        try:
            payload = _http_get(source)
            root = ET.fromstring(payload)
            for node in root.findall(".//item"):
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                description = (node.findtext("description") or "").strip()
                category = (node.findtext("category") or "varie").strip().lower()
                if normalized_categories and not any(tag in f"{title} {description} {category}".lower() for tag in normalized_categories):
                    continue
                items.append(
                    {
                        "title": title[:160],
                        "link": link,
                        "summary": description[:400],
                        "category": category or "varie",
                        "source": urllib.parse.urlparse(source).netloc or source,
                    }
                )
        except Exception:
            continue
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in items:
        grouped.setdefault(item["category"], []).append(item)
    return {"categories": grouped, "sources": attempted}


def fetch_weather_content(sources: list[str]) -> dict[str, Any]:
    resolved_sources = _resolve_weather_sources(sources)
    if not resolved_sources:
        resolved_sources = _resolve_weather_sources(DEFAULT_WEATHER_SOURCES)

    primary_provider = "open-meteo" if "open-meteo" in resolved_sources else resolved_sources[0]
    displayed_sources = resolved_sources

    regions = {
        "Nord": [(45.4642, 9.19, "Milano"), (45.0703, 7.6869, "Torino")],
        "Centro": [(41.9028, 12.4964, "Roma"), (43.7696, 11.2558, "Firenze")],
        "Sud e Isole": [(40.8518, 14.2681, "Napoli"), (38.1157, 13.3615, "Palermo")],
    }
    data: dict[str, list[dict[str, Any]]] = {}
    for area, cities in regions.items():
        data[area] = []
        for lat, lon, city in cities:
            if primary_provider != "open-meteo":
                data[area].append({"city": city, "temperature": None, "windspeed": None, "weathercode": None})
                continue
            url = (
                "https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}&current_weather=true"
            )
            try:
                payload = json.loads(_http_get(url))
                weather = payload.get("current_weather", {})
                data[area].append(
                    {
                        "city": city,
                        "temperature": weather.get("temperature"),
                        "windspeed": weather.get("windspeed"),
                        "weathercode": weather.get("weathercode"),
                    }
                )
            except Exception:
                data[area].append({"city": city, "temperature": None, "windspeed": None, "weathercode": None})
    return {"regions": data, "sources": displayed_sources}


def fetch_horoscope_content(sources: list[str]) -> dict[str, Any]:
    resolved_sources = _resolve_horoscope_sources(sources)
    if not resolved_sources:
        resolved_sources = _resolve_horoscope_sources(DEFAULT_HOROSCOPE_SOURCES)

    base: str | None = None
    if "https://ohmanda.com/api/horoscope" in resolved_sources:
        base = "https://ohmanda.com/api/horoscope"
    else:
        for source in resolved_sources:
            if source.startswith(("http://", "https://")):
                base = source.rstrip("/")
                break

    slug_map = {
        "Ariete": "aries",
        "Toro": "taurus",
        "Gemelli": "gemini",
        "Cancro": "cancer",
        "Leone": "leo",
        "Vergine": "virgo",
        "Bilancia": "libra",
        "Scorpione": "scorpio",
        "Sagittario": "sagittarius",
        "Capricorno": "capricorn",
        "Acquario": "aquarius",
        "Pesci": "pisces",
    }
    items: dict[str, dict[str, str]] = {}
    for sign in SIGNS:
        if not base:
            items[sign] = {"text": "Giornata nebulosa: prendila con filosofia e un caffè."}
            continue
        try:
            payload = json.loads(_http_get(f"{base}/{slug_map[sign]}"))
            horoscope = str(payload.get("horoscope") or "").strip()
            items[sign] = {"text": horoscope or "Giornata nebulosa: prendila con filosofia e un caffè."}
        except Exception:
            items[sign] = {"text": "Giornata nebulosa: prendila con filosofia e un caffè."}
    return {"signs": items, "sources": resolved_sources}
