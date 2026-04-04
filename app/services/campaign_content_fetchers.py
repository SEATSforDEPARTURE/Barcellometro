from __future__ import annotations

import json
import logging
import re
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

logger = logging.getLogger(__name__)

NEWS_SOURCE_CATALOG = [
    {
        "value": "ansa",
        "label": "ansa.it",
        "url": "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",
        "aliases": ["ansa", "ansa.it", "www.ansa.it"],
    },
    {
        "value": "repubblica",
        "label": "repubblica.it",
        "url": "https://www.repubblica.it/rss/homepage/rss2.0.xml",
        "aliases": ["repubblica", "repubblica.it", "www.repubblica.it"],
    },
    {
        "value": "ilpost",
        "label": "ilpost.it",
        "url": "https://www.ilpost.it/feed/",
        "aliases": ["ilpost", "ilpost.it", "www.ilpost.it"],
    },
    {
        "value": "open",
        "label": "open.online",
        "url": "https://www.open.online/feed/",
        "aliases": ["open", "open.online", "www.open.online"],
    },
    {
        "value": "fanpage",
        "label": "fanpage.it",
        "url": "https://www.fanpage.it/feed/",
        "aliases": ["fanpage", "fanpage.it", "www.fanpage.it"],
    },
    {
        "value": "wired",
        "label": "wired.it",
        "url": "https://www.wired.it/feed/rss",
        "aliases": ["wired", "wired.it", "www.wired.it"],
    },
    {
        "value": "corriere",
        "label": "corriere.it",
        "url": "https://xml2.corriereobjects.it/rss/homepage.xml",
        "aliases": ["corriere", "corriere.it", "www.corriere.it"],
    },
]

NEWS_CATEGORY_CATALOG = [
    {"value": "cronaca", "label": "Cronaca", "aliases": ["cronaca"]},
    {"value": "politica", "label": "Politica", "aliases": ["politica"]},
    {"value": "sport", "label": "Sport", "aliases": ["sport"]},
    {"value": "spettacolo", "label": "Spettacolo", "aliases": ["spettacolo"]},
    {"value": "gossip", "label": "Gossip", "aliases": ["gossip"]},
    {"value": "tecnologia", "label": "Tecnologia", "aliases": ["tecnologia", "tech"]},
    {"value": "economia", "label": "Economia", "aliases": ["economia"]},
    {"value": "mondo", "label": "Mondo", "aliases": ["mondo", "esteri"]},
    {"value": "viral", "label": "Viral", "aliases": ["viral"]},
    {"value": "trash", "label": "Trash", "aliases": ["trash"]},
    {"value": "curiosita", "label": "Curiosità", "aliases": ["curiosita", "curiosità"]},
    {"value": "varie", "label": "Varie", "aliases": ["varie"]},
]

NEWS_SOURCE_MAP = {entry["value"]: entry["url"] for entry in NEWS_SOURCE_CATALOG}
SUPPORTED_NEWS_CATEGORIES = [entry["value"] for entry in NEWS_CATEGORY_CATALOG]

