from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from app.services.barcello import NEGATIVE_KEYWORDS
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)

DEFAULT_SUMMARY_CONFIG: dict[str, Any] = {
    "tiers": {
        "role1": {
            "label": "PLUS",
            "sections": ["themes", "moments", "notes"],
            "limits": {
                "themes": 6,
                "moments": 5,
                "quotes": 4,
                "dynamics": 2,
            },
        },
        "role2": {
            "label": "PRO",
            "sections": ["themes", "moments", "quotes", "notes"],
            "limits": {
                "themes": 6,
                "moments": 10,
                "quotes": 6,
                "dynamics": 3,
            },
        },
        "role3": {
            "label": "PRO MAX",
            "sections": ["themes", "moments", "quotes", "dynamics"],
            "limits": {
                "themes": 8,
                "moments": 12,
                "quotes": 8,
                "dynamics": 4,
            },
        },
        "mod": {
            "label": "MOD",
            "sections": [
                "themes",
                "moments",
                "quotes",
                "dynamics",
                "impact",
                "advice",
                "metrics",
                "ai",
            ],
            "limits": {
                "themes": 10,
                "moments": 15,
                "quotes": 10,
                "dynamics": 5,
                "impact": 3,
            },
        },
    },
    "ai_enabled_tiers": ["role2", "role3", "mod"],
    "fallback_local": True,
    "evidence_mode": {
        "links_off": 2,
        "links_on": 4,
        "mod_explain_links": 3,
    },
    "include_names_when_score": {
        "default": "green_only",
        "mod": "always",
    },
    "max_messages": 600,
}

ITALIAN_STOPWORDS = {
    "che",
    "come",
    "della",
    "delle",
    "dello",
    "dell",
    "dall",
    "dai",
    "dagli",
    "dal",
    "dei",
    "del",
    "della",
    "e",
    "è",
    "gli",
    "il",
    "la",
    "le",
    "lo",
    "ma",
    "non",
    "per",
    "poi",
    "piu",
    "più",
    "se",
    "si",
    "su",
    "un",
    "una",
    "uno",
    "tra",
    "con",
    "nel",
    "nei",
    "nelle",
    "nella",
    "allo",
    "alla",
    "agli",
    "alle",
}

POSITIVE_KEYWORDS = {
    "grazie",
    "ottimo",
    "bene",
    "perfetto",
    "bravo",
    "ok",
    "grande",
    "cool",
    "amazing",
    "top",
}


@dataclass
class SummaryItem:
    ts: str
    text: str
    author_id: Optional[str]
    message_ids: list[str] = field(default_factory=list)
    cluster_key: Optional[str] = None


@dataclass
class SummaryQuote:
    ts: str
    text: str
    author_id: Optional[str]
    message_ids: list[str] = field(default_factory=list)


@dataclass
class SummaryImpact:
    author_id: Optional[str]
    reason: str
    ts: str
    message_id: Optional[str]


@dataclass
class SummaryResult:
    themes: list[str]
    moments: list[SummaryItem]
    quotes: list[SummaryQuote]
    dynamics: list[SummaryItem]
    degrade: list[SummaryImpact]
    invigorate: list[SummaryImpact]
    advice: list[str]
    metrics: dict[str, Any]
    ai_status: dict[str, Any]
    cache_hit: bool = False


