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
                "quotes": 3,
                "dynamics": 2,
            },
        },
        "role2": {
            "label": "PRO",
            "sections": ["themes", "moments", "quotes", "notes"],
            "limits": {
                "themes": 6,
                "moments": 10,
                "quotes": 3,
                "dynamics": 3,
            },
        },
        "role3": {
            "label": "PRO MAX",
            "sections": ["themes", "moments", "quotes", "dynamics"],
            "limits": {
                "themes": 8,
                "moments": 15,
                "quotes": 3,
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
                "quotes": 3,
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

NOISE_KEYWORDS = {
    "ciao",
    "buongiorno",
    "buonasera",
    "buonanotte",
    "ok",
    "okay",
    "aha",
    "ahah",
    "ahahah",
    "lol",
    "pls",
    "plz",
    "thanks",
    "grazie",
    "thx",
    "perfetto",
    "bene",
    "ottimo",
    "bravo",
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
    ts: Optional[str]
    text: str
    author_id: Optional[str]
    message_ids: list[str] = field(default_factory=list)
    cluster_key: Optional[str] = None


@dataclass
class SummaryQuote:
    ts: Optional[str]
    text: str
    author_id: Optional[str]
    message_ids: list[str] = field(default_factory=list)


@dataclass
class SummaryImpact:
    author_id: Optional[str]
    reason: str
    ts: Optional[str]
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
                        config=config,
                    )
                    if ai_payload:
                        self._sanitize_ai_payload(ai_payload, messages)
                    if ai_payload:
                        summary = self._merge_ai_summary(local_summary, ai_payload, include_names, config=config, tier=tier)
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

    async def build_period_description(
        self,
        *,
        tier: str,
        period_prefix: str,
        score: int,
        color: str,
        metrics: dict[str, Any],
        trend: dict[str, Any] | None,
        ai_allowed: bool,
        config: dict[str, Any],
    ) -> str | None:
        ai_enabled_tiers = set(config.get("ai_enabled_tiers", []) or [])
        use_ai = ai_allowed and tier in ai_enabled_tiers and self._ai_service is not None
        if not use_ai:
            return None
        model = self._ai_service.get_model("summary") if self._ai_service else None
        client = self._ai_service.client() if self._ai_service else None
        if not model or not client:
            return None
        try:
            text = await self._call_ai_period_description(
                client=client,
                model=model,
                period_prefix=period_prefix,
                score=score,
                color=color,
                metrics=metrics,
                trend=trend,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Summary AI period description failed")
            return None
        return _trim_period_description(text, period_prefix)

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
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        snippet = [
            {
                "ts": msg.get("ts"),
                "author_id": msg.get("author_id"),
                "content": msg.get("content"),
            }
            for msg in messages[:80]
        ]
        moments_target = _tier_limit(config, tier, "moments", 5)
        quotes_target = _tier_limit(config, tier, "quotes", 3)
        dynamics_target = _tier_limit(config, tier, "dynamics", 2)
        system_prompt = (
            "Scrivi in italiano e restituisci SOLO JSON valido. "
            "Non inventare dettagli. "
            "Se include_names=false NON includere nomi persone, usa 'un utente'. "
            "TEMI devono essere solo keyword brevi (no nomi). "
            "Descrivi gli EVENTI: non copiare il testo dei messaggi. "
            "Genera ESATTAMENTE moments_target_count momenti salienti (non accorpare). "
            "Ogni momento deve riassumere un evento/argomento e NON deve includere citazioni dirette. "
            "I momenti devono contenere message_ids con almeno un riferimento valido. "
            "dynamics devono essere descrizioni astratte, senza copiare testo. "
            "Struttura JSON: themes[], moments[], quotes[], dynamics[], degrade_list[], invigorate_list[], advice[]. "
            "moments: oggetti con 'ts','text','message_ids' (almeno un message_id di riferimento). "
            "quotes: oggetti con 'ts','text','message_ids'. "
            "dynamics: oggetti con 'ts','text','message_ids'. "
            "degrade_list/invigorate_list: oggetti con 'author_id','reason','ts','message_id'. "
            "advice: lista stringhe brevi."
        )
        user_payload = json.dumps(
            {
                "tier": tier,
                "include_names": include_names,
                "moments_target_count": moments_target,
                "quotes_target_count": quotes_target,
                "dynamics_target_count": dynamics_target,
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

    async def _call_ai_period_description(
        self,
        *,
        client: Any,
        model: str,
        period_prefix: str,
        score: int,
        color: str,
        metrics: dict[str, Any],
        trend: dict[str, Any] | None,
    ) -> str:
        emoji_map = {"verde": "🙂", "giallo": "😐", "rosso": "😟", "nero": "😨"}
        color_label = (color or "nero").lower()
        emoji = emoji_map.get(color_label, "😨")
        compact_metrics = {
            "msg_per_min": metrics.get("msg_per_min"),
            "reply_war": metrics.get("reply_war"),
            "top1_author_share": metrics.get("top1_author_share"),
            "negativity_hits": metrics.get("negativity_hits"),
            "mentions_per_msg": metrics.get("mentions_per_msg"),
            "burst_ratio": metrics.get("burst_ratio"),
        }
        system_prompt = (
            "Scrivi in italiano. Restituisci una sola frase (max 120 caratteri), senza elenco puntato. "
            "Non copiare testo da messaggi. "
            "Inizia con il prefisso fornito e continua con 'il barcello è stato ...'. "
            "Inserisci una sola emoji coerente con il colore fornito."
        )
        user_payload = json.dumps(
            {
                "period_prefix": period_prefix,
                "score": score,
                "color": color_label,
                "emoji": emoji,
                "trend": trend,
                "metrics": compact_metrics,
            },
            ensure_ascii=False,
        )
        response = await client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
        )
        return _extract_ai_text(response)

    def _merge_ai_summary(
        self,
        local_summary: SummaryResult,
        ai_payload: dict[str, Any],
        include_names: bool,
        *,
        config: dict[str, Any],
        tier: str,
    ) -> SummaryResult:
        def _normalize_items(raw: Any, *, is_quote: bool = False) -> list[SummaryItem | SummaryQuote]:
            if not isinstance(raw, list):
                return []
            output: list[SummaryItem | SummaryQuote] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                ts = item.get("ts")
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                message_ids = [str(mid) for mid in (item.get("message_ids") or []) if str(mid)]
                author_id = str(item.get("author_id") or "") or None
                if is_quote:
                    output.append(
                        SummaryQuote(
                            ts=_normalize_ts_value(ts),
                            text=text,
                            author_id=author_id,
                            message_ids=message_ids,
                        )
                    )
                else:
                    output.append(
                        SummaryItem(
                            ts=_normalize_ts_value(ts),
                            text=text,
                            author_id=author_id,
                            message_ids=message_ids,
                        )
                    )
            return output

        themes = [str(item).strip() for item in (ai_payload.get("themes") or []) if str(item).strip()]
        moments = _normalize_items(ai_payload.get("moments"))
        quotes = _normalize_items(ai_payload.get("quotes"), is_quote=True)
        dynamics = _normalize_items(ai_payload.get("dynamics"))
        advice = [str(item).strip() for item in (ai_payload.get("advice") or []) if str(item).strip()]
        degrade = _normalize_impacts(ai_payload.get("degrade_list"))
        invigorate = _normalize_impacts(ai_payload.get("invigorate_list"))
        moment_limit = _tier_limit(config, tier, "moments", 5)
        quote_limit = _tier_limit(config, tier, "quotes", 3)
        dynamic_limit = _tier_limit(config, tier, "dynamics", 2)
        if not themes:
            themes = local_summary.themes
        if not moments:
            moments = local_summary.moments
        if len(moments) < moment_limit:
            existing_text = {item.text for item in moments}
            for item in local_summary.moments:
                if item.text in existing_text:
                    continue
                moments.append(item)
                existing_text.add(item.text)
                if len(moments) >= moment_limit:
                    break
            if len(moments) < moment_limit:
                logger.warning("Summary AI returned %s moments; expected %s", len(moments), moment_limit)
        if len(moments) > moment_limit:
            moments = moments[:moment_limit]
        if not quotes:
            quotes = local_summary.quotes
        if len(quotes) > quote_limit:
            quotes = quotes[:quote_limit]
        if not dynamics:
            dynamics = local_summary.dynamics
        if len(dynamics) > dynamic_limit:
            dynamics = dynamics[:dynamic_limit]
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

    def _sanitize_ai_payload(self, payload: dict[str, Any], messages: list[dict[str, Any]]) -> None:
        message_ts_map = {
            str(msg.get("message_id")): msg.get("ts")
            for msg in messages
            if msg.get("message_id") and msg.get("ts")
        }
        logged_invalid = False

        def normalize_ts(value: Any, message_ids: list[str]) -> Optional[str]:
            nonlocal logged_invalid
            ts = _normalize_ts_value(value)
            if ts:
                return ts
            for message_id in message_ids:
                candidate = _normalize_ts_value(message_ts_map.get(message_id))
                if candidate:
                    if not logged_invalid:
                        logger.debug("Summary AI sanitized invalid ts")
                        logged_invalid = True
                    return candidate
            if not logged_invalid and value:
                logger.debug("Summary AI sanitized invalid ts")
                logged_invalid = True
            return None

        def sanitize_items(key: str) -> None:
            raw_items = payload.get(key)
            if not isinstance(raw_items, list):
                return
            sanitized: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                message_ids = [str(mid) for mid in (item.get("message_ids") or []) if str(mid)]
                if not message_ids and item.get("primary_ref"):
                    message_ids = [str(item.get("primary_ref"))]
                if not message_ids and item.get("refs"):
                    message_ids = [str(mid) for mid in (item.get("refs") or []) if str(mid)]
                ts = normalize_ts(item.get("ts"), message_ids)
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                sanitized.append(
                    {
                        "ts": ts,
                        "text": text,
                        "author_id": item.get("author_id"),
                        "message_ids": message_ids,
                    }
                )
            payload[key] = sanitized

        def sanitize_impacts(key: str) -> None:
            raw_items = payload.get(key)
            if not isinstance(raw_items, list):
                return
            sanitized: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                message_id = str(item.get("message_id") or "") or None
                ts = normalize_ts(item.get("ts"), [message_id] if message_id else [])
                reason = str(item.get("reason") or "").strip()
                if not reason:
                    continue
                sanitized.append(
                    {
                        "author_id": item.get("author_id"),
                        "reason": reason,
                        "ts": ts,
                        "message_id": message_id,
                    }
                )
            payload[key] = sanitized

        sanitize_items("moments")
        sanitize_items("quotes")
        sanitize_items("dynamics")
        sanitize_impacts("degrade_list")
        sanitize_impacts("invigorate_list")

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
        segments = _segment_messages(messages)
        if not segments:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        for segment in segments:
            score = (
                segment["message_count"]
                + segment["author_count"] * 2
                + segment["mentions"]
                + segment["burstiness"]
            )
            scored.append((score, segment))
        top_segments = [segment for _, segment in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]
        top_segments.sort(key=lambda segment: segment["start_ts"] or "")
        items: list[SummaryItem] = []
        for segment in top_segments:
            text = _build_segment_summary(segment)
            message_ids = segment["message_ids"]
            items.append(
                SummaryItem(
                    ts=segment["representative_ts"],
                    text=text,
                    author_id=segment.get("top_author_id"),
                    message_ids=message_ids[:3],
                    cluster_key=segment.get("cluster_key"),
                )
            )
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
                    ts=msg.get("ts") or None,
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
        primary_id = _pick_message_id(messages)
        top_author = _pick_top_author_id(messages)
        reply_war = bool(barcello_metrics.get("reply_war"))
        top_author_share = float(barcello_metrics.get("top1_author_share") or 0)
        negativity_hits = int(barcello_metrics.get("negativity_hits") or 0)
        if reply_war:
            dynamics.append(
                SummaryItem(
                    ts=_pick_ts(messages),
                    text="Botta e risposta fitto, ritmo acceso.",
                    author_id=top_author,
                    message_ids=[primary_id] if primary_id else [],
                )
            )
        if top_author_share > 0.4:
            dynamics.append(
                SummaryItem(
                    ts=_pick_ts(messages),
                    text="Conversazione concentrata su pochi utenti.",
                    author_id=top_author,
                    message_ids=[primary_id] if primary_id else [],
                )
            )
        if negativity_hits > 0:
            dynamics.append(
                SummaryItem(
                    ts=_pick_ts(messages),
                    text="Toni pungenti o negativi compaiono nella finestra.",
                    author_id=top_author,
                    message_ids=[primary_id] if primary_id else [],
                )
            )
        if not dynamics:
            dynamics.append(
                SummaryItem(
                    ts=_pick_ts(messages),
                    text="Dinamica complessivamente lineare.",
                    author_id=top_author,
                    message_ids=[primary_id] if primary_id else [],
                )
            )
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
                    ts=msg.get("ts") or None,
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
                    ts=msg.get("ts") or None,
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


def _shorten(text: str, limit: int = 140) -> str:
    cleaned = " ".join(text.split())
    return cleaned


def _pick_ts(messages: list[dict[str, Any]]) -> Optional[str]:
    if not messages:
        return None
    return messages[0].get("ts") or None


def _pick_message_id(messages: list[dict[str, Any]]) -> Optional[str]:
    for msg in messages:
        message_id = msg.get("message_id")
        if message_id:
            return str(message_id)
    return None


def _pick_top_author_id(messages: list[dict[str, Any]]) -> Optional[str]:
    counts: dict[str, int] = {}
    for msg in messages:
        author_id = str(msg.get("author_id") or "")
        if not author_id:
            continue
        counts[author_id] = counts.get(author_id, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _parse_ts(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _clean_text(text: str) -> str:
    cleaned = re.sub(r"https?://\S+", " ", text)
    cleaned = re.sub(r"<@!?\\d+>", " ", cleaned)
    cleaned = re.sub(r"<#\\d+>", " ", cleaned)
    cleaned = re.sub(r"<@&\\d+>", " ", cleaned)
    cleaned = re.sub(r"`{1,3}.*?`{1,3}", " ", cleaned)
    cleaned = re.sub(r"\\s+", " ", cleaned)
    return cleaned.strip().lower()


def _extract_segment_keywords(text: str) -> list[str]:
    keywords = []
    for word in _extract_keywords(text):
        if word in ITALIAN_STOPWORDS:
            continue
        keywords.append(word)
    return keywords


def _rank_keywords(words: list[str]) -> list[str]:
    counts: dict[str, float] = {}
    for word in words:
        weight = 0.2 if word in NOISE_KEYWORDS else 1.0
        counts[word] = counts.get(word, 0.0) + weight
    if not counts:
        return []
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    keywords = [word for word, _ in ranked if word]
    filtered = [word for word in keywords if word not in NOISE_KEYWORDS]
    return filtered[:3] if filtered else keywords[:3]


def _segment_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for msg in messages:
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        ts = _parse_ts(msg.get("ts"))
        if ts is None:
            continue
        cleaned = _clean_text(content)
        keywords = _extract_segment_keywords(cleaned)
        enriched.append(
            {
                "message_id": msg.get("message_id"),
                "author_id": msg.get("author_id"),
                "ts": ts,
                "content": content,
                "cleaned": cleaned,
                "keywords": keywords,
            }
        )
    if not enriched:
        return []
    enriched.sort(key=lambda item: item["ts"])
    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for msg in enriched:
        if current is None:
            current = _start_segment(msg)
            continue
        gap_minutes = (msg["ts"] - current["last_ts"]).total_seconds() / 60
        overlap = _keyword_overlap(current["keyword_set"], set(msg["keywords"]))
        if gap_minutes > 7 or (gap_minutes > 3 and overlap < 0.2):
            segments.append(_finalize_segment(current))
            current = _start_segment(msg)
        else:
            _add_to_segment(current, msg)
    if current is not None:
        segments.append(_finalize_segment(current))
    return segments


def _start_segment(msg: dict[str, Any]) -> dict[str, Any]:
    return {
        "start_ts": msg["ts"],
        "last_ts": msg["ts"],
        "message_count": 1,
        "authors": {str(msg.get("author_id") or ""): 1} if msg.get("author_id") else {},
        "keyword_counts": {word: 1 for word in msg["keywords"]},
        "keyword_set": set(msg["keywords"]),
        "mentions": _count_mentions(msg["content"]),
        "questions": msg["content"].count("?"),
        "negativity_hits": _count_keywords(msg["cleaned"], NEGATIVE_KEYWORDS),
        "positive_hits": _count_keywords(msg["cleaned"], POSITIVE_KEYWORDS),
        "message_ids": [str(msg.get("message_id"))] if msg.get("message_id") else [],
        "representative": msg,
        "representative_score": _reference_score(msg),
    }


def _add_to_segment(segment: dict[str, Any], msg: dict[str, Any]) -> None:
    segment["last_ts"] = msg["ts"]
    segment["message_count"] += 1
    author_id = str(msg.get("author_id") or "")
    if author_id:
        segment["authors"][author_id] = segment["authors"].get(author_id, 0) + 1
    for word in msg["keywords"]:
        segment["keyword_counts"][word] = segment["keyword_counts"].get(word, 0) + 1
    segment["keyword_set"].update(msg["keywords"])
    segment["mentions"] += _count_mentions(msg["content"])
    segment["questions"] += msg["content"].count("?")
    segment["negativity_hits"] += _count_keywords(msg["cleaned"], NEGATIVE_KEYWORDS)
    segment["positive_hits"] += _count_keywords(msg["cleaned"], POSITIVE_KEYWORDS)
    if msg.get("message_id"):
        segment["message_ids"].append(str(msg.get("message_id")))
    ref_score = _reference_score(msg)
    if ref_score > segment["representative_score"]:
        segment["representative"] = msg
        segment["representative_score"] = ref_score


def _finalize_segment(segment: dict[str, Any]) -> dict[str, Any]:
    duration_minutes = max(1.0, (segment["last_ts"] - segment["start_ts"]).total_seconds() / 60)
    burstiness = segment["message_count"] / duration_minutes
    top_author_id = None
    if segment["authors"]:
        top_author_id = max(segment["authors"].items(), key=lambda item: item[1])[0]
    top_keywords = _rank_keywords(_expand_keywords(segment["keyword_counts"]))
    cluster_key = "_".join(top_keywords) if top_keywords else "misc"
    return {
        "start_ts": segment["start_ts"].isoformat(),
        "end_ts": segment["last_ts"].isoformat(),
        "message_count": segment["message_count"],
        "author_count": len(segment["authors"]),
        "mentions": segment["mentions"],
        "burstiness": burstiness,
        "keywords": top_keywords,
        "questions": segment["questions"],
        "negativity_hits": segment["negativity_hits"],
        "positive_hits": segment["positive_hits"],
        "message_ids": segment["message_ids"],
        "representative_ts": segment["representative"]["ts"].isoformat(),
        "top_author_id": top_author_id,
        "cluster_key": cluster_key,
    }


def _expand_keywords(counts: dict[str, int]) -> list[str]:
    output: list[str] = []
    for word, count in counts.items():
        output.extend([word] * count)
    return output


def _keyword_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _reference_score(msg: dict[str, Any]) -> float:
    return _count_mentions(msg["content"]) + len(msg["content"]) / 80


def _count_mentions(text: str) -> int:
    return len(re.findall(r"<@!?\\d+>", text))


def _count_keywords(text: str, keywords: Iterable[str]) -> int:
    return sum(text.count(word) for word in keywords)


def _build_segment_summary(segment: dict[str, Any]) -> str:
    keywords = segment.get("keywords") or []
    topic = " / ".join(keywords) if keywords else "diversi temi"
    action = _segment_action(segment)
    templates = [
        "Si parla di {topic}; {action}.",
        "Focus su {topic}, con {action}.",
        "Nel periodo spiccano {topic}: {action}.",
        "Discussione su {topic} con {action}.",
    ]
    selector = sum(ord(char) for char in topic) % len(templates)
    template = templates[selector]
    return template.format(topic=topic, action=action)


def _segment_action(segment: dict[str, Any]) -> str:
    if segment.get("negativity_hits", 0) > 0:
        return "emergono frizioni e richieste di chiarimento"
    if segment.get("positive_hits", 0) > 0:
        return "tono collaborativo con supporto reciproco"
    if segment.get("questions", 0) > 1:
        return "si chiariscono dubbi e si allineano le posizioni"
    if _keywords_match(segment.get("keywords") or [], {"orari", "ora", "meeting", "call", "programma", "agenda"}):
        return "ci si coordina su tempi e organizzazione"
    return "scambio di aggiornamenti e punti di vista"


def _keywords_match(keywords: list[str], targets: set[str]) -> bool:
    return any(word in targets for word in keywords)


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


def _trim_period_description(text: str | None, period_prefix: str) -> str | None:
    if not text:
        return None
    line = text.strip().splitlines()[0].strip()
    if not line:
        return None
    lower_line = line.lower()
    lower_prefix = period_prefix.lower()
    if "il barcello" not in lower_line:
        if lower_line.startswith(lower_prefix):
            line = line[len(period_prefix) :].lstrip(" ,:-")
        line = f"{period_prefix} il barcello è stato {line}"
    elif not lower_line.startswith(lower_prefix):
        line = f"{period_prefix} {line}"
    line = line.strip()
    if len(line) > 120:
        trimmed = line[:120]
        if " " in trimmed:
            trimmed = trimmed.rsplit(" ", 1)[0]
        line = trimmed.rstrip(".") + "."
    return line


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
        ts = _normalize_ts_value(item.get("ts"))
        message_id = str(item.get("message_id") or "") or None
        if not reason:
            continue
        output.append(SummaryImpact(author_id=author_id, reason=reason, ts=ts, message_id=message_id))
    return output


def _normalize_ts_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


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
