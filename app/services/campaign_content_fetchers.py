from __future__ import annotations

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

DEFAULT_NEWS_SOURCES = [
    "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",
    "https://www.repubblica.it/rss/homepage/rss2.0.xml",
]

DEFAULT_WEATHER_SOURCES = ["open-meteo"]
DEFAULT_HOROSCOPE_SOURCES = ["https://ohmanda.com/api/horoscope"]

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


def fetch_news_content(sources: list[str], categories: list[str]) -> dict[str, Any]:
    normalized_categories = [c.strip().lower() for c in categories if c.strip()]
    effective_sources = sources or list(DEFAULT_NEWS_SOURCES)
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


def fetch_weather_content(_: list[str]) -> dict[str, Any]:
    regions = {
        "Nord": [(45.4642, 9.19, "Milano"), (45.0703, 7.6869, "Torino")],
        "Centro": [(41.9028, 12.4964, "Roma"), (43.7696, 11.2558, "Firenze")],
        "Sud e Isole": [(40.8518, 14.2681, "Napoli"), (38.1157, 13.3615, "Palermo")],
    }
    data: dict[str, list[dict[str, Any]]] = {}
    for area, cities in regions.items():
        data[area] = []
        for lat, lon, city in cities:
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
    return {"regions": data, "sources": list(DEFAULT_WEATHER_SOURCES)}


def fetch_horoscope_content(sources: list[str]) -> dict[str, Any]:
    base = (sources[0] if sources else DEFAULT_HOROSCOPE_SOURCES[0]).rstrip("/")
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
        try:
            payload = json.loads(_http_get(f"{base}/{slug_map[sign]}"))
            horoscope = str(payload.get("horoscope") or "").strip()
            items[sign] = {"text": horoscope}
        except Exception:
            items[sign] = {"text": "Giornata nebulosa: prendila con filosofia e un caffè."}
    return {"signs": items, "sources": [base]}