NEWS_CLASSIFICATION_RULES: dict[str, dict[str, Any]] = {
    "cronaca": {
        "label": "Cronaca",
        "aliases": ["cronaca", "fatti", "cronache"],
        "feed_categories": ["cronaca", "crime", "locali", "attualita"],
        "keywords": [
            "incidente",
            "arresto",
            "morto",
            "ferito",
            "procura",
            "carabinieri",
            "polizia",
            "omicidio",
            "incendio",
            "rapina",
            "tribunale",
            "sequestro",
        ],
    },
    "politica": {
        "label": "Politica",
        "aliases": ["politica", "governo", "parlamento"],
        "feed_categories": ["politica", "governo", "istituzioni"],
        "keywords": ["governo", "parlamento", "decreto", "senato", "camera", "premier", "ministro", "elezioni", "partito"],
    },
    "sport": {
        "label": "Sport",
        "aliases": ["sport", "calcio", "tennis", "formula 1", "motogp"],
        "feed_categories": ["sport", "calcio", "motori", "tennis"],
        "keywords": ["campionato", "gol", "partita", "allenatore", "serie a", "champions", "atleta", "gara", "vittoria"],
    },
    "spettacolo": {
        "label": "Spettacolo",
        "aliases": ["spettacolo", "cultura pop", "show"],
        "feed_categories": ["spettacoli", "tv", "cinema", "musica", "showbiz"],
        "keywords": ["cinema", "film", "serie tv", "palco", "teatro", "concerto", "festival", "spettacolo", "attore", "attrice"],
    },
    "gossip": {
        "label": "Gossip",
        "aliases": ["gossip", "vip", "celebrita", "celebrità"],
        "feed_categories": ["gossip", "vip", "people"],
        "keywords": ["vip", "celeb", "fidanzata", "fidanzato", "coppia", "paparazzi", "retroscena", "indiscrezione"],
    },
    "tecnologia": {
        "label": "Tecnologia",
        "aliases": ["tecnologia", "tech", "digitale", "innovazione"],
        "feed_categories": ["tecnologia", "tech", "scienza", "digitale"],
        "keywords": ["startup", "intelligenza artificiale", "ai", "software", "smartphone", "app", "chip", "digitale", "cyber"],
    },
    "economia": {
        "label": "Economia",
        "aliases": ["economia", "finanza", "mercati"],
        "feed_categories": ["economia", "finanza", "business", "borsa"],
        "keywords": ["borsa", "spread", "inflazione", "pil", "mercato", "aziende", "banche", "tasso", "stipendi", "finanza"],
    },
    "mondo": {
        "label": "Mondo",
        "aliases": ["mondo", "esteri", "internazionale", "internazionali"],
        "feed_categories": ["esteri", "mondo", "internazionale"],
        "keywords": ["usa", "cina", "russia", "ucraina", "gaza", "israele", "europa", "onu", "nato", "internazionale", "esteri"],
    },
    "viral": {
        "label": "Viral",
        "aliases": ["viral", "virale", "social"],
        "feed_categories": ["viral", "web", "social"],
        "keywords": ["video", "social", "tiktok", "instagram", "virale", "web", "trend", "online", "meme", "utenti", "clip"],
    },
    "trash": {
        "label": "Trash",
        "aliases": ["trash", "trash tv", "polemica"],
        "feed_categories": ["trash", "tv", "reality", "gossip"],
        "keywords": ["reality", "scandalo", "polemica", "siparietto", "sfuriata", "lite", "trash tv", "talk show", "gossip spinto"],
        "source_hints": ["fanpage.it", "open.online"],
    },
    "curiosita": {
        "label": "Curiosità",
        "aliases": ["curiosita", "curiosità", "insolito"],
        "feed_categories": ["curiosita", "curiosità", "insolito"],
        "keywords": ["incredibile", "record", "scoperta", "singolare", "insolito", "assurdo", "curioso"],
    },
    "varie": {
        "label": "Varie",
        "aliases": ["varie", "generale", "topnews"],
        "feed_categories": ["varie", "generale", "topnews"],
        "keywords": [],
    },
}


def _fold_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in normalized if not unicodedata.combining(char)).strip().lower()


def _build_news_source_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for entry in NEWS_SOURCE_CATALOG:
        canonical = str(entry["value"]).strip().lower()
        aliases[canonical] = canonical
        aliases[_fold_token(canonical)] = canonical
        label = str(entry.get("label") or "").strip().lower()
        if label:
            aliases[label] = canonical
            aliases[_fold_token(label)] = canonical
        for alias in entry.get("aliases", []):
            alias_clean = str(alias).strip().lower()
            if alias_clean:
                aliases[alias_clean] = canonical
                aliases[_fold_token(alias_clean)] = canonical
                if "." in alias_clean and "://" not in alias_clean:
                    aliases[f"https://{alias_clean}"] = canonical
                    aliases[f"http://{alias_clean}"] = canonical
        url = str(entry.get("url") or "").strip().lower()
        if url.startswith(("http://", "https://")):
            aliases[url] = canonical
            host = url.split("//", 1)[1].split("/", 1)[0].strip()
            if host:
                aliases[host] = canonical
                aliases[_fold_token(host)] = canonical
                aliases[f"https://{host}"] = canonical
                aliases[f"http://{host}"] = canonical
                if host.startswith("www."):
                    aliases[host[4:]] = canonical
    return aliases


def _build_news_category_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for entry in NEWS_CATEGORY_CATALOG:
        canonical = str(entry["value"]).strip().lower()
        aliases[canonical] = canonical
        aliases[_fold_token(canonical)] = canonical
        label = str(entry.get("label") or "").strip().lower()
        if label:
            aliases[label] = canonical
            aliases[_fold_token(label)] = canonical
        for alias in entry.get("aliases", []):
            alias_clean = str(alias).strip().lower()
            if alias_clean:
                aliases[alias_clean] = canonical
                aliases[_fold_token(alias_clean)] = canonical
    return aliases


