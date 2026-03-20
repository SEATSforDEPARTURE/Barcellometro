from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Iterable, Optional

from app.services.ai_utils import model_display_name, parse_model_string
from app.services.aura import resolve_aura_reason_label
from app.services.barcello_service import NEGATIVE_KEYWORDS
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)
MOMENT_TEXT_LIMIT = 200
ROME_TZ = ZoneInfo("Europe/Rome")
SUMMARY_PROMPT_TARGET_TOKENS = 10000
SUMMARY_PROMPT_CHAR_BUDGET_TARGET = 36000
SUMMARY_PROMPT_CHAR_BUDGET_HARD_CAP = 40000
SUMMARY_PROMPT_MESSAGE_CHAR_LIMIT = 280
SUMMARY_PROMPT_MESSAGE_CHAR_LIMIT_MIN = 96
SUMMARY_PROMPT_DUPLICATE_FINGERPRINT_LIMIT = 160

DEFAULT_SUMMARY_CONFIG: dict[str, Any] = {
    "tiers": {
        "role1": {
            "label": "PLUS",
            "sections": ["themes", "moments"],
            "limits": {
                "themes": 6,
                "moments": 10,
                "quotes": 3,
                "dynamics": 3,
            },
        },
        "role2": {
            "label": "PRO",
            "sections": ["themes", "moments", "quotes"],
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
                "moments": 10,
                "quotes": 3,
                "dynamics": 3,
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
                "moments": 10,
                "quotes": 3,
                "dynamics": 3,
                "impact": 3,
            },
        },
    },
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


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default



THEME_EN_TO_IT = {
    "humor": "umore",
    "health": "salute",
    "weather": "meteo",
    "projectwork": "progetti",
    "collaboration": "collaborazione",
}


@dataclass
class SummaryItem:
    ts: Optional[str]
    text: str
    author_id: Optional[str]
    message_ids: list[str] = field(default_factory=list)
    cluster_key: Optional[str] = None
    actor_display: Optional[str] = None
    actors_display: list[str] = field(default_factory=list)
    in_call: bool = False


@dataclass
class SummaryQuote:
    ts: Optional[str]
    text: str
    author_id: Optional[str]
    message_ids: list[str] = field(default_factory=list)
    actor_display: Optional[str] = None
    in_call: bool = False


@dataclass
class SummaryImpact:
    author_id: Optional[str]
    reason: str
    ts: Optional[str]
    message_id: Optional[str]
    aura_points_period: Optional[int] = None
    aura_total_points: Optional[int] = None


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
    vibe_line: str | None = None
    proverbio: str | None = None
    who_interacted_today: list[str] = field(default_factory=list)
    cache_hit: bool = False


@dataclass
class SummaryJsonParseResult:
    payload: dict[str, Any] | None
    extraction_strategy: str
    extracted_json_from_code_fence: bool = False
    extracted_json_from_text_wrapper: bool = False
    normalized_invalid_json: bool = False

    @property
    def parse_recovered(self) -> bool:
        return self.extraction_strategy != "direct" or self.normalized_invalid_json


def _summary_prompt_budget(
    *,
    start_ts: str | None,
    end_ts: str | None,
    granularity_hint: str | None,
    period_label: str | None,
    is_ollama: bool,
    ollama_compatible_fallback: bool,
) -> dict[str, int | str]:
    duration_secs = 0
    start_dt = _parse_ts(_normalize_ts_value(start_ts))
    end_dt = _parse_ts(_normalize_ts_value(end_ts))
    if start_dt and end_dt:
        duration_secs = max(int((end_dt - start_dt).total_seconds()), 0)
    label = str(period_label or "").strip().lower()
    hint = str(granularity_hint or "").strip().lower()

    max_items = 96
    buckets = 8
    per_message_char_limit = 320
    total_prompt_char_budget = SUMMARY_PROMPT_CHAR_BUDGET_TARGET
    if duration_secs >= 30 * 24 * 3600:
        max_items = 32
        buckets = 4
        per_message_char_limit = 140
        total_prompt_char_budget = 22000
    elif duration_secs >= 14 * 24 * 3600:
        max_items = 40
        buckets = 4
        per_message_char_limit = 160
        total_prompt_char_budget = 24000
    elif duration_secs >= 7 * 24 * 3600:
        max_items = 52
        buckets = 5
        per_message_char_limit = 180
        total_prompt_char_budget = 26000
    elif duration_secs >= 3 * 24 * 3600:
        max_items = 64
        buckets = 6
        per_message_char_limit = 210
        total_prompt_char_budget = 30000
    elif duration_secs >= 24 * 3600:
        max_items = 80
        buckets = 7
        per_message_char_limit = 240
        total_prompt_char_budget = 33000
    elif duration_secs >= 6 * 3600:
        max_items = 92
        buckets = 8
        per_message_char_limit = 280
        total_prompt_char_budget = 35000

    if label in {"oggi", "ieri"}:
        max_items = max(max_items, 92)
        buckets = max(buckets, 8)
        per_message_char_limit = max(per_message_char_limit, 280)
        total_prompt_char_budget = max(total_prompt_char_budget, 35000)
    elif label == "range" and duration_secs >= 7 * 24 * 3600:
        max_items = min(max_items, 48)
        buckets = min(buckets, 5)
        per_message_char_limit = min(per_message_char_limit, 170)
        total_prompt_char_budget = min(total_prompt_char_budget, 25000)

    if hint in {"weeks", "months"}:
        max_items = min(max_items, 48)
        buckets = min(buckets, 5)
        per_message_char_limit = min(per_message_char_limit, 170)
        total_prompt_char_budget = min(total_prompt_char_budget, 25000)
    elif hint == "days" and duration_secs >= 7 * 24 * 3600:
        max_items = min(max_items, 56)
        buckets = min(buckets, 5)
        per_message_char_limit = min(per_message_char_limit, 180)

    if is_ollama or ollama_compatible_fallback:
        max_items = min(40, max(24, int(max_items * 0.75)))
        buckets = max(3, min(buckets, 5))
        per_message_char_limit = max(SUMMARY_PROMPT_MESSAGE_CHAR_LIMIT_MIN, int(per_message_char_limit * 0.85))
        total_prompt_char_budget = max(18000, int(total_prompt_char_budget * 0.8))

    return {
        "duration_secs": duration_secs,
        "period_label": label or "unspecified",
        "max_items": max_items,
        "min_items": max(18, min(24, max_items)),
        "buckets": max(3, min(buckets, max_items)),
        "per_message_char_limit": max(SUMMARY_PROMPT_MESSAGE_CHAR_LIMIT_MIN, per_message_char_limit),
        "min_per_message_char_limit": SUMMARY_PROMPT_MESSAGE_CHAR_LIMIT_MIN,
        "total_prompt_char_budget": min(total_prompt_char_budget, SUMMARY_PROMPT_CHAR_BUDGET_HARD_CAP),
        "hard_prompt_char_cap": SUMMARY_PROMPT_CHAR_BUDGET_HARD_CAP,
        "target_tokens": SUMMARY_PROMPT_TARGET_TOKENS,
    }


def _estimate_summary_prompt_tokens(char_count: int) -> int:
    return max(1, math.ceil(max(char_count, 0) / 4))


