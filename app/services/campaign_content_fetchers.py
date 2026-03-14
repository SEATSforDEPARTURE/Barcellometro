from __future__ import annotations

import json
import re
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


SIGN_FALLBACKS = {
    "Ariete": {
        "love": "In amore hai voglia di accelerare: evita il turbo con chi ha bisogno di tempi più lenti.",
        "work": "Prendi l'iniziativa su una cosa concreta invece di aprire dieci fronti insieme.",
        "money": "Spendi su ciò che ti fa davvero comodo oggi, non solo su ciò che luccica.",
        "energy": "Energia alta ma nervosa: sfogala in qualcosa di pratico.",
        "friction": "Con chi rimanda troppo o gira intorno al punto.",
        "advice": "Taglia il superfluo e punta dritto al bersaglio.",
    },
    "Toro": {
        "love": "Cerchi rassicurazioni: chiedile con dolcezza, senza test silenziosi.",
        "work": "La costanza ti premia: chiudi un lavoro in sospeso prima di aprirne un altro.",
        "money": "Giornata da controllo budget e piccole scelte intelligenti.",
        "energy": "Ritmo stabile, ma non fossilizzarti sulle abitudini.",
        "friction": "Con chi cambia idea ogni mezz'ora.",
        "advice": "Scegli il comfort che ti fa crescere, non quello che ti blocca.",
    },
    "Gemelli": {
        "love": "Flirt e chat girano veloci: fermati un secondo se senti segnali confusi.",
        "work": "Ottima mente elastica, utile per mediare tra persone diverse.",
        "money": "Piccole uscite sparse: sommate fanno più di quanto immagini.",
        "energy": "Alta e frizzante, con picchi alterni durante il giorno.",
        "friction": "Con chi pretende risposte immediate su tutto.",
        "advice": "Usa la tua curiosità per risolvere, non per disperderti.",
    },
    "Cancro": {
        "love": "Cuore sensibilissimo: parla chiaro prima di chiuderti nel guscio.",
        "work": "Ti riesce bene gestire le persone, soprattutto nei momenti tesi.",
        "money": "Spese di casa o comfort personale da gestire con equilibrio.",
        "energy": "Energia emotiva forte, fisica altalenante.",
        "friction": "Con chi minimizza ciò che provi.",
        "advice": "Metti confini gentili, non muri alti.",
    },
    "Leone": {
        "love": "Hai bisogno di attenzione vera: chiedila con calore, non con orgoglio.",
        "work": "Buona visibilità: sfruttala per guidare, non per sovrastare.",
        "money": "Occhio agli acquisti scenici: scegli valore oltre l'effetto wow.",
        "energy": "Vitalità in crescita, soprattutto nel pomeriggio.",
        "friction": "Con chi non riconosce il tuo impegno.",
        "advice": "Brilla, ma lascia spazio anche alle idee degli altri.",
    },
    "Vergine": {
        "love": "Se qualcosa ti turba, evita di analizzare tutto: prova a sentire e parlare.",
        "work": "Precisione eccellente: giornata ottima per rimettere ordine.",
        "money": "Bilanci e dettagli sotto controllo, bene così.",
        "energy": "Lucida ma da dosare: troppe check-list possono stancarti.",
        "friction": "Con chi improvvisa senza criterio.",
        "advice": "Perfezione no, chiarezza sì.",
    },
    "Bilancia": {
        "love": "Cerchi armonia, ma non annacquare i tuoi desideri per evitare tensioni.",
        "work": "Ottimo fiuto diplomatico per sbloccare un nodo relazionale.",
        "money": "Giornata buona per scegliere qualità e tagliare il superfluo.",
        "energy": "Regolare, migliora con ritmi equilibrati.",
        "friction": "Con chi impone decisioni senza ascolto.",
        "advice": "Sii gentile anche quando dici un no netto.",
    },
    "Scorpione": {
        "love": "Emozioni profonde: evita i test di fedeltà, punta su domande sincere.",
        "work": "Concentrazione potente, ideale per attività strategiche.",
        "money": "Fase prudente: meglio consolidare che rischiare.",
        "energy": "Intensa, ma non lasciare che si trasformi in rigidità.",
        "friction": "Con chi resta in superficie.",
        "advice": "Trasforma la diffidenza in osservazione utile.",
    },
    "Sagittario": {
        "love": "Hai voglia di leggerezza e avventura: condividi i piani con chi ti sta vicino.",
        "work": "Visione ampia e buona intuizione su nuove opportunità.",
        "money": "Spese per esperienze o spostamenti: pianifica prima.",
        "energy": "Dinamica e ottimista, tende a salire la sera.",
        "friction": "Con chi vuole bloccarti in routine strette.",
        "advice": "Libertà sì, ma con una direzione chiara.",
    },
    "Capricorno": {
        "love": "Ti apri poco ma quando lo fai lasci il segno: fallo con tempi umani.",
        "work": "Produttività alta, soprattutto su obiettivi a medio termine.",
        "money": "Scelte razionali favorite, evita l'eccesso di controllo.",
        "energy": "Solida e concreta: attenzione alla rigidità fisica.",
        "friction": "Con chi promette molto e conclude poco.",
        "advice": "Concediti una pausa senza sensi di colpa.",
    },
    "Acquario": {
        "love": "Ti stimola chi porta idee nuove: chiarisci però i limiti emotivi.",
        "work": "Creatività e pensiero laterale sono la tua carta migliore.",
        "money": "Spese impulsive su tecnologia o hobby: misura il reale utilizzo.",
        "energy": "Mentale altissima, fisica variabile.",
        "friction": "Con chi vuole regole troppo strette.",
        "advice": "Originale sì, ma resta comprensibile.",
    },
    "Pesci": {
        "love": "Empatia fortissima: non assorbire i problemi degli altri come fossero tuoi.",
        "work": "Ispirazione buona, da accompagnare con priorità pratiche.",
        "money": "Occhio a spese emotive o poco ponderate.",
        "energy": "Sensibile ai contesti: scegli ambienti e persone che ti nutrono.",
        "friction": "Con chi parla solo di numeri e ignora il lato umano.",
        "advice": "Proteggi la tua sensibilità senza spegnere la fantasia.",
    },
}