NEWS_SOURCE_ALIASES = _build_news_source_aliases()
NEWS_CATEGORY_ALIASES = _build_news_category_aliases()


def normalize_news_source_token(value: str) -> str | None:
    token = str(value or "").strip().lower()
    if not token:
        return None
    direct = NEWS_SOURCE_ALIASES.get(token) or NEWS_SOURCE_ALIASES.get(_fold_token(token))
    if direct:
        return direct
    if token.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(token)
        host = parsed.netloc.strip().lower()
        if host:
            return (
                NEWS_SOURCE_ALIASES.get(host)
                or NEWS_SOURCE_ALIASES.get(_fold_token(host))
                or (NEWS_SOURCE_ALIASES.get(host[4:]) if host.startswith("www.") else None)
            )
    return None


def normalize_news_category_token(value: str) -> str | None:
    token = str(value or "").strip().lower()
    if not token:
        return None
    return NEWS_CATEGORY_ALIASES.get(token) or NEWS_CATEGORY_ALIASES.get(_fold_token(token))

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
        canonical = normalize_news_source_token(token) or token
        mapped = NEWS_SOURCE_MAP.get(canonical)
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



def normalize_news_key(title: str, link: str) -> str:
    normalized_link = re.sub(r"[#?].*$", "", (link or "").strip().lower())
    normalized_link = normalized_link.rstrip("/")
    if normalized_link:
        return f"link:{normalized_link}"
    title_key = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    return f"title:{title_key}"


def similarity_title(a: str, b: str) -> float:
    a_tokens = re.sub(r"[^a-z0-9]+", " ", (a or "").lower()).split()
    b_tokens = re.sub(r"[^a-z0-9]+", " ", (b or "").lower()).split()
    if not a_tokens or not b_tokens:
        return 0.0
    a_set = set(a_tokens)
    b_set = set(b_tokens)
    jaccard = len(a_set & b_set) / max(1, len(a_set | b_set))
    return jaccard


def _item_quality(item: dict[str, str]) -> tuple[int, int]:
    source = (item.get("source") or "").lower()
    reliability_bonus = 2 if any(k in source for k in ["ansa", "repubblica", "corriere", "ilpost"]) else 0
    return (len(item.get("summary") or ""), reliability_bonus)


def dedupe_news_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    key_index: dict[str, int] = {}
    for item in items:
        key = normalize_news_key(item.get("title", ""), item.get("link", ""))
        if key in key_index:
            existing_idx = key_index[key]
            if _item_quality(item) > _item_quality(deduped[existing_idx]):
                deduped[existing_idx] = item
            continue
        duplicate_idx = None
        for idx, existing in enumerate(deduped):
            if similarity_title(existing.get("title", ""), item.get("title", "")) >= 0.86:
                duplicate_idx = idx
                break
        if duplicate_idx is not None:
            if _item_quality(item) > _item_quality(deduped[duplicate_idx]):
                deduped[duplicate_idx] = item
            continue
        key_index[key] = len(deduped)
        deduped.append(item)
    return deduped

def _normalize_news_categories(categories: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in categories:
        token = normalize_news_category_token(raw)
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def _extract_news_item_category_hints(node: ET.Element) -> list[str]:
    hints: list[str] = []
    for child in list(node):
        tag_name = str(child.tag or "").lower()
        if not tag_name.endswith("category") and not tag_name.endswith("subject"):
            continue
        text = str(child.text or "").strip()
        if text:
            hints.append(text)
    return hints


def _normalize_news_text(text: str) -> str:
    return re.sub(r"\s+", " ", _fold_token(text or ""))


def _contains_keyword(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    if " " in keyword:
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def classify_news_item(*, title: str, description: str, raw_categories: list[str], source: str) -> list[str]:
    title_text = _normalize_news_text(title)
    description_text = _normalize_news_text(description)
    source_text = _normalize_news_text(source)
    category_text = " ".join(_normalize_news_text(cat) for cat in raw_categories if cat)
    text_blob = " ".join(part for part in [title_text, description_text, category_text] if part).strip()
    scores: dict[str, int] = {}
    for category, rule in NEWS_CLASSIFICATION_RULES.items():
        score = 0
        for alias in rule.get("aliases", []):
            alias_norm = _normalize_news_text(alias)
            if alias_norm and _contains_keyword(text_blob, alias_norm):
                score += 3
        for feed_equivalent in rule.get("feed_categories", []):
            feed_norm = _normalize_news_text(feed_equivalent)
            if feed_norm and _contains_keyword(category_text, feed_norm):
                score += 4
        for keyword in rule.get("keywords", []):
            keyword_norm = _normalize_news_text(keyword)
            if keyword_norm and _contains_keyword(text_blob, keyword_norm):
                score += 2
        for source_hint in rule.get("source_hints", []):
            source_hint_norm = _normalize_news_text(source_hint)
            if source_hint_norm and source_hint_norm in source_text:
                score += 1
        if score > 0:
            scores[category] = score
    if not scores:
        return ["varie"]
    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], SUPPORTED_NEWS_CATEGORIES.index(pair[0])))
    top_score = ordered[0][1]
    selected = [category for category, score in ordered if score >= max(2, top_score - 2)]
    if "varie" in selected and len(selected) > 1:
        selected.remove("varie")
    return selected[:3] or ["varie"]