class SummaryService:
    def __init__(self, database: DatabaseService, ai_service: Any | None = None, *, cache_ttl_seconds: int = 90) -> None:
        self._database = database
        self._ai_service = ai_service
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[
            tuple[str, str, str, str, str, bool, bool, bool, str | None, str],
            tuple[float, SummaryResult, str | None],
        ] = {}
        self._response_format_supported: bool | None = None

    def build_cache_key(
        self,
        *,
        guild_id: str,
        channel_id: str,
        start_ts: str,
        end_ts: str,
        tier: str,
        evidence_mode: bool,
        voice_context: bool,
        ai_allowed: bool,
        model_name: str | None,
        summary_mode: str,
    ) -> tuple[str, str, str, str, str, bool, bool, bool, str | None, str]:
        return (
            guild_id,
            channel_id,
            start_ts,
            end_ts,
            tier,
            evidence_mode,
            voice_context,
            ai_allowed,
            model_name,
            summary_mode,
        )

    def peek_cache(self, cache_key: tuple[str, ...], max_message_ts: Optional[str]) -> bool:
        now_epoch = datetime.now(timezone.utc).timestamp()
        cached = self._cache.get(cache_key)
        if cached and cached[0] > now_epoch:
            if max_message_ts and cached[2] and max_message_ts <= cached[2]:
                return True
        return False

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
        granularity_hint: str | None = None,
        summary_mode: str = "default",
        summary_context: dict[str, Any] | None = None,
    ) -> SummaryResult:
        model_name = self._ai_service.get_model("summary") if self._ai_service else None
        cache_key = self.build_cache_key(
            guild_id=guild_id,
            channel_id=channel_id,
            start_ts=start_ts,
            end_ts=end_ts,
            tier=tier,
            evidence_mode=evidence_mode,
            voice_context=voice_context,
            ai_allowed=ai_allowed,
            model_name=model_name,
            summary_mode=summary_mode,
        )
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
            granularity_hint=granularity_hint,
        )

        use_ai = ai_allowed and self._ai_service is not None

        summary = local_summary
        ai_status: dict[str, Any] = {
            "enabled": False,
            "provider": None,
            "model": None,
            "display_model": None,
            "configured_model": None,
            "configured_display_model": None,
            "called": False,
            "fallback": False,
            "reason": "disabled",
            "used_ai_output": False,
            "used_model": None,
            "used_display_model": None,
        }
        if use_ai:
            model_cfg = str(model_name or "").strip()
            provider, _ = parse_model_string(model_cfg) if model_cfg else (None, None)
            model_label = model_display_name(model_cfg) or None
            ai_status.update({
                "enabled": True,
                "provider": provider,
                "model": model_cfg or None,
                "display_model": model_label,
                "configured_model": model_cfg or None,
                "configured_display_model": model_label,
            })
            if not model_cfg:
                ai_status.update({"enabled": False, "fallback": True, "reason": "missing_model"})
            else:
                try:
                    ai_status["called"] = True
                    ai_payload = await self._call_ai(
                        messages=messages,
                        include_names=include_names,
                        tier=tier,
                        barcello_metrics=barcello_metrics,
                        config=config,
                        granularity_hint=granularity_hint,
                        summary_mode=summary_mode,
                        summary_context=summary_context,
                        start_ts=start_ts,
                        end_ts=end_ts,
                    )
                    runtime_model_cfg = self._ai_service.get_runtime_model("summary") if hasattr(self._ai_service, "get_runtime_model") else model_cfg
                    runtime_provider, _ = parse_model_string(str(runtime_model_cfg or "")) if runtime_model_cfg else (provider, None)
                    runtime_label = model_display_name(runtime_model_cfg) or model_label
                    if runtime_model_cfg:
                        ai_status.update(
                            {
                                "provider": runtime_provider,
                                "model": runtime_model_cfg,
                                "display_model": runtime_label,
                                "fallback": bool(runtime_model_cfg and runtime_model_cfg != model_cfg),
                            }
                        )
                    if ai_payload:
                        await self._sanitize_ai_payload(
                            ai_payload,
                            messages,
                            include_names=include_names,
                            channel_id=channel_id,
                            start_ts=start_ts,
                            end_ts=end_ts,
                        )
                    if ai_payload:
                        summary = self._merge_ai_summary(local_summary, ai_payload, include_names, config=config, tier=tier)
                        ai_status.update(
                            {
                                "enabled": True,
                                "fallback": bool(runtime_model_cfg and runtime_model_cfg != model_cfg),
                                "reason": "ok",
                                "used_ai_output": True,
                                "used_model": runtime_model_cfg or model_cfg,
                                "used_display_model": runtime_label,
                            }
                        )
                    else:
                        ai_status.update(
                            {
                                "enabled": False,
                                "fallback": True,
                                "reason": "invalid_json",
                                "used_ai_output": False,
                                "used_model": None,
                                "used_display_model": None,
                            }
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Summary AI failed")
                    ai_status.update(
                        {
                            "enabled": False,
                            "fallback": True,
                            "reason": f"exception:{exc.__class__.__name__}",
                            "used_ai_output": False,
                            "used_model": None,
                            "used_display_model": None,
                        }
                    )

        summary.ai_status = ai_status
        logger.info(
            "summary: ai_called=%s used_ai_output=%s fallback_reason=%s provider=%s configured_model=%s used_model=%s",
            ai_status.get("called"),
            ai_status.get("used_ai_output"),
            ai_status.get("reason"),
            ai_status.get("provider"),
            ai_status.get("configured_model") or ai_status.get("model"),
            ai_status.get("used_model"),
        )
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
        del tier, score, metrics, trend, ai_allowed, config
        text = _local_period_description(period_prefix, color)
        logger.info(
            "summary: period_description ai_calls_before=2 ai_calls_after=1 local_period_description=true used_local_render_fields=true"
        )
        return _trim_period_description(text, period_prefix)

    def _build_local_summary(
        self,
        *,
        messages: list[dict[str, Any]],
        include_names: bool,
        config: dict[str, Any],
        barcello_metrics: dict[str, Any],
        tier: str,
        granularity_hint: str | None = None,
        summary_mode: str = "default",
        summary_context: dict[str, Any] | None = None,
    ) -> SummaryResult:
        themes = self._extract_themes(messages, config, tier)
        moments_tier = _moments_policy_tier(tier)
        moments = self._extract_moments(messages, config, moments_tier, granularity_hint=granularity_hint)
        quotes = self._extract_quotes(messages, config, tier)
        dynamics = self._extract_dynamics(barcello_metrics, messages, config, tier)
        degrade, invigorate = self._extract_impact(messages, config, tier)
        advice = self._build_mod_advice(barcello_metrics)
        moments = _sanitize_summary_items(moments, drop_templates=False, drop_slash_tokens=True)
        quotes = _sanitize_summary_items(quotes, drop_templates=False)
        dynamics = _sanitize_summary_items(dynamics, drop_templates=False)
        moments = _sort_moments_chronologically(moments)
        moments = _compact_moment_items(moments, limit=MOMENT_TEXT_LIMIT)
        quotes = _sort_quotes_chronologically(quotes)
        dynamics = _sort_moments_chronologically(dynamics)
        degrade = _sort_impacts_chronologically(degrade)
        invigorate = _sort_impacts_chronologically(invigorate)
        cleaned_advice: list[str] = []
        for item in advice:
            sanitized = _sanitize_bullet_text(item)
            if sanitized:
                cleaned_advice.append(sanitized)
        advice = cleaned_advice
        return SummaryResult(
            themes=themes,
            moments=moments,
            quotes=quotes,
            dynamics=dynamics,
            degrade=degrade,
            invigorate=invigorate,
            advice=advice,
            metrics=barcello_metrics,
            ai_status={
                "enabled": False,
                "provider": None,
                "model": None,
                "display_model": None,
                "configured_model": None,
                "configured_display_model": None,
                "called": False,
                "fallback": False,
                "reason": "local",
                "used_ai_output": False,
                "used_model": None,
                "used_display_model": None,
            },
        )

    async def _call_ai(
        self,
        *,
        messages: list[dict[str, Any]],
        include_names: bool,
        tier: str,
        barcello_metrics: dict[str, Any],
        config: dict[str, Any],
        granularity_hint: str | None = None,
        summary_mode: str = "default",
        summary_context: dict[str, Any] | None = None,
        start_ts: str | None = None,
        end_ts: str | None = None,
    ) -> dict[str, Any] | None:
        model_cfg = self._ai_service.get_model("summary") if self._ai_service else None
        fallback_model_cfg = self._ai_service.get_fallback_model("summary") if self._ai_service and hasattr(self._ai_service, "get_fallback_model") else None
        provider, _ = parse_model_string(str(model_cfg or "")) if model_cfg else (None, None)
        fallback_provider, _ = parse_model_string(str(fallback_model_cfg or "")) if fallback_model_cfg else (None, None)
        is_ollama = provider == "ollama"
        ollama_compatible_fallback = provider != "ollama" and fallback_provider == "ollama"
        moments_policy_tier = _moments_policy_tier(tier)
        moments_target = _tier_limit(config, moments_policy_tier, "moments", 5)
        logger.info("summary: moments_policy=role3 requested_tier=%s", tier)
        quotes_target = _tier_limit(config, tier, "quotes", 3)
        dynamics_target = _tier_limit(config, tier, "dynamics", 2)
        multi_day_window = False
        try:
            if start_ts and end_ts:
                st = datetime.fromisoformat(str(start_ts).replace("Z", "+00:00"))
                en = datetime.fromisoformat(str(end_ts).replace("Z", "+00:00"))
                multi_day_window = st.astimezone(ROME_TZ).date() != en.astimezone(ROME_TZ).date()
        except Exception:
            multi_day_window = False
        period_label = str((summary_context or {}).get("period_label") or "").strip().lower()
        if period_label in {"oggi", "ieri"}:
            multi_day_window = False
        if summary_mode in {"daily_report", "daily_resoconto", "channel_summary"}:
            narrative_extra = (
                "Imposta un andamento narrativo della giornata: apertura, sviluppo, chiusura. "
                "Niente copia verbatim dai messaggi. "
                "Per FRASI ICONICHE non parafrasare: usa solo citazioni reali e fornisci sempre primary_ref. "
                "Se non sei sicuro del testo esatto della frase, non inventare: restituisci il riferimento al messaggio. "
            )
            names_rule = "NON includere mai nomi di persone reali: usa solo il placeholder {AUTHOR} nei moments quando necessario. "
            if summary_mode in {"daily_resoconto", "channel_summary"}:
                if multi_day_window:
                    narrative_extra += (
                        "MOMENTI SALIENTI (intervallo multi-giorno): usa descrizioni neutrali degli eventi, non cronologia di una singola giornata. "
                        "Non usare ganci orari come 'di prima mattina', 'verso mezzogiorno', 'nel pomeriggio', 'in serata'. "
                        "Non forzare apertura/sviluppo/chiusura giornaliera: ogni bullet deve restare autonomo e fattuale. "
                    )
                else:
                    narrative_extra += (
                        "MOMENTI SALIENTI (OBBLIGATORIO): scrivi in stile narrativo come un racconto della giornata (inizio, sviluppo, chiusura). "
                        "Ogni bullet DEVE iniziare con un gancio temporale coerente con l'orario del messaggio di riferimento. "
                        "Non iniziare mai la frase con il nome della persona. "
                        "Integra il nickname nel racconto in modo naturale, preferendo strutture come '... quando {AUTHOR} ...'. "
                        "Evita qualsiasi forma che riveli o presuma il genere. "
                        "Non usare strutture da elenco tipo '{AUTHOR} ha...'. "
                        "Usa ganci temporali variati in base all'orario: 06:00-10:59 (La mattina/Di prima mattina/All'avvio della giornata), "
                        "11:00-14:59 (Durante la tarda mattinata/Verso mezzogiorno/In piena giornata), 15:00-18:59 (Nel pomeriggio/Più tardi), "
                        "19:00-22:59 (In serata/Sul finire della giornata). "
                        "L'ultimo momento deve suonare come chiusura (es. 'La giornata si chiude con...' o 'In chiusura...'). "
                        "Non usare la stessa apertura più di una volta; vietato ripetere esattamente la stessa locuzione in più bullet. "
                    )
                narrative_extra += "Quando barcello_verde=true evita formule vaghe come 'un membro' o 'qualcuno' se {AUTHOR} è disponibile. "
        else:
            narrative_extra = ""
            names_rule = "NON includere mai nomi di persone. "
        moments_style_rule = (
            "Momenti: stile narrativo e descrittivo, frasi complete; niente template tipo 'Si discute di'. "
        )
        if summary_mode in {"daily_resoconto", "channel_summary"} and multi_day_window:
            moments_style_rule = (
                "Momenti: stile neutro-fattuale, bullet autonomi orientati agli eventi; evita cronologia narrativa della giornata. "
            )
        compact_system_prompt = (
            "Scrivi in italiano e restituisci SOLO JSON valido. "
            + narrative_extra
            + "Non inventare dettagli. "
            + names_rule
            + "Descrivi eventi reali senza copiare i messaggi. "
            "I messaggi in input usano chiavi compatte: i=message_id, t=timestamp ISO, a=author_id, x=testo, k=kind, vc=1 se evento vocale/in call. "
            "Mantieni il testo dei campi JSON essenziale: niente boilerplate, niente intestazioni, niente frasi ornamentali. "
            "Struttura JSON minima richiesta: themes[], moments[], advice[]. "
            "themes: lista corta di keyword in italiano, minuscole. "
            "moments: oggetti con 'ts','summary_text','primary_ref','refs'. "
            "advice: lista stringhe brevi per la community, anche vuota se non aggiunge valore. "
            "quotes/dynamics/degrade_list/invigorate_list/who_interacted_today/proverbio sono opzionali."
        )
        if is_ollama:
            schema_mode = "compact"
            system_prompt = compact_system_prompt
        else:
            schema_mode = "full"
            system_prompt = (
                "Scrivi in italiano e restituisci SOLO JSON valido. "
                + narrative_extra
                + "Non inventare dettagli. "
                + "Non inferire né ricostruire contenuti omessi per privacy. "
                + names_rule
                + "I messaggi in input usano chiavi compatte: i=message_id, t=timestamp ISO, a=author_id, x=testo, k=kind, vc=1 se evento vocale/in call. "
                + "Se includi emoji custom, mantieni il formato Discord `<:nome:id>` o `<a:nome:id>` senza convertirle in numeri. "
                "TEMI devono essere solo keyword brevi (no nomi). TEMI devono essere in italiano, minuscoli, una parola o snake_case, senza # e senza inglese. Se un tema ti verrebbe in inglese, traducilo in italiano. "
                "Descrivi gli EVENTI: non copiare il testo dei messaggi. "
                "Non inventare eventi di chiamata: usa solo quelli presenti nella timeline (kind: call/privacy/presence). "
                "Genera ESATTAMENTE moments_target_count momenti salienti (non accorpare). "
                "Ogni momento deve riassumere un evento/argomento e NON deve includere citazioni dirette. "
                + moments_style_rule
                + "I momenti devono contenere un primary_ref valido (snowflake 17-20 cifre) e, se possibile, refs[] con altri id. "
                "Ogni momento DEVE includere un primary_ref presente nei message ids forniti: non inventare id. "
                "Se i dati sono pochi, restituisci comunque fino a moments_target_count elementi (mai meno del necessario). "
                "Distribuisci moments/quotes/dynamics su tutto l'intervallo temporale (inizio, metà, fine). "
                "Per i moments usa bullet descrittivi di 1-2 frasi quando possibile, evitando formule troppo brevi. "
                "Tieni quotes/dynamics/degrade_list/invigorate_list/advice concisi e restituisci array vuoti quando il valore aggiunto è scarso: il renderer completa localmente i campi standard. "
                "dynamics devono essere descrizioni astratte e comportamentali, senza copiare testo o riportare orari. "
                "Per degrade_list/invigorate_list scrivi motivi utili ai MOD: spiega in modo concreto il comportamento osservato, "
                "con linguaggio semplice e non tecnico, in massimo 1 frase breve ma chiara. "
                "Evita formule astratte tipo 'toni pungenti' o 'messaggi positivi'. "
                "Esempi di qualità desiderata: "
                "'Ha alzato la tensione con battute pungenti e risposte che hanno irrigidito il dialogo.' "
                "'Ha tenuto un tono rassicurante e ha riportato calma quando la conversazione rischiava di irrigidirsi.' "
                "Struttura JSON: themes[], moments[], quotes[], dynamics[], degrade_list[], invigorate_list[], advice[]. "
                "moments: oggetti con 'ts','summary_text','primary_ref','refs'. "
                "quotes: oggetti con 'ts','primary_ref','refs' e 'quote_text' opzionale solo se certo al 100%. "
                "dynamics: oggetti con 'ts','dynamic_text','optional_ref','refs'. "
                "degrade_list/invigorate_list: oggetti con 'author_id','reason','ts','message_id'. "
                "advice: lista stringhe brevi."
            )
        if summary_mode in {"daily_resoconto", "channel_summary"}:
            system_prompt += (
                " In modalità channel_summary aggiungi anche `vibe_line`: UNA sola frase (max 140 caratteri), "
                "in italiano al passato prossimo, riferita solo a colore + punti salute + vibe generale del barcello di oggi. "
                "NON includere riferimenti a trend/delta/ieri: vietate le parole 'trend', 'stabile', 'miglioramento', 'peggioramento', 'Δ', 'delta', 'rispetto a ieri'. "
                "Varia stile e lessico ad ogni invio, evita formule standard ripetitive. "
                "Usa il campo `summary_context.nonce` solo come stimolo di variazione e non stamparlo. "
                "Genera `advice_bullets` (4-6) rivolti alla community usando sempre il 'voi', senza citare persone singole: "
                "se color=verde consigli di mantenimento, altrimenti consigli correttivi/de-escalation per tornare al verde. "
                "Genera anche `who_interacted_today` come lista di oggetti {name, line}: usa solo i nomi forniti in summary_context.who_interacted_candidates, "
                "nessun nome inventato, una frase per riga (max 160 caratteri), italiano corretto e neutro. "
                "Aggiungi opzionalmente `proverbio` (una riga)."
            )
        period_label = str((summary_context or {}).get("period_label") or period_label or "").strip().lower()
        budget = _summary_prompt_budget(
            start_ts=start_ts,
            end_ts=end_ts,
            granularity_hint=granularity_hint,
            period_label=period_label,
            is_ollama=is_ollama,
            ollama_compatible_fallback=ollama_compatible_fallback,
        )
        logger.info(
            "summary: period_budget duration_secs=%s period_label=%s granularity_hint=%s target_tokens=%s",
            budget["duration_secs"],
            budget["period_label"],
            granularity_hint or "unspecified",
            budget["target_tokens"],
        )
        logger.info(
            "summary: prompt_budget_chars=%s hard_cap_chars=%s",
            budget["total_prompt_char_budget"],
            budget["hard_prompt_char_cap"],
        )
        payload_base = {
            "tier": tier,
            "moments_target_count": moments_target,
            "quotes_target_count": quotes_target,
            "dynamics_target_count": dynamics_target,
            "metrics": _build_summary_prompt_metrics(barcello_metrics),
            "granularity_hint": _granularity_prompt_hint(granularity_hint),
            "summary_context": _build_summary_prompt_context(summary_context),
        }
        if include_names:
            payload_base["include_names"] = True
        user_payload, compact_messages, compact_stats = _build_summary_prompt_payload(
            messages=messages,
            payload_base=payload_base,
            system_prompt=system_prompt,
            budget=budget,
        )
        if self._ai_service is None:
            return None
        prompt_chars_before = compact_stats["raw_payload_chars"] + len(system_prompt)
        prompt_chars_after = len(user_payload) + len(system_prompt)
        logger.info("summary: sampled_messages_before_budget=%s", compact_stats["sampled_before_budget"])
        logger.info("summary: sampled_messages_after_budget=%s", compact_stats["sampled_after_budget"])
        logger.info("summary: per_message_char_limit=%s", compact_stats["per_message_char_limit"])
        logger.info(
            "summary: prompt_chars_final=%s estimated_tokens=%s",
            compact_stats["prompt_chars_final"],
            _estimate_summary_prompt_tokens(int(compact_stats["prompt_chars_final"])),
        )
        logger.info(
            "summary: provider=%s schema=%s sampled_messages=%s buckets=%s ai_calls_before=%s ai_calls_after=%s prompt_chars_before=%s prompt_chars_after=%s prompt_items_before=%s prompt_items_after=%s removed_metadata=%s used_local_render_fields=%s local_period_description=%s",
            provider or "unknown",
            schema_mode,
            compact_stats["sampled_after_budget"],
            compact_stats["buckets_used"],
            2,
            1,
            prompt_chars_before,
            prompt_chars_after,
            compact_stats["sampled_before_budget"],
            compact_stats["items_after"],
            str(bool(compact_stats["removed_metadata"]) or bool(compact_stats["metadata_reduced"])).lower(),
            "true",
            "true" if summary_mode == "default" else "false",
        )
        fallback_schema_mode = "compact" if ollama_compatible_fallback else schema_mode
        fallback_system_prompt = compact_system_prompt if ollama_compatible_fallback else system_prompt
        fallback_user_payload = user_payload
        text = await self._ai_service.ask_for_task(
            "summary",
            user_payload,
            system_prompt,
            fallback_question=fallback_user_payload if ollama_compatible_fallback else None,
            fallback_persona_system=fallback_system_prompt if ollama_compatible_fallback else None,
        )
        runtime_model_cfg = self._ai_service.get_runtime_model("summary") if hasattr(self._ai_service, "get_runtime_model") else model_cfg
        runtime_provider, _ = parse_model_string(str(runtime_model_cfg or "")) if runtime_model_cfg else (provider, None)
        effective_schema_mode = fallback_schema_mode if runtime_provider == "ollama" and ollama_compatible_fallback else schema_mode
        parse_result = _parse_json_safe(text)
        logger.info(
            "summary: provider=%s schema=%s json_extraction_strategy=%s extracted_json_from_code_fence=%s extracted_json_from_text_wrapper=%s normalized_invalid_json=%s parse_recovered=%s",
            runtime_provider or provider or "unknown",
            effective_schema_mode,
            parse_result.extraction_strategy,
            str(parse_result.extracted_json_from_code_fence).lower(),
            str(parse_result.extracted_json_from_text_wrapper).lower(),
            str(parse_result.normalized_invalid_json).lower(),
            str(parse_result.parse_recovered).lower(),
        )
        payload = parse_result.payload
        validation_failed_field = _validate_summary_payload(payload, effective_schema_mode)
        if validation_failed_field:
            logger.warning(
                "summary: provider=%s schema=%s used_ai_output=false parse_recovered=%s validation_failed_field=%s",
                runtime_provider or provider or "unknown",
                effective_schema_mode,
                str(parse_result.parse_recovered).lower(),
                validation_failed_field,
            )
            return None
        return payload

    def _merge_ai_summary(
        self,
        local_summary: SummaryResult,
        ai_payload: dict[str, Any],
        include_names: bool,
        *,
        config: dict[str, Any],
        tier: str,
    ) -> SummaryResult:
        def _normalize_items(
            raw: Any,
            *,
            is_quote: bool = False,
            is_dynamic: bool = False,
        ) -> list[SummaryItem | SummaryQuote]:
            if not isinstance(raw, list):
                return []
            output: list[SummaryItem | SummaryQuote] = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                ts = item.get("ts")
                in_call = bool(item.get("in_call"))
                if is_quote:
                    text = str(item.get("quote_text") or item.get("text") or "").strip()
                elif is_dynamic:
                    text = str(item.get("dynamic_text") or item.get("text") or "").strip()
                else:
                    text = str(item.get("summary_text") or item.get("text") or "").strip()
                if not text:
                    continue
                ref_candidates = [
                    item.get("primary_ref"),
                    item.get("optional_ref"),
                    *(item.get("refs") or []),
                    *(item.get("message_ids") or []),
                ]
                message_ids = []
                seen_ids: set[str] = set()
                for mid in ref_candidates:
                    mid_str = str(mid or "").strip()
                    if not mid_str or mid_str in seen_ids:
                        continue
                    seen_ids.add(mid_str)
                    message_ids.append(mid_str)
                author_id = str(item.get("author_id") or "") or None
                if is_quote:
                    output.append(
                        SummaryQuote(
                            ts=_normalize_ts_value(ts),
                            text=text,
                            author_id=author_id,
                            message_ids=message_ids,
                            actor_display=None,
                            in_call=in_call,
                        )
                    )
                else:
                    output.append(
                        SummaryItem(
                            ts=_normalize_ts_value(ts),
                            text=text,
                            author_id=author_id,
                            message_ids=message_ids,
                            actor_display=None,
                            actors_display=[],
                            in_call=in_call,
                        )
                    )
            return output

        theme_limit = _tier_limit(config, tier, "themes", 6)
        themes = _sanitize_themes(ai_payload.get("themes") or [], limit=theme_limit)
        moments = _normalize_items(ai_payload.get("moments"))
        quotes = _normalize_items(ai_payload.get("quotes") or ai_payload.get("iconic_quotes"), is_quote=True)
        dynamics = _normalize_items(ai_payload.get("dynamics"), is_dynamic=True)
        advice = [str(item).strip() for item in (ai_payload.get("advice") or ai_payload.get("advice_bullets") or []) if str(item).strip()]
        vibe_line = str(ai_payload.get("vibe_line") or "").strip() or None
        proverbio = str(ai_payload.get("proverbio") or "").strip() or None
        who_rows = ai_payload.get("who_interacted_today") or []
        who_interacted_today: list[str] = []
        if isinstance(who_rows, list):
            for row in who_rows:
                if isinstance(row, dict):
                    name = str(row.get("name") or "").strip()
                    line = str(row.get("line") or "").strip()
                    if line and name and name not in line:
                        line = f"{name}: {line}"
                    if line:
                        who_interacted_today.append(line)
                else:
                    line = str(row).strip()
                    if line:
                        who_interacted_today.append(line)
        degrade = _normalize_impacts(ai_payload.get("degrade_list"))
        invigorate = _normalize_impacts(ai_payload.get("invigorate_list"))
        logger.info(
            "Summary impacts pre-filter: degrade=%s invigorate=%s",
            len(degrade),
            len(invigorate),
        )
        degrade, invigorate = _sanitize_and_resolve_impacts(degrade, invigorate)
        logger.info(
            "Summary impacts post-filter: degrade=%s invigorate=%s",
            len(degrade),
            len(invigorate),
        )
        moments_policy_tier = _moments_policy_tier(tier)
        moment_limit = _tier_limit(config, moments_policy_tier, "moments", 5)
        quote_limit = _tier_limit(config, tier, "quotes", 3)
        dynamic_limit = _tier_limit(config, tier, "dynamics", 2)
        if not themes:
            themes = local_summary.themes
        moments = _sanitize_summary_items(moments, drop_slash_tokens=True)
        quotes = _sanitize_summary_items(quotes)
        dynamics = _sanitize_summary_items(dynamics)
        cleaned_advice: list[str] = []
        for item in advice:
            sanitized = _sanitize_bullet_text(item)
            if sanitized:
                cleaned_advice.append(sanitized)
        advice = cleaned_advice
        if not moments:
            moments = _sanitize_summary_items(local_summary.moments)
        moments = _filter_invalid_moments(moments)
        moments_missing_before = max(0, moment_limit - len(moments))
        if len(moments) < moment_limit:
            moments = _dedupe_summary_items(moments, local_summary.moments, limit=moment_limit)
            if len(moments) < moment_limit:
                logger.warning("Summary AI returned %s moments; expected %s", len(moments), moment_limit)
        moments_missing_after = max(0, moment_limit - len(moments))
        if moments_missing_before > 0:
            logger.info(
                "Summary AI moments fill: missing_before=%s missing_after=%s filled=%s",
                moments_missing_before,
                moments_missing_after,
                moments_missing_before - moments_missing_after,
            )
        if len(moments) > moment_limit:
            moments = moments[:moment_limit]
        moments = _sort_moments_chronologically(moments)
        moments = _compact_moment_items(moments, limit=MOMENT_TEXT_LIMIT)
        if not quotes:
            quotes = _sanitize_summary_items(local_summary.quotes)
        if len(quotes) < quote_limit:
            quotes = _dedupe_summary_items(quotes, local_summary.quotes, limit=quote_limit)
        if len(quotes) > quote_limit:
            quotes = quotes[:quote_limit]
        if not dynamics:
            dynamics = _sanitize_summary_items(local_summary.dynamics)
        if len(dynamics) < dynamic_limit:
            dynamics = _dedupe_summary_items(dynamics, local_summary.dynamics, limit=dynamic_limit)
        if len(dynamics) > dynamic_limit:
            dynamics = dynamics[:dynamic_limit]
        quotes = _sort_quotes_chronologically(quotes)
        dynamics = _sort_moments_chronologically(dynamics)
        degrade = _sort_impacts_chronologically(degrade)
        invigorate = _sort_impacts_chronologically(invigorate)
        if not advice:
            advice = local_summary.advice
        if not degrade:
            degrade = local_summary.degrade
        if not invigorate:
            invigorate = local_summary.invigorate
        degrade, invigorate = _sanitize_and_resolve_impacts(degrade, invigorate)
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
            vibe_line=vibe_line,
            proverbio=proverbio,
            who_interacted_today=who_interacted_today,
        )

    async def _sanitize_ai_payload(
        self,
        payload: dict[str, Any],
        messages: list[dict[str, Any]],
        *,
        include_names: bool,
        channel_id: str,
        start_ts: str,
        end_ts: str,
    ) -> None:
        message_records: list[tuple[datetime, str, Optional[str]]] = []
        message_ts_map: dict[str, str] = {}
        message_author_map: dict[str, Optional[str]] = {}
        for msg in messages:
            message_id = str(msg.get("message_id") or "")
            if not _is_valid_snowflake(message_id):
                continue
            ts_value = _normalize_ts_value(msg.get("ts"))
            parsed_ts = _parse_ts(ts_value) if ts_value else None
            if parsed_ts is None:
                continue
            author_id = str(msg.get("author_id") or "") or None
            message_records.append((parsed_ts, message_id, author_id))
            message_ts_map[message_id] = ts_value
            message_author_map[message_id] = author_id
        message_records.sort(key=lambda item: item[0])
        logged_invalid_ts = False
        invalid_primary_ref_count = 0
        invalid_ref_not_in_channel_count = 0
        fallback_nearest_applied_count = 0
        final_items_with_no_ref_count = 0
        invalid_ref_format_count = 0
        ref_cache: dict[str, bool] = {}
        range_start = _normalize_ts_value(start_ts)
        range_end = _normalize_ts_value(end_ts)

        def normalize_ts(value: Any, message_ids: list[str], fallback_ts: Optional[str]) -> Optional[str]:
            nonlocal logged_invalid_ts
            ts = _normalize_ts_value(value)
            if ts:
                return ts
            for message_id in message_ids:
                candidate = _normalize_ts_value(message_ts_map.get(message_id))
                if candidate:
                    if not logged_invalid_ts:
                        logger.debug("Summary AI sanitized invalid ts")
                        logged_invalid_ts = True
                    return candidate
            if fallback_ts:
                if not logged_invalid_ts and value:
                    logger.debug("Summary AI sanitized invalid ts")
                    logged_invalid_ts = True
                return fallback_ts
            if not logged_invalid_ts and value:
                logger.debug("Summary AI sanitized invalid ts")
                logged_invalid_ts = True
            return None

        async def ref_exists(ref: str) -> bool:
            if ref in ref_cache:
                return ref_cache[ref]
            exists = await self._database.message_exists_in_channel(channel_id=channel_id, message_id=ref)
            ref_cache[ref] = exists
            return exists

        async def normalize_refs(raw_refs: Any) -> list[str]:
            nonlocal invalid_ref_not_in_channel_count, invalid_ref_format_count
            refs: list[str] = []
            if isinstance(raw_refs, str):
                raw_refs = [raw_refs]
            for ref in raw_refs or []:
                ref_str = str(ref)
                if not ref_str:
                    continue
                if not _is_valid_snowflake(ref_str):
                    invalid_ref_format_count += 1
                    continue
                if await ref_exists(ref_str):
                    refs.append(ref_str)
                else:
                    invalid_ref_not_in_channel_count += 1
            return refs

        def pick_nearest_record(target_ts: Optional[datetime]) -> tuple[Optional[str], Optional[str], Optional[str]]:
            if not message_records:
                return None, None, None
            if target_ts is None:
                mid = len(message_records) // 2
                picked = message_records[mid]
                return picked[1], picked[0].isoformat(), picked[2]
            closest = min(message_records, key=lambda item: abs((item[0] - target_ts).total_seconds()))
            return closest[1], closest[0].isoformat(), closest[2]

        async def sanitize_items(key: str) -> None:
            nonlocal invalid_primary_ref_count
            nonlocal invalid_ref_not_in_channel_count
            nonlocal fallback_nearest_applied_count
            nonlocal final_items_with_no_ref_count
            raw_items = payload.get(key)
            if not isinstance(raw_items, list):
                return
            sanitized: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                if key == "dynamics":
                    primary_ref_raw = str(item.get("optional_ref") or item.get("primary_ref") or "").strip()
                else:
                    primary_ref_raw = str(item.get("primary_ref") or "").strip()
                primary_ref = None
                if primary_ref_raw:
                    if not _is_valid_snowflake(primary_ref_raw):
                        invalid_primary_ref_count += 1
                    elif await ref_exists(primary_ref_raw):
                        primary_ref = primary_ref_raw
                    else:
                        invalid_ref_not_in_channel_count += 1
                refs = await normalize_refs(item.get("refs"))
                message_ids = await normalize_refs(item.get("message_ids"))
                candidates = [ref for ref in [primary_ref] + refs + message_ids if ref]
                primary_ref = candidates[0] if candidates else None
                parsed_ts = _parse_ts(_normalize_ts_value(item.get("ts")))
                nearest_id, nearest_ts, _nearest_author = pick_nearest_record(parsed_ts)
                fallback_ts = nearest_ts
                if primary_ref is None:
                    if refs:
                        primary_ref = refs[0]
                    elif parsed_ts and range_start and range_end:
                        nearest = await self._database.fetch_nearest_message_id_in_range(
                            channel_id=channel_id,
                            start_ts=range_start,
                            end_ts=range_end,
                            ts=parsed_ts.isoformat(),
                        )
                        if nearest:
                            primary_ref = nearest
                            fallback_nearest_applied_count += 1
                    elif range_start and range_end:
                        start_dt = _parse_ts(range_start)
                        end_dt = _parse_ts(range_end)
                        if start_dt and end_dt:
                            midpoint = start_dt + (end_dt - start_dt) / 2
                            nearest = await self._database.fetch_nearest_message_id_in_range(
                                channel_id=channel_id,
                                start_ts=range_start,
                                end_ts=range_end,
                                ts=midpoint.isoformat(),
                            )
                            if nearest:
                                primary_ref = nearest
                                fallback_nearest_applied_count += 1
                if primary_ref:
                    candidates = [primary_ref] + [ref for ref in refs if ref != primary_ref]
                ts = normalize_ts(item.get("ts"), candidates, fallback_ts)
                if primary_ref and not ts:
                    ts = message_ts_map.get(primary_ref)
                if primary_ref and not ts:
                    record = await self._database.fetch_message_by_id(
                        channel_id=channel_id,
                        message_id=primary_ref,
                    )
                    record_ts = _row_get(record, "ts")
                    if record_ts:
                        ts = _normalize_ts_value(record_ts)
                if key == "moments":
                    text = str(item.get("summary_text") or item.get("text") or "").strip()
                elif key == "quotes":
                    text = str(item.get("quote_text") or item.get("text") or "").strip()
                else:
                    text = str(item.get("dynamic_text") or item.get("text") or "").strip()
                if not text:
                    continue
                author_id = str(item.get("author_id") or "") or None
                if not author_id and primary_ref:
                    author_id = message_author_map.get(primary_ref)
                if primary_ref is None:
                    final_items_with_no_ref_count += 1
                sanitized.append(
                    {
                        "ts": ts,
                        "text": text,
                        "author_id": author_id,
                        "message_ids": candidates,
                    }
                )
            payload[key] = sanitized

        async def sanitize_impacts(key: str) -> None:
            nonlocal invalid_ref_not_in_channel_count
            nonlocal invalid_ref_format_count
            nonlocal final_items_with_no_ref_count
            raw_items = payload.get(key)
            if not isinstance(raw_items, list):
                return
            sanitized: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                message_id_raw = str(item.get("message_id") or "").strip()
                message_id = None
                if message_id_raw:
                    if not _is_valid_snowflake(message_id_raw):
                        invalid_ref_format_count += 1
                    elif await ref_exists(message_id_raw):
                        message_id = message_id_raw
                    else:
                        invalid_ref_not_in_channel_count += 1
                ts = normalize_ts(item.get("ts"), [message_id] if message_id else [], None)
                if message_id and not ts:
                    ts = message_ts_map.get(message_id)
                reason = str(item.get("reason") or "").strip()
                if not reason:
                    continue
                if message_id is None:
                    final_items_with_no_ref_count += 1
                sanitized.append(
                    {
                        "author_id": item.get("author_id"),
                        "reason": reason,
                        "ts": ts,
                        "message_id": message_id,
                    }
                )
            payload[key] = sanitized

        await sanitize_items("moments")
        await sanitize_items("quotes")
        await sanitize_items("iconic_quotes")
        await sanitize_items("dynamics")
        await sanitize_impacts("degrade_list")
        await sanitize_impacts("invigorate_list")
        logger.info(
            "Summary AI ref diagnostics: invalid_primary_ref=%s invalid_ref_format=%s invalid_ref_not_in_channel=%s "
            "fallback_nearest_applied=%s items_no_ref=%s",
            invalid_primary_ref_count,
            invalid_ref_format_count,
            invalid_ref_not_in_channel_count,
            fallback_nearest_applied_count,
            final_items_with_no_ref_count,
        )

    def _extract_themes(self, messages: list[dict[str, Any]], config: dict[str, Any], tier: str) -> list[str]:
        counts: dict[str, int] = {}
        for msg in messages:
            content = msg.get("content") or ""
            for word in _extract_keywords(content):
                if word in ITALIAN_STOPWORDS:
                    continue
                if _is_theme_noise(word):
                    continue
                counts[word] = counts.get(word, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        limit = _tier_limit(config, tier, "themes", 6)
        themes = [word for word, _ in ranked]
        return _trim_theme_list(themes, limit)

    def _extract_moments(
        self,
        messages: list[dict[str, Any]],
        config: dict[str, Any],
        tier: str,
        *,
        granularity_hint: str | None = None,
    ) -> list[SummaryItem]:
        limit = _tier_limit(config, tier, "moments", 5)
        buckets = _bucket_messages_by_time(messages, limit)
        if not buckets:
            return []
        items: list[SummaryItem] = []
        for idx, bucket in enumerate(buckets):
            text = _build_bucket_summary(bucket, idx, len(buckets), granularity_hint=granularity_hint)
            message_ids = bucket["message_ids"]
            items.append(
                SummaryItem(
                    ts=bucket["representative_ts"],
                    text=text,
                    author_id=bucket.get("top_author_id"),
                    message_ids=message_ids[:3],
                    cluster_key=bucket.get("cluster_key"),
                    in_call=bool(bucket.get("in_call_count", 0)),
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
        candidates = sample_messages_time_distributed(candidates, max_items=limit, buckets=min(6, max(1, limit)))
        output: list[SummaryQuote] = []
        for msg in candidates[:limit]:
            in_call = bool((msg.get("meta") or {}).get("in_call"))
            output.append(
                SummaryQuote(
                    ts=msg.get("ts") or None,
                    text=_shorten(msg.get("content") or ""),
                    author_id=msg.get("author_id"),
                    message_ids=[str(msg.get("message_id"))] if msg.get("message_id") else [],
                    in_call=in_call,
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
        any_in_call = _any_in_call(messages)
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
                    in_call=any_in_call,
                )
            )
        if top_author_share > 0.4:
            dynamics.append(
                SummaryItem(
                    ts=_pick_ts(messages),
                    text="Conversazione concentrata su pochi utenti.",
                    author_id=top_author,
                    message_ids=[primary_id] if primary_id else [],
                    in_call=any_in_call,
                )
            )
        if negativity_hits > 0:
            dynamics.append(
                SummaryItem(
                    ts=_pick_ts(messages),
                    text="Toni pungenti o negativi compaiono nella finestra.",
                    author_id=top_author,
                    message_ids=[primary_id] if primary_id else [],
                    in_call=any_in_call,
                )
            )
        if not dynamics:
            dynamics.append(
                SummaryItem(
                    ts=_pick_ts(messages),
                    text="Dinamica complessivamente lineare.",
                    author_id=top_author,
                    message_ids=[primary_id] if primary_id else [],
                    in_call=any_in_call,
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
            reason = _humanize_local_impact_reason(
                msg=msg,
                polarity="neg",
                intensity=int(data["neg"] or 0),
            )
            degrade.append(
                SummaryImpact(
                    author_id=author_id,
                    reason=reason,
                    ts=msg.get("ts") or None,
                    message_id=str(msg.get("message_id")) if msg.get("message_id") else None,
                )
            )
        for author_id, data in invigorate_ranked[:limit]:
            if data["pos"] <= 0:
                continue
            msg = data["last"]
            reason = _humanize_local_impact_reason(
                msg=msg,
                polarity="pos",
                intensity=int(data["pos"] or 0),
            )
            invigorate.append(
                SummaryImpact(
                    author_id=author_id,
                    reason=reason,
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


def _is_valid_snowflake(value: str | None) -> bool:
    if not value:
        return False
    return bool(re.fullmatch(r"\\d{17,20}", str(value)))


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


def _any_in_call(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        if (msg.get("meta") or {}).get("in_call"):
            return True
    return False


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


def _humanize_local_impact_reason(
    *,
    msg: dict[str, Any],
    polarity: str,
    intensity: int,
) -> str:
    content_raw = " ".join(str(msg.get("content") or "").split())
    content = _clean_text(content_raw)
    meta = msg.get("meta") or {}
    reason_code = str(meta.get("reason_code") or msg.get("reason_code") or "").strip()
    mention_count = len(re.findall(r"<@!?\d+>", str(msg.get("content") or "")))
    has_caps = any(len(token) >= 4 and token.isupper() for token in re.findall(r"\b[A-ZÀ-Ý]{4,}\b", str(msg.get("content") or "")))
    if polarity == "neg":
        if reason_code:
            label = resolve_aura_reason_label(reason_code, audience="mod")
            if label and "attività registrata" not in label:
                return f"Ha inciso soprattutto con {label.lower()}, irrigidendo il clima della conversazione."
        if mention_count and re.search(r"\b(tu|voi|sempre|mai|basta|serio|assurdo|colpa)\b", content):
            return "Ha alzato la tensione con richiami diretti e risposte che hanno spostato il focus sullo scontro."
        if has_caps or "!!" in content_raw or "??" in content_raw:
            return "Ha dato più pressione alla discussione con messaggi molto accesi che hanno reso il tono più duro."
        if re.search(r"\b(insult|offes|aggress|provoc|attacc|flame|callout)\w*", content):
            return "Ha spinto il dialogo verso lo scontro con messaggi provocatori o personali."
        if intensity >= 2:
            return "Ha contribuito a irrigidire il confronto con più interventi critici ravvicinati."
        return "Ha reso il confronto meno disteso con un intervento che ha aumentato la frizione nel canale."
    if reason_code:
        label = resolve_aura_reason_label(reason_code, audience="mod")
        if label and "attività registrata" not in label:
            return f"Ha dato un contributo positivo soprattutto con {label.lower()}, aiutando a tenere il clima più sereno."
    if re.search(r"\b(grazie|brav|ottim|perfett|grande)\b", content) and mention_count:
        return "Ha alleggerito il clima con riconoscimenti diretti che hanno fatto scendere la tensione."
    if re.search(r"\b(tranquill|calma|nessun problema|ci sta|va bene|capisco)\b", content):
        return "Ha tenuto un tono rassicurante e ha riportato calma quando la conversazione rischiava di irrigidirsi."
    if re.search(r"\b(possiamo|proviamo|facciamo|vediamo|aiuto|aiut)\b", content):
        return "Ha rimesso la conversazione su un piano collaborativo proponendo una strada concreta per andare avanti."
    if intensity >= 2:
        return "Ha aiutato a tenere il clima più leggero con più messaggi costruttivi e distensivi nel periodo."
    return "Ha dato un contributo positivo con un tono tranquillo che ha reso il dialogo più facile da gestire."


def _sanitize_bullet_text(text: str) -> str:
    cleaned = " ".join(text.split())
    cleaned = re.sub(r"\\btutti+i\\b", "tutti", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\\bbuongiornoo+\\b", "buongiorno", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _is_template_bullet(text: str) -> bool:
    return "nel periodo spiccano" in text.lower()


def _sanitize_summary_items(
    items: list[SummaryItem] | list[SummaryQuote],
    *,
    drop_templates: bool = True,
    drop_slash_tokens: bool = False,
) -> list[SummaryItem] | list[SummaryQuote]:
    sanitized: list[Any] = []
    for item in items:
        text = _sanitize_bullet_text(item.text)
        if not text:
            continue
        if drop_templates and _is_template_bullet(text):
            continue
        if drop_slash_tokens and _looks_like_slash_tokens(text):
            continue
        item.text = text
        sanitized.append(item)
    return sanitized


def _dedupe_summary_items(
    primary: list[SummaryItem] | list[SummaryQuote],
    fallback: list[SummaryItem] | list[SummaryQuote],
    *,
    limit: int,
) -> list[SummaryItem] | list[SummaryQuote]:
    output: list[Any] = []
    seen_text: set[str] = set()
    seen_keywords: list[set[str]] = []
    seen_message_ids: set[str] = set()

    def add_item(item: Any) -> None:
        text = item.text
        if text in seen_text:
            return
        message_ids = {str(mid) for mid in (getattr(item, "message_ids", []) or []) if str(mid)}
        if message_ids and seen_message_ids.intersection(message_ids):
            return
        keywords = set(_extract_keywords(_clean_text(text)))
        if keywords:
            for existing in seen_keywords:
                if _keyword_overlap(existing, keywords) >= 0.6:
                    return
            seen_keywords.append(keywords)
        seen_text.add(text)
        seen_message_ids.update(message_ids)
        output.append(item)

    for item in list(primary) + list(fallback):
        if len(output) >= limit:
            break
        add_item(item)
    return output


def _sort_moments_chronologically(items: list[SummaryItem]) -> list[SummaryItem]:
    def sort_key(item: SummaryItem) -> tuple[bool, str]:
        ts = item.ts or ""
        return (not bool(ts), ts)

    return sorted(items, key=sort_key)


def _sort_quotes_chronologically(items: list[SummaryQuote]) -> list[SummaryQuote]:
    def sort_key(item: SummaryQuote) -> tuple[bool, str]:
        ts = item.ts or ""
        return (not bool(ts), ts)

    return sorted(items, key=sort_key)


def _sort_impacts_chronologically(items: list[SummaryImpact]) -> list[SummaryImpact]:
    def sort_key(item: SummaryImpact) -> tuple[bool, str]:
        ts = item.ts or ""
        return (not bool(ts), ts)

    return sorted(items, key=sort_key)


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
    topic = ", ".join(keywords) if keywords else "diversi temi"
    action = _segment_action(segment)
    templates = [
        "La conversazione tocca {topic}, mentre {action}.",
        "Emergono spunti su {topic}, con {action}.",
        "Si apre un confronto su {topic}: {action}.",
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


def _trim_theme_list(items: list[str], limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = _sanitize_theme_token(item)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        output.append(cleaned)
        if len(output) >= limit:
            break
    return output


def _sanitize_themes(raw: Iterable[Any], *, limit: int) -> list[str]:
    themes = [str(item).strip() for item in raw if str(item).strip()]
    return _trim_theme_list(themes, limit=limit)


def _is_theme_noise(token: str) -> bool:
    if not token:
        return True
    if token.isdigit():
        return True
    if _is_valid_snowflake(token):
        return True
    if len(token) > 25:
        return True
    digits = sum(1 for char in token if char.isdigit())
    if digits >= max(4, int(len(token) * 0.6)):
        return True
    return False


def _sanitize_theme_token(token: str) -> str | None:
    cleaned = re.sub(r"[^0-9a-zA-Zàèéìòù_]", "", token.lower())
    if not cleaned:
        return None
    cleaned = THEME_EN_TO_IT.get(cleaned, cleaned)
    if cleaned in ITALIAN_STOPWORDS:
        return None
    if _is_theme_noise(cleaned):
        return None
    return cleaned


def _looks_like_slash_tokens(text: str) -> bool:
    return bool(re.search(r".*(\\w+\\s*/\\s*){2,}\\w+.*", text))


def _filter_invalid_moments(moments: list[SummaryItem]) -> list[SummaryItem]:
    return [moment for moment in moments if not _looks_like_slash_tokens(moment.text)]


def _bucket_messages_by_time(messages: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
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
        in_call = bool((msg.get("meta") or {}).get("in_call"))
        enriched.append(
            {
                "message_id": msg.get("message_id"),
                "author_id": msg.get("author_id"),
                "ts": ts,
                "cleaned": cleaned,
                "keywords": keywords,
                "in_call": in_call,
            }
        )
    if not enriched:
        return []
    enriched.sort(key=lambda item: item["ts"])
    start_ts = enriched[0]["ts"]
    end_ts = enriched[-1]["ts"]
    total_seconds = max(1.0, (end_ts - start_ts).total_seconds())
    bucket_count = min(limit, 10, max(1, len(enriched)))
    buckets: list[dict[str, Any]] = []
    for idx in range(bucket_count):
        buckets.append(
            {
                "start": start_ts + (end_ts - start_ts) * (idx / bucket_count),
                "end": start_ts + (end_ts - start_ts) * ((idx + 1) / bucket_count),
                "message_ids": [],
                "authors": {},
                "keyword_counts": {},
                "negativity_hits": 0,
                "positive_hits": 0,
                "questions": 0,
                "representative_ts": None,
                "top_author_id": None,
                "cluster_key": None,
                "in_call_count": 0,
            }
        )
    for msg in enriched:
        rel = (msg["ts"] - start_ts).total_seconds() / total_seconds
        idx = min(bucket_count - 1, max(0, int(rel * bucket_count)))
        bucket = buckets[idx]
        bucket["message_ids"].append(str(msg.get("message_id")) if msg.get("message_id") else None)
        author_id = str(msg.get("author_id") or "")
        if author_id:
            bucket["authors"][author_id] = bucket["authors"].get(author_id, 0) + 1
        for word in msg["keywords"]:
            if _is_theme_noise(word):
                continue
            bucket["keyword_counts"][word] = bucket["keyword_counts"].get(word, 0) + 1
        bucket["negativity_hits"] += _count_keywords(msg["cleaned"], NEGATIVE_KEYWORDS)
        bucket["positive_hits"] += _count_keywords(msg["cleaned"], POSITIVE_KEYWORDS)
        bucket["questions"] += msg["cleaned"].count("?")
        if msg.get("in_call"):
            bucket["in_call_count"] += 1
        if bucket["representative_ts"] is None:
            bucket["representative_ts"] = msg["ts"].isoformat()
    output: list[dict[str, Any]] = []
    for bucket in buckets:
        if not bucket["message_ids"]:
            continue
        if bucket["authors"]:
            bucket["top_author_id"] = max(bucket["authors"].items(), key=lambda item: item[1])[0]
        keywords = _rank_keywords(_expand_keywords(bucket["keyword_counts"]))
        bucket["cluster_key"] = "_".join(keywords) if keywords else "misc"
        bucket["message_ids"] = [mid for mid in bucket["message_ids"] if mid]
        if bucket["representative_ts"] is None:
            bucket["representative_ts"] = start_ts.isoformat()
        output.append(bucket)
    return output


def _build_bucket_summary(
    bucket: dict[str, Any],
    index: int,
    total: int,
    *,
    granularity_hint: str | None = None,
) -> str:
    keywords = _rank_keywords(_expand_keywords(bucket.get("keyword_counts", {})))
    keywords = _trim_theme_list(keywords, limit=2)
    if index == 0:
        prefix = "All'inizio"
    elif index >= total - 1:
        prefix = "Verso la fine"
    elif index == 1:
        prefix = "Poco dopo"
    else:
        prefix = "Più tardi"
    if granularity_hint == "days" and index == 0:
        prefix = "Nel corso della giornata"
    elif granularity_hint == "weeks" and index == 0:
        prefix = "Nel corso della settimana"
    tone = _bucket_tone(bucket)
    if keywords:
        topic = " e ".join(keywords)
        return f"{prefix} emergono spunti su {topic}, con {tone}."
    return f"{prefix} il confronto procede con {tone}."


def _bucket_tone(bucket: dict[str, Any]) -> str:
    if bucket.get("negativity_hits", 0) > 0:
        return "tensione e richieste di chiarimento"
    if bucket.get("positive_hits", 0) > 0:
        return "tono collaborativo e scambi costruttivi"
    if bucket.get("questions", 0) > 1:
        return "domande e chiarimenti in sequenza"
    return "aggiornamenti e scambi regolari"


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


def _extract_json_object_candidate(raw: str) -> str | None:
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(raw)):
        ch = raw[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return raw[start : idx + 1]
    return None


def _normalize_json_candidate(candidate: str) -> tuple[str, bool]:
    normalized = candidate.strip().lstrip("\ufeff")
    changed = False
    trailing_commas_removed = re.sub(r",(\s*[}\]])", r"\1", normalized)
    if trailing_commas_removed != normalized:
        normalized = trailing_commas_removed
        changed = True
    return normalized, changed


def _parse_json_candidate(candidate: str) -> tuple[dict[str, Any] | None, bool]:
    normalized, changed = _normalize_json_candidate(candidate)
    if not normalized:
        return None, False
    try:
        parsed = json.loads(normalized)
        if isinstance(parsed, dict):
            return parsed, changed
    except json.JSONDecodeError:
        return None, changed
    return None, changed


def _parse_json_safe(text: str) -> SummaryJsonParseResult:
    if not text:
        return SummaryJsonParseResult(payload=None, extraction_strategy="none")
    raw = text.strip()
    if not raw:
        return SummaryJsonParseResult(payload=None, extraction_strategy="none")

    direct_payload, direct_normalized = _parse_json_candidate(raw)
    if direct_payload is not None:
        return SummaryJsonParseResult(
            payload=direct_payload,
            extraction_strategy="direct",
            normalized_invalid_json=direct_normalized,
        )

    if "```" in raw:
        for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE):
            fenced = match.group(1).strip()
            if not fenced:
                continue
            parsed, normalized = _parse_json_candidate(fenced)
            if parsed is not None:
                return SummaryJsonParseResult(
                    payload=parsed,
                    extraction_strategy="code_fence",
                    extracted_json_from_code_fence=True,
                    normalized_invalid_json=normalized,
                )
            extracted = _extract_json_object_candidate(fenced)
            if extracted:
                parsed, normalized = _parse_json_candidate(extracted)
                if parsed is not None:
                    return SummaryJsonParseResult(
                        payload=parsed,
                        extraction_strategy="code_fence",
                        extracted_json_from_code_fence=True,
                        extracted_json_from_text_wrapper=True,
                        normalized_invalid_json=normalized,
                    )

    extracted = _extract_json_object_candidate(raw)
    if extracted:
        parsed, normalized = _parse_json_candidate(extracted)
        if parsed is not None:
            return SummaryJsonParseResult(
                payload=parsed,
                extraction_strategy="first_object",
                extracted_json_from_text_wrapper=True,
                normalized_invalid_json=normalized,
            )

    preview = raw.replace("\n", " ")[:240]
    logger.debug("summary ai parse failed preview=%r", preview)
    return SummaryJsonParseResult(payload=None, extraction_strategy="none")


def _validate_summary_payload(payload: dict[str, Any] | None, schema_mode: str) -> str | None:
    if payload is None:
        return "payload"
    required_fields = ("themes", "moments", "advice") if schema_mode == "compact" else ("themes", "moments", "advice")
    for field_name in required_fields:
        value = payload.get(field_name)
        if not isinstance(value, list):
            return field_name
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


def _is_negative_impact_reason(reason: str) -> bool:
    normalized = _clean_text(reason)
    if not normalized:
        return False
    if _count_keywords(normalized, NEGATIVE_KEYWORDS) > 0:
        return True
    return bool(re.search(r"\b(insult|offes|aggress|provoc|callout|attacc|flame|caps)\w*", normalized))


def _is_positive_impact_reason(reason: str) -> bool:
    normalized = _clean_text(reason)
    if not normalized:
        return False
    if _count_keywords(normalized, POSITIVE_KEYWORDS) > 0:
        return True
    return bool(re.search(r"\b(costrutt|calm|distens|support|media|aiut|gentil|rispett)\w*", normalized))


def _sanitize_and_resolve_impacts(
    degrade: list[SummaryImpact],
    invigorate: list[SummaryImpact],
) -> tuple[list[SummaryImpact], list[SummaryImpact]]:
    deduped_degrade = _dedupe_impacts(degrade)
    deduped_invigorate = _dedupe_impacts(invigorate)

    filtered_degrade = [impact for impact in deduped_degrade if impact.message_id or _is_negative_impact_reason(impact.reason)]
    filtered_invigorate = [
        impact for impact in deduped_invigorate if impact.message_id or _is_positive_impact_reason(impact.reason)
    ]

    per_author: dict[str, dict[str, Any]] = {}
    for impact in filtered_degrade:
        if not impact.author_id:
            continue
        record = per_author.setdefault(impact.author_id, {"neg": 0, "pos": 0})
        record["neg"] += 1 + (1 if _is_negative_impact_reason(impact.reason) else 0)
    for impact in filtered_invigorate:
        if not impact.author_id:
            continue
        record = per_author.setdefault(impact.author_id, {"neg": 0, "pos": 0})
        record["pos"] += 1 + (1 if _is_positive_impact_reason(impact.reason) else 0)

    authors_by_message_neg: dict[str, set[str]] = {}
    authors_by_message_pos: dict[str, set[str]] = {}
    for impact in filtered_degrade:
        if impact.message_id and impact.author_id:
            authors_by_message_neg.setdefault(impact.message_id, set()).add(impact.author_id)
    for impact in filtered_invigorate:
        if impact.message_id and impact.author_id:
            authors_by_message_pos.setdefault(impact.message_id, set()).add(impact.author_id)

    conflict_authors: set[str] = set()
    for message_id, neg_authors in authors_by_message_neg.items():
        pos_authors = authors_by_message_pos.get(message_id, set())
        if neg_authors & pos_authors:
            conflict_authors.update(neg_authors & pos_authors)

    tie_dropped_authors = 0
    message_conflict_dropped_authors = len(conflict_authors)
    allowed_side: dict[str, str] = {}
    for author_id, weights in per_author.items():
        if author_id in conflict_authors:
            allowed_side[author_id] = "none"
            continue
        if weights["pos"] > weights["neg"]:
            allowed_side[author_id] = "pos"
        elif weights["neg"] > weights["pos"]:
            allowed_side[author_id] = "neg"
        else:
            allowed_side[author_id] = "none"
            tie_dropped_authors += 1

    final_degrade: list[SummaryImpact] = []
    final_invigorate: list[SummaryImpact] = []
    overlap_removed = 0
    for impact in filtered_degrade:
        if not impact.author_id:
            final_degrade.append(impact)
            continue
        if allowed_side.get(impact.author_id) == "neg":
            final_degrade.append(impact)
        else:
            overlap_removed += 1

    for impact in filtered_invigorate:
        if not impact.author_id:
            final_invigorate.append(impact)
            continue
        if allowed_side.get(impact.author_id) == "pos":
            final_invigorate.append(impact)
        else:
            overlap_removed += 1

    logger.info(
        "Summary impacts overlap resolution: overlap_removed=%s tie_dropped_authors=%s message_conflict_dropped_authors=%s final_degrade=%s final_invigorate=%s",
        overlap_removed,
        tie_dropped_authors,
        message_conflict_dropped_authors,
        len(final_degrade),
        len(final_invigorate),
    )
    return _sort_impacts_chronologically(final_degrade), _sort_impacts_chronologically(final_invigorate)


def _dedupe_impacts(items: list[SummaryImpact]) -> list[SummaryImpact]:
    seen: set[tuple[str, str, str, str]] = set()
    output: list[SummaryImpact] = []
    for item in items:
        key = (
            str(item.author_id or ""),
            str(item.message_id or ""),
            str(item.ts or ""),
            _clean_text(item.reason),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def sample_messages_time_distributed(
    messages: list[dict[str, Any]],
    *,
    max_items: int,
    buckets: int,
) -> list[dict[str, Any]]:
    if len(messages) <= max_items:
        return list(messages)
    effective_buckets = max(1, int(buckets or 1))
    parsed_rows: list[tuple[datetime, dict[str, Any]]] = []
    for msg in messages:
        ts = _parse_ts(msg.get("ts"))
        if ts is None:
            continue
        parsed_rows.append((ts, msg))
    if len(parsed_rows) <= max_items:
        return [msg for _, msg in sorted(parsed_rows, key=lambda item: item[0])]
    parsed_rows.sort(key=lambda item: item[0])
    min_ts = parsed_rows[0][0]
    max_ts = parsed_rows[-1][0]
    span_seconds = max(1.0, (max_ts - min_ts).total_seconds())
    slots: list[list[tuple[datetime, dict[str, Any]]]] = [[] for _ in range(effective_buckets)]
    for ts, msg in parsed_rows:
        rel = (ts - min_ts).total_seconds() / span_seconds
        idx = min(effective_buckets - 1, max(0, int(rel * effective_buckets)))
        slots[idx].append((ts, msg))

    per_bucket = max(1, math.ceil(max_items / effective_buckets))
    picked: list[tuple[datetime, dict[str, Any]]] = []
    slot_sizes = [len(slot) for slot in slots]
    for slot in slots:
        if not slot:
            continue
        ranked = sorted(slot, key=lambda item: _message_representativeness_score(item[1]), reverse=True)
        take = ranked[:per_bucket]
        if not take:
            take = ranked[:1]
        picked.extend(take)

    if len(picked) > max_items:
        picked.sort(key=lambda item: item[0])
        step = len(picked) / max_items
        reduced: list[tuple[datetime, dict[str, Any]]] = []
        pos = 0.0
        while len(reduced) < max_items and int(pos) < len(picked):
            reduced.append(picked[int(pos)])
            pos += step
        picked = reduced

    picked.sort(key=lambda item: item[0])
    logger.info(
        "summary: sampled_messages distribution total=%s max_items=%s buckets=%s slot_sizes=%s picked=%s",
        len(messages),
        max_items,
        effective_buckets,
        slot_sizes,
        len(picked),
    )
    return [msg for _, msg in picked]


def _message_representativeness_score(message: dict[str, Any]) -> int:
    content = str(message.get("content") or "")
    score = min(200, len(content))
    if "@" in content:
        score += 20
    if re.search(r"[😀-🙏🌀-🫶]", content):
        score += 20
    if "<:" in content or "<a:" in content:
        score += 15
    return score


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


def _moments_policy_tier(tier: str) -> str:
    if tier in {"role1", "role2", "role3", "mod"}:
        return "role3"
    return tier


def _granularity_prompt_hint(granularity_hint: str | None) -> str | None:
    if not granularity_hint:
        return None
    mapping = {
        "minutes": "riassumi per eventi ravvicinati; evidenzia picchi e svolte negli ultimi minuti",
        "hours": "riassumi per fasce orarie; evidenzia temi e cambi di tono tra le ore",
        "days": "riassumi per giorno; evidenzia cosa è successo in ciascun giorno",
        "weeks": "riassumi per settimana; evidenzia macro-temi e momenti top",
    }
    return mapping.get(granularity_hint, granularity_hint)


def _build_summary_prompt_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        return {}
    selected_keys = (
        "message_count",
        "window_minutes",
        "msg_per_min",
        "negativity_hits",
        "reply_war",
        "top1_author_share",
        "top3_author_share",
        "burst_ratio",
        "mentions_per_msg",
        "voice_minutes",
        "voice_sessions",
        "voice_segments",
    )
    compact: dict[str, Any] = {}
    for key in selected_keys:
        value = metrics.get(key)
        if value is None or value == "":
            continue
        compact[key] = value
    return compact


def _build_summary_prompt_context(summary_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(summary_context, dict):
        return {}
    compact: dict[str, Any] = {}
    for key in ("period_label", "nonce", "who_interacted_candidates"):
        value = summary_context.get(key)
        if value in (None, "", [], {}):
            continue
        compact[key] = value
    return compact


def _build_summary_prompt_payload(
    *,
    messages: list[dict[str, Any]],
    payload_base: dict[str, Any],
    system_prompt: str,
    budget: dict[str, int | str],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    max_items = int(budget["max_items"])
    min_items = int(budget["min_items"])
    buckets = int(budget["buckets"])
    per_message_char_limit = int(budget["per_message_char_limit"])
    min_per_message_char_limit = int(budget["min_per_message_char_limit"])
    total_prompt_char_budget = int(budget["total_prompt_char_budget"])
    hard_prompt_char_cap = int(budget["hard_prompt_char_cap"])
    include_kind = True
    include_voice_meta = True
    sampled_messages = sample_messages_time_distributed(messages, max_items=max_items, buckets=buckets)
    sampled_before_budget = len(sampled_messages)
    compact_messages: list[dict[str, Any]] = []
    compact_stats: dict[str, Any] = {
        "items_before": 0,
        "items_after": 0,
        "removed_duplicates": 0,
        "removed_metadata": False,
        "raw_payload_chars": 0,
    }
    user_payload = ""
    metadata_reduced = False
    guard = 0
    while guard < 12:
        guard += 1
        compact_messages, compact_stats = _build_summary_prompt_messages(
            sampled_messages,
            per_message_char_limit=per_message_char_limit,
            include_kind=include_kind,
            include_voice_meta=include_voice_meta,
        )
        payload_dict = dict(payload_base)
        payload_dict["messages"] = compact_messages
        user_payload = json.dumps(payload_dict, ensure_ascii=False, separators=(",", ":"))
        prompt_chars = len(user_payload) + len(system_prompt)
        if prompt_chars <= total_prompt_char_budget and len(user_payload) <= hard_prompt_char_cap:
            break
        if include_kind or include_voice_meta:
            include_kind = False
            include_voice_meta = False
            metadata_reduced = True
            continue
        if per_message_char_limit > min_per_message_char_limit:
            per_message_char_limit = max(min_per_message_char_limit, int(per_message_char_limit * 0.82))
            continue
        if max_items > min_items:
            max_items = max(min_items, int(max_items * 0.82))
            buckets = max(3, min(buckets, max_items))
            sampled_messages = sample_messages_time_distributed(messages, max_items=max_items, buckets=buckets)
            continue
        while compact_messages and (len(user_payload) + len(system_prompt) > total_prompt_char_budget or len(user_payload) > hard_prompt_char_cap):
            compact_messages = compact_messages[:-1]
            payload_dict["messages"] = compact_messages
            user_payload = json.dumps(payload_dict, ensure_ascii=False, separators=(",", ":"))
        break
    compact_stats.update(
        {
            "sampled_before_budget": sampled_before_budget,
            "sampled_after_budget": len(compact_messages),
            "per_message_char_limit": per_message_char_limit,
            "max_items_used": max_items,
            "buckets_used": buckets,
            "metadata_reduced": metadata_reduced,
            "prompt_chars_final": len(user_payload) + len(system_prompt),
            "prompt_payload_chars_final": len(user_payload),
        }
    )
    return user_payload, compact_messages, compact_stats


def _build_summary_prompt_messages(
    messages: list[dict[str, Any]],
    *,
    per_message_char_limit: int = SUMMARY_PROMPT_MESSAGE_CHAR_LIMIT,
    include_kind: bool = True,
    include_voice_meta: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    compact_rows: list[dict[str, Any]] = []
    seen_fingerprints: set[tuple[str, str, str]] = set()
    removed_duplicates = 0
    removed_metadata = False
    raw_payload_chars = 0
    for message in messages:
        meta = message.get("meta") or {}
        text = _compact_summary_prompt_text(message.get("content"), limit=per_message_char_limit)
        if not text:
            continue
        author_id = str(message.get("author_id") or "")
        kind = str(meta.get("kind") or "")
        fingerprint = (
            author_id,
            kind,
            _duplicate_message_fingerprint(text),
        )
        if fingerprint in seen_fingerprints:
            removed_duplicates += 1
            continue
        seen_fingerprints.add(fingerprint)
        row = {
            "i": str(message.get("message_id") or ""),
            "t": message.get("ts"),
            "a": author_id,
            "x": text,
        }
        if include_kind and kind:
            row["k"] = kind
            removed_metadata = True
        if include_voice_meta and meta.get("in_call"):
            row["vc"] = 1
            removed_metadata = True
        compact_rows.append(row)
        raw_payload_chars += len(json.dumps(message, ensure_ascii=False))
    return compact_rows, {
        "items_before": len(messages),
        "items_after": len(compact_rows),
        "removed_duplicates": removed_duplicates,
        "removed_metadata": removed_metadata or (removed_duplicates > 0),
        "raw_payload_chars": raw_payload_chars,
    }


def _compact_summary_prompt_text(text: Any, *, limit: int = SUMMARY_PROMPT_MESSAGE_CHAR_LIMIT) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return _compact_text_word_boundary(cleaned, limit)


def _duplicate_message_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if len(normalized) > SUMMARY_PROMPT_DUPLICATE_FINGERPRINT_LIMIT:
        normalized = normalized[:SUMMARY_PROMPT_DUPLICATE_FINGERPRINT_LIMIT]
    return normalized


def _compact_text_word_boundary(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    if limit <= 1:
        return "…"
    cut = cleaned[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    if not cut:
        cut = cleaned[: limit - 1]
    return f"{cut}…"


def _compact_moment_items(items: list[SummaryItem], *, limit: int) -> list[SummaryItem]:
    output: list[SummaryItem] = []
    for item in items:
        item.text = _compact_text_word_boundary(item.text or "", limit)
        output.append(item)
    return output


def cast_items(items: Iterable[Any], target: type) -> list[Any]:
    output: list[Any] = []
    for item in items:
        if isinstance(item, target):
            output.append(item)
    return output


def _local_period_description(period_prefix: str, color: str) -> str:
    color_label = str(color or "nero").strip().lower()
    mapping = {
        "verde": ("sano", "🙂"),
        "giallo": ("delicato", "😐"),
        "rosso": ("teso", "😟"),
        "nero": ("critico", "😨"),
    }
    adjective, emoji = mapping.get(color_label, ("critico", "😨"))
    return f"{period_prefix} il barcello è stato {adjective} {emoji}."