SIGN_MOOD_HINTS = {
    "Ariete": "impulsivo",
    "Toro": "stabile",
    "Gemelli": "vivace",
    "Cancro": "sensibile",
    "Leone": "solare",
    "Vergine": "ordinato",
    "Bilancia": "diplomatico",
    "Scorpione": "intenso",
    "Sagittario": "avventuroso",
    "Capricorno": "determinato",
    "Acquario": "creativo",
    "Pesci": "sognante",
}


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
    used_sources: list[str] = []
    for source in effective_sources:
        attempted.append(source)
        try:
            payload = _http_get(source)
            root = ET.fromstring(payload)
            found_for_source = False
            for node in root.findall(".//item"):
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                description = re.sub(r"\s+", " ", (node.findtext("description") or "").strip())
                category = (node.findtext("category") or "varie").strip().lower()
                if normalized_categories and not any(tag in f"{title} {description} {category}".lower() for tag in normalized_categories):
                    continue
                found_for_source = True
                items.append(
                    {
                        "title": title[:160],
                        "link": link,
                        "summary": description[:500],
                        "category": category or "varie",
                        "source": urllib.parse.urlparse(source).netloc or source,
                    }
                )
            if found_for_source:
                used_sources.append(source)
        except Exception:
            continue
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in items:
        grouped.setdefault(item["category"], []).append(item)
    return {"categories": grouped, "sources": attempted, "used_sources": used_sources, "configured_sources": sources}