class SummaryService:
    def __init__(self, database: DatabaseService, ai_service: Any | None = None, *, cache_ttl_seconds: int = 90) -> None:
        self._database = database
        self._ai_service = ai_service
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[tuple[str, str, str, str, str, bool, bool], tuple[float, SummaryResult, str | None]] = {}
        self._response_format_supported: bool | None = None

    async def get_config(self) -> dict[str, Any]:
        raw = await self._database.get_setting("summary.config")
        if not raw:
            return DEFAULT_SUMMARY_CONFIG
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in setting summary.config")
            return DEFAULT_SUMMARY_CONFIG
        if not isinstance(parsed, dict):
            return DEFAULT_SUMMARY_CONFIG
        return _merge_dict(DEFAULT_SUMMARY_CONFIG, parsed)

    async def build_summary(
        self,
        *,
        guild_id: str,
        channel_id: str,
        start_ts: str,
        end_ts: str,
        tier: str,
        include_names: bool,
        ai_allowed: bool,
        evidence_mode: bool,
        voice_context: bool,
        config: dict[str, Any],
        barcello_metrics: dict[str, Any],
        max_message_ts: Optional[str],
        messages: list[dict[str, Any]],
    ) -> SummaryResult:
        cache_key = (guild_id, channel_id, start_ts, end_ts, tier, evidence_mode, voice_context)
        now_epoch = datetime.now(timezone.utc).timestamp()
        cached = self._cache.get(cache_key)
        if cached and cached[0] > now_epoch:
            if max_message_ts and cached[2] and max_message_ts <= cached[2]:
                cached[1].cache_hit = True
                return cached[1]

        local_summary = self._build_local_summary(
            messages=messages,
            include_names=include_names,
            config=config,
            barcello_metrics=barcello_metrics,
            tier=tier,
        )

        ai_enabled_tiers = set(config.get("ai_enabled_tiers", []) or [])
        use_ai = ai_allowed and tier in ai_enabled_tiers and self._ai_service is not None

        summary = local_summary
        ai_status: dict[str, Any] = {
            "enabled": False,
            "provider": None,
            "model": None,
            "fallback": False,
            "reason": "disabled",
        }
        if use_ai:
            ai_status.update({"enabled": True, "provider": "openai"})
            model = self._ai_service.get_model("summary") if self._ai_service else None
            client = self._ai_service.client() if self._ai_service else None
            ai_status["model"] = model
            if not model or not client:
                ai_status.update({"enabled": False, "fallback": True, "reason": "missing_key"})
            else:
                try:
                    ai_payload = await self._call_ai(
                        client=client,
                        model=model,
                        messages=messages,
                        include_names=include_names,
                        tier=tier,
                        barcello_metrics=barcello_metrics,
                    )
                    if ai_payload:
                        summary = self._merge_ai_summary(local_summary, ai_payload, include_names)
                        ai_status.update({"enabled": True, "reason": "ok"})
                    else:
                        ai_status.update({"enabled": False, "fallback": True, "reason": "invalid_json"})
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Summary AI failed")
                    ai_status.update({"enabled": False, "fallback": True, "reason": f"exception:{exc.__class__.__name__}"})

        summary.ai_status = ai_status
        expires = now_epoch + self._cache_ttl
        self._cache[cache_key] = (expires, summary, max_message_ts)
        return summary

    def _build_local_summary(
        self,
        *,
        messages: list[dict[str, Any]],
        include_names: bool,
        config: dict[str, Any],
        barcello_metrics: dict[str, Any],
        tier: str,
    ) -> SummaryResult:
        themes = self._extract_themes(messages, config, tier)
        moments = self._extract_moments(messages, config, tier)
        quotes = self._extract_quotes(messages, config, tier)
        dynamics = self._extract_dynamics(barcello_metrics, messages, config, tier)
        degrade, invigorate = self._extract_impact(messages, config, tier)
        advice = self._build_mod_advice(barcello_metrics)
        return SummaryResult(
            themes=themes,
            moments=moments,
            quotes=quotes,
            dynamics=dynamics,
            degrade=degrade,
            invigorate=invigorate,
            advice=advice,
            metrics=barcello_metrics,
            ai_status={"enabled": False, "provider": None, "model": None, "fallback": False, "reason": "local"},
        )

    async def _call_ai(
        self,
        *,
        client: Any,
        model: str,
        messages: list[dict[str, Any]],
        include_names: bool,
        tier: str,
        barcello_metrics: dict[str, Any],
    ) -> dict[str, Any] | None:
        snippet = [
            {
                "ts": msg.get("ts"),
                "author_id": msg.get("author_id"),
                "content": msg.get("content"),
            }
            for msg in messages[:80]
        ]
        system_prompt = (
            "Scrivi in italiano e restituisci SOLO JSON valido. "
            "Non inventare dettagli. "
            "Se include_names=false NON includere nomi persone, usa 'un utente'. "
            "TEMI devono essere solo keyword brevi (no nomi). "
            "Struttura JSON: themes[], moments[], quotes[], dynamics[], degrade_list[], invigorate_list[], advice[]. "
            "moments: oggetti con 'ts','text','message_ids'. "
            "quotes: oggetti con 'ts','text','message_ids'. "
            "dynamics: oggetti con 'ts','text','message_ids'. "
            "degrade_list/invigorate_list: oggetti con 'author_id','reason','ts','message_id'. "
            "advice: lista stringhe brevi."
        )
        user_payload = json.dumps(
            {
                "tier": tier,
                "include_names": include_names,
                "metrics": barcello_metrics,
                "messages": snippet,
            },
            ensure_ascii=False,
        )
        if self._response_format_supported is False:
            response = await client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
            )
        else:
            try:
                response = await client.responses.create(
                    model=model,
                    response_format={"type": "json_object"},
                    input=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_payload},
                    ],
                )
                self._response_format_supported = True
            except TypeError as exc:
                if "response_format" not in str(exc):
                    raise
                if self._response_format_supported is not False:
                    logger.info("Summary AI response_format unsupported; using JSON-in-text mode")
                self._response_format_supported = False
                response = await client.responses.create(
                    model=model,
                    input=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_payload},
                    ],
                )
        text = _extract_ai_text(response)
        return _parse_json_safe(text)

    def _merge_ai_summary(
        self,
        local_summary: SummaryResult,
        ai_payload: dict[str, Any],
        include_names: bool,
    ) -> SummaryResult:
        def _normalize_items(raw: Any, *, is_quote: bool = False) -> list[SummaryItem | SummaryQuote]:
            if not isinstance(raw, list):
                return []
            output: list[SummaryItem | SummaryQuote] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                ts = str(item.get("ts") or "")
                text = str(item.get("text") or "").strip()
                if not ts or not text:
                    continue
                message_ids = [str(mid) for mid in (item.get("message_ids") or []) if str(mid)]
                author_id = str(item.get("author_id") or "") or None
                if is_quote:
                    output.append(SummaryQuote(ts=ts, text=text, author_id=author_id, message_ids=message_ids))
                else:
                    output.append(SummaryItem(ts=ts, text=text, author_id=author_id, message_ids=message_ids))
            return output

        themes = [str(item).strip() for item in (ai_payload.get("themes") or []) if str(item).strip()]
        moments = _normalize_items(ai_payload.get("moments"))
        quotes = _normalize_items(ai_payload.get("quotes"), is_quote=True)
        dynamics = _normalize_items(ai_payload.get("dynamics"))
        advice = [str(item).strip() for item in (ai_payload.get("advice") or []) if str(item).strip()]
        degrade = _normalize_impacts(ai_payload.get("degrade_list"))
        invigorate = _normalize_impacts(ai_payload.get("invigorate_list"))
        if not themes:
            themes = local_summary.themes
        if not moments:
            moments = local_summary.moments
        if not quotes:
            quotes = local_summary.quotes
        if not dynamics:
            dynamics = local_summary.dynamics
        if not advice:
            advice = local_summary.advice
        if not degrade:
            degrade = local_summary.degrade
        if not invigorate:
            invigorate = local_summary.invigorate
        return SummaryResult(
            themes=themes,
            moments=cast_items(moments, SummaryItem),
            quotes=cast_items(quotes, SummaryQuote),
            dynamics=cast_items(dynamics, SummaryItem),
            degrade=degrade,
            invigorate=invigorate,
            advice=advice,
            metrics=local_summary.metrics,
            ai_status=local_summary.ai_status,
        )

    def _extract_themes(self, messages: list[dict[str, Any]], config: dict[str, Any], tier: str) -> list[str]:
        counts: dict[str, int] = {}
        for msg in messages:
            content = msg.get("content") or ""
            for word in _extract_keywords(content):
                if word in ITALIAN_STOPWORDS:
                    continue
                counts[word] = counts.get(word, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        limit = _tier_limit(config, tier, "themes", 6)
        themes = [word for word, _ in ranked[:limit]]
        return themes

    def _extract_moments(self, messages: list[dict[str, Any]], config: dict[str, Any], tier: str) -> list[SummaryItem]:
        limit = _tier_limit(config, tier, "moments", 5)
        clusters: dict[str, int] = {}
        items: list[SummaryItem] = []
        for msg in sorted(messages, key=lambda item: len(item.get("content") or ""), reverse=True):
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            cluster_key = _cluster_key(content)
            if clusters.get(cluster_key, 0) >= 2:
                continue
            clusters[cluster_key] = clusters.get(cluster_key, 0) + 1
            items.append(
                SummaryItem(
                    ts=msg.get("ts") or "",
                    text=_shorten(content),
                    author_id=msg.get("author_id"),
                    message_ids=[str(msg.get("message_id"))] if msg.get("message_id") else [],
                    cluster_key=cluster_key,
                )
            )
            if len(items) >= limit:
                break
        return items

    def _extract_quotes(self, messages: list[dict[str, Any]], config: dict[str, Any], tier: str) -> list[SummaryQuote]:
        limit = _tier_limit(config, tier, "quotes", 6)
        candidates: list[dict[str, Any]] = []
        for msg in messages:
            content = (msg.get("content") or "").strip()
            if len(content) < 24:
                continue
            if "\"" in content or "“" in content or len(content) > 80:
                candidates.append(msg)
        output: list[SummaryQuote] = []
        for msg in candidates[:limit]:
            output.append(
                SummaryQuote(
                    ts=msg.get("ts") or "",
                    text=_shorten(msg.get("content") or ""),
                    author_id=msg.get("author_id"),
                    message_ids=[str(msg.get("message_id"))] if msg.get("message_id") else [],
                )
            )
        return output

    def _extract_dynamics(
        self,
        barcello_metrics: dict[str, Any],
        messages: list[dict[str, Any]],
        config: dict[str, Any],
        tier: str,
    ) -> list[SummaryItem]:
        limit = _tier_limit(config, tier, "dynamics", 3)
        dynamics: list[SummaryItem] = []
        reply_war = bool(barcello_metrics.get("reply_war"))
        top_author_share = float(barcello_metrics.get("top1_author_share") or 0)
        negativity_hits = int(barcello_metrics.get("negativity_hits") or 0)
        if reply_war:
            dynamics.append(SummaryItem(ts=_pick_ts(messages), text="Botta e risposta fitto, ritmo acceso.", author_id=None))
        if top_author_share > 0.4:
            dynamics.append(
                SummaryItem(ts=_pick_ts(messages), text="Conversazione concentrata su pochi utenti.", author_id=None)
            )
        if negativity_hits > 0:
            dynamics.append(
                SummaryItem(ts=_pick_ts(messages), text="Toni pungenti o negativi compaiono nella finestra.", author_id=None)
            )
        if not dynamics:
            dynamics.append(SummaryItem(ts=_pick_ts(messages), text="Dinamica complessivamente lineare.", author_id=None))
        return dynamics[:limit]

    def _extract_impact(
        self,
        messages: list[dict[str, Any]],
        config: dict[str, Any],
        tier: str,
    ) -> tuple[list[SummaryImpact], list[SummaryImpact]]:
        limit = _tier_limit(config, tier, "impact", 3)
        author_scores: dict[str, dict[str, Any]] = {}
        for msg in messages:
            author_id = str(msg.get("author_id") or "")
            if not author_id:
                continue
            content = (msg.get("content") or "").lower()
            neg_hits = sum(content.count(word) for word in NEGATIVE_KEYWORDS)
            pos_hits = sum(content.count(word) for word in POSITIVE_KEYWORDS)
            record = author_scores.setdefault(author_id, {"neg": 0, "pos": 0, "last": msg})
            record["neg"] += neg_hits
            record["pos"] += pos_hits
            record["last"] = msg
        degrade_ranked = sorted(author_scores.items(), key=lambda item: item[1]["neg"], reverse=True)
        invigorate_ranked = sorted(author_scores.items(), key=lambda item: item[1]["pos"], reverse=True)
        degrade: list[SummaryImpact] = []
        invigorate: list[SummaryImpact] = []
        for author_id, data in degrade_ranked[:limit]:
            if data["neg"] <= 0:
                continue
            msg = data["last"]
            degrade.append(
                SummaryImpact(
                    author_id=author_id,
                    reason="Toni pungenti o callout frequenti.",
                    ts=msg.get("ts") or "",
                    message_id=str(msg.get("message_id")) if msg.get("message_id") else None,
                )
            )
        for author_id, data in invigorate_ranked[:limit]:
            if data["pos"] <= 0:
                continue
            msg = data["last"]
            invigorate.append(
                SummaryImpact(
                    author_id=author_id,
                    reason="Messaggi positivi e distensivi.",
                    ts=msg.get("ts") or "",
                    message_id=str(msg.get("message_id")) if msg.get("message_id") else None,
                )
            )
        return degrade, invigorate

    def _build_mod_advice(self, metrics: dict[str, Any]) -> list[str]:
        advice: list[str] = []
        if metrics.get("reply_war"):
            advice.append("Interrompi il ping-pong con un reminder di tono.")
        if float(metrics.get("caps_ratio") or 0) > 0.3:
            advice.append("Chiedi di ridurre il CAPSLOCK per evitare escalation.")
        if int(metrics.get("negativity_hits") or 0) > 0:
            advice.append("Invita a riformulare con un linguaggio più neutro.")
        if not advice:
            advice.append("Mantieni un ritmo calmo e distribuisci i turni.")
        return advice


def _extract_keywords(text: str) -> Iterable[str]:
    words = re.findall(r"[a-zA-Zàèéìòù0-9]{3,}", text.lower())
    return [word for word in words if len(word) >= 3]


def _cluster_key(text: str) -> str:
    keywords = _extract_keywords(text)
    if not keywords:
        return "misc"
    return "_".join(sorted(set(keywords))[:3])


def _shorten(text: str, limit: int = 140) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _pick_ts(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""
    return messages[0].get("ts") or ""


def _extract_ai_text(response: Any) -> str:
    output_text = getattr(response, "output_text", "") or ""
    if output_text:
        return output_text
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if not text and getattr(content, "type", None) in {"output_text", "text"}:
                text = getattr(content, "text", "")
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def _parse_json_safe(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    raw = text.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    if "```" in raw:
        start = raw.find("```")
        if start != -1:
            fence_lang_end = raw.find("\n", start + 3)
            if fence_lang_end != -1:
                end = raw.find("```", fence_lang_end + 1)
                if end != -1:
                    fenced = raw[fence_lang_end:end].strip()
                    try:
                        parsed = json.loads(fenced)
                        return parsed if isinstance(parsed, dict) else None
                    except json.JSONDecodeError:
                        return None
    start_obj = raw.find("{")
    end_obj = raw.rfind("}")
    if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
        candidate = raw[start_obj : end_obj + 1]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _normalize_impacts(raw: Any) -> list[SummaryImpact]:
    if not isinstance(raw, list):
        return []
    output: list[SummaryImpact] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        author_id = str(item.get("author_id") or "") or None
        reason = str(item.get("reason") or "").strip()
        ts = str(item.get("ts") or "")
        message_id = str(item.get("message_id") or "") or None
        if not reason or not ts:
            continue
        output.append(SummaryImpact(author_id=author_id, reason=reason, ts=ts, message_id=message_id))
    return output


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged.get(key, {}), value)
        else:
            merged[key] = value
    return merged


def _tier_limit(config: dict[str, Any], tier: str, key: str, fallback: int) -> int:
    limits = config.get("tiers", {}).get(tier, {}).get("limits", {})
    if isinstance(limits, dict) and key in limits:
        try:
            return int(limits.get(key))
        except (TypeError, ValueError):
            return fallback
    return fallback


def cast_items(items: Iterable[Any], target: type) -> list[Any]:
    output: list[Any] = []
    for item in items:
        if isinstance(item, target):
            output.append(item)
    return output