def fetch_news_content(sources: list[str], categories: list[str]) -> dict[str, Any]:
    normalized_categories = _normalize_news_categories(categories)
    effective_sources = _resolve_news_sources(sources)
    items: list[dict[str, str]] = []
    varie_fallback_items: list[dict[str, str]] = []
    attempted: list[str] = []
    used_sources: list[str] = []
    discarded_unclassified = 0
    per_source_total: dict[str, int] = {}
    per_category_count: dict[str, int] = {}
    for source in effective_sources:
        attempted.append(source)
        try:
            payload = _http_get(source)
            root = ET.fromstring(payload)
            found_for_source = False
            source_label = urllib.parse.urlparse(source).netloc or source
            per_source_total[source_label] = 0
            for node in root.findall(".//item"):
                per_source_total[source_label] += 1
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                description = re.sub(r"\s+", " ", (node.findtext("description") or "").strip())
                raw_categories = _extract_news_item_category_hints(node) or [node.findtext("category") or "varie"]
                classified_categories = classify_news_item(
                    title=title,
                    description=description,
                    raw_categories=raw_categories,
                    source=source_label,
                )
                if not classified_categories:
                    discarded_unclassified += 1
                    continue
                if normalized_categories:
                    selected_categories = [cat for cat in normalized_categories if cat in classified_categories]
                else:
                    selected_categories = classified_categories
                if not selected_categories:
                    if normalized_categories and "varie" in classified_categories:
                        varie_fallback_items.append(
                            {
                                "title": title[:160],
                                "link": link,
                                "summary": description[:500],
                                "category": "varie",
                                "source": source_label,
                            }
                        )
                    continue
                found_for_source = True
                for selected_category in selected_categories:
                    per_category_count[selected_category] = per_category_count.get(selected_category, 0) + 1
                    items.append(
                        {
                            "title": title[:160],
                            "link": link,
                            "summary": description[:500],
                            "category": selected_category,
                            "source": source_label,
                        }
                    )
            if found_for_source:
                used_sources.append(source)
        except Exception as exc:
            logger.warning("campaign news fetch failed for source=%s (%s)", source, exc.__class__.__name__)
            continue

    grouped: dict[str, list[dict[str, str]]] = {}
    for item in items:
        grouped.setdefault(item["category"], []).append(item)
    for category, category_items in list(grouped.items()):
        grouped[category] = dedupe_news_items(category_items)

    ordered: dict[str, list[dict[str, str]]] = {}
    for cat in normalized_categories:
        if cat in grouped and grouped[cat]:
            ordered[cat] = grouped[cat]
    if normalized_categories and not ordered:
        fallback_candidates = grouped.get("varie", []) or dedupe_news_items(varie_fallback_items)
        if fallback_candidates:
            ordered["varie"] = fallback_candidates
    for cat, cat_items in grouped.items():
        if cat not in ordered and cat_items:
            ordered[cat] = cat_items

    logger.info(
        "campaign news fetch diagnostics sources=%s requested_categories=%s read_items=%s classified_counts=%s discarded_unclassified=%d fallback=%s",
        attempted,
        normalized_categories,
        per_source_total,
        per_category_count,
        discarded_unclassified,
        bool(normalized_categories and not any(cat in ordered for cat in normalized_categories) and "varie" in ordered),
    )

    return {
        "categories": ordered,
        "sources": attempted,
        "used_sources": used_sources,
        "configured_sources": sources,
        "configured_categories": normalized_categories,
        "diagnostics": {
            "per_source_total": per_source_total,
            "per_category_count": per_category_count,
            "discarded_unclassified": discarded_unclassified,
        },
    }


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