def fetch_weather_content(sources: list[str]) -> dict[str, Any]:
    resolved_sources = _resolve_weather_sources(sources)
    if not resolved_sources:
        resolved_sources = _resolve_weather_sources(DEFAULT_WEATHER_SOURCES)

    primary_provider = "open-meteo" if "open-meteo" in resolved_sources else resolved_sources[0]
    regions = {
        "Nord": [(45.4642, 9.19, "Milano"), (45.0703, 7.6869, "Torino"), (44.4056, 8.9463, "Genova")],
        "Centro": [(41.9028, 12.4964, "Roma"), (43.7696, 11.2558, "Firenze"), (43.1107, 12.3908, "Perugia")],
        "Sud e Isole": [(40.8518, 14.2681, "Napoli"), (38.1157, 13.3615, "Palermo"), (39.2238, 9.1217, "Cagliari")],
    }

    weathercode_map = {
        0: "sereno",
        1: "quasi sereno",
        2: "parzialmente nuvoloso",
        3: "coperto",
        45: "nebbia",
        51: "pioviggine",
        61: "pioggia",
        63: "pioggia moderata",
        65: "pioggia intensa",
        71: "neve",
        80: "rovesci",
        95: "temporali",
    }

    data: dict[str, dict[str, Any]] = {}
    used_sources: list[str] = []
    fallback_used = False
    for area, cities in regions.items():
        sampled: list[dict[str, Any]] = []
        area_temps: list[float] = []
        area_winds: list[float] = []
        conditions: list[str] = []
        for lat, lon, city in cities:
            if primary_provider != "open-meteo":
                fallback_used = True
                sampled.append({"city": city, "temperature": None, "windspeed": None, "weathercode": None, "condition": "dati non disponibili"})
                continue
            url = "https://api.open-meteo.com/v1/forecast?" f"latitude={lat}&longitude={lon}&current_weather=true"
            try:
                payload = json.loads(_http_get(url))
                weather = payload.get("current_weather", {})
                temperature = weather.get("temperature")
                windspeed = weather.get("windspeed")
                weathercode = weather.get("weathercode")
                condition = weathercode_map.get(int(weathercode), "variabile") if weathercode is not None else "variabile"
                sampled.append({
                    "city": city,
                    "temperature": temperature,
                    "windspeed": windspeed,
                    "weathercode": weathercode,
                    "condition": condition,
                })
                if isinstance(temperature, (int, float)):
                    area_temps.append(float(temperature))
                if isinstance(windspeed, (int, float)):
                    area_winds.append(float(windspeed))
                conditions.append(condition)
                if "open-meteo" not in used_sources:
                    used_sources.append("open-meteo")
            except Exception:
                fallback_used = True
                sampled.append({"city": city, "temperature": None, "windspeed": None, "weathercode": None, "condition": "dati non disponibili"})

        data[area] = {
            "area": area,
            "sampled_cities": sampled,
            "summary": (
                f"{area}: tempo {max(set(conditions), key=conditions.count)} prevalente"
                if conditions
                else f"{area}: dati meteo limitati"
            ),
            "temp_min": min(area_temps) if area_temps else None,
            "temp_max": max(area_temps) if area_temps else None,
            "wind_summary": (
                f"vento medio {round(sum(area_winds) / len(area_winds), 1)} km/h"
                if area_winds
                else "vento non determinabile"
            ),
            "precipitation_summary": (
                "possibili piogge" if any("piogg" in cond or "roves" in cond or "tempor" in cond for cond in conditions) else "precipitazioni poco probabili"
            ),
            "notable_conditions": sorted(set(conditions))[:4],
            "source_points": [
                f"{entry['city']}: {entry['condition']}" for entry in sampled if entry.get("condition") and entry.get("condition") != "dati non disponibili"
            ][:4],
            "source_names": used_sources[:],
        }

    return {
        "regions": data,
        "sources": resolved_sources,
        "used_sources": used_sources,
        "configured_sources": sources,
        "fallback_used": fallback_used,
        "provider": primary_provider,
    }


def _split_horoscope_sections(text: str) -> dict[str, str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    clauses = [chunk.strip(" -") for chunk in re.split(r"(?<=[.!?;])\s+", cleaned) if chunk.strip()]
    if not clauses:
        clauses = [cleaned] if cleaned else []
    love = clauses[0] if clauses else ""
    work = clauses[1] if len(clauses) > 1 else clauses[0] if clauses else ""
    money = clauses[2] if len(clauses) > 2 else ""
    energy = clauses[3] if len(clauses) > 3 else ""
    return {
        "love": love,
        "work": work,
        "money": money,
        "energy": energy,
    }


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
    items: dict[str, dict[str, Any]] = {}
    used_sources: list[str] = []
    fallback_used = False
    for sign in SIGNS:
        fallback = SIGN_FALLBACKS[sign]
        if not base:
            fallback_used = True
            items[sign] = {
                "sign": sign,
                **fallback,
                "source_names": [],
                "source_snippets": [],
                "confidence": 0.2,
                "fallback_used": True,
                "tone": SIGN_MOOD_HINTS[sign],
            }
            continue
        try:
            payload = json.loads(_http_get(f"{base}/{slug_map[sign]}"))
            horoscope = str(payload.get("horoscope") or "").strip()
            sections = _split_horoscope_sections(horoscope)
            merged = {
                "love": sections.get("love") or fallback["love"],
                "work": sections.get("work") or fallback["work"],
                "money": sections.get("money") or fallback["money"],
                "energy": sections.get("energy") or fallback["energy"],
                "friction": fallback["friction"],
                "advice": fallback["advice"],
            }
            source_name = urllib.parse.urlparse(base).netloc or base
            if source_name and source_name not in used_sources:
                used_sources.append(source_name)
            snippet = horoscope[:180]
            items[sign] = {
                "sign": sign,
                **merged,
                "source_names": [source_name],
                "source_snippets": [snippet] if snippet else [],
                "confidence": 0.8 if horoscope else 0.45,
                "fallback_used": not bool(horoscope),
                "tone": SIGN_MOOD_HINTS[sign],
                "text": horoscope or f"{merged['love']} {merged['work']}",
            }
            if not horoscope:
                fallback_used = True
        except Exception:
            fallback_used = True
            items[sign] = {
                "sign": sign,
                **fallback,
                "source_names": [],
                "source_snippets": [],
                "confidence": 0.3,
                "fallback_used": True,
                "tone": SIGN_MOOD_HINTS[sign],
                "text": f"{fallback['love']} {fallback['work']}",
            }
    return {
        "signs": items,
        "sources": resolved_sources,
        "used_sources": used_sources,
        "configured_sources": sources,
        "fallback_used": fallback_used,
    }
