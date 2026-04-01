from __future__ import annotations

import json
import logging
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.services.database import DatabaseService

logger = logging.getLogger(__name__)

DEFAULT_COLOR_RANGES = [
    {"min": 0, "max": 20, "color": "nero", "label": "nero"},
    {"min": 21, "max": 40, "color": "rosso", "label": "rosso"},
    {"min": 41, "max": 60, "color": "giallo", "label": "giallo"},
    {"min": 61, "max": 100, "color": "verde", "label": "verde"},
]

NEGATIVE_KEYWORDS = [
    "stupido", "idiota", "scemo", "cretino", "ridicolo", "patetico", "fallito", "imbecille",
    "merda", "schifo", "odio", "vergogna", "basta", "tossico", "marcio", "pena", "disastro",
]

PROFANITY_KEYWORDS = [
    "cazzo", "caxxo", "merda", "merd", "stronzo", "stronz", "vaffanculo", "fanculo", "minchia",
    "porca", "troia", "puttana", "bastardo", "coglione", "cogliona", "rompicazzo", "incazzat",
    "porco", "cagare", "cacata", "fottere", "porcod", "cacchio", "cristo",
]

INSULT_KEYWORDS = [
    "ridicolo", "idiota", "stupido", "scemo", "patetico", "fallito", "imbecille", "pagliaccio",
    "deficiente", "mongolo", "ritardato", "lurido", "verme", "clown", "ignorante", "inetto",
    "minus habens", "fallit", "pagliacc",
]

BLASPHEMY_PATTERNS = [
    r"\bporco\s+dio\b",
    r"\bdio\s+cane\b",
    r"\bdio\s+boia\b",
    r"\bmadonna\s+puttana\b",
    r"\bporca\s+madonna\b",
    r"\bgesu\s+cristo\b.{0,8}\b(merda|cane|boia|bastardo)\b",
]

AGGRESSIVE_PATTERNS = [
    r"\b(zitto|taci|sparisci|smettila|piantala)\b",
    r"\b(ma che|ma quanto|ma sei)\b",
    r"\bvergognati\b",
]

CALMING_KEYWORDS = [
    "calma",
    "tranquilli",
    "non litigate",
    "pace",
    "respiriamo",
    "chiudiamola qui",
    "basta litigare",
]

VENTING_PATTERNS = [
    r"\bio\b.*\b(sto|sono)\b.*\b(incazzat|nervos|esaust|stanch|arrabbiat)",
    r"\bche giornat[ae]\b",
    r"\bmi gira(no)?\b",
]

SECOND_PERSON_PATTERNS = [
    r"\btu\b",
    r"\bsei\b",
    r"\bstai\b",
    r"\bfai\b",
    r"\bdici\b",
    r"\bti\b",
]

CHALLENGE_PATTERNS = [
    r"\bma che .* dici\b",
    r"\bchi ti credi\b",
    r"\bhai rotto\b",
    r"\bnon capisci niente\b",
    r"\bimpara a\b",
    r"\bma perche\b",
    r"\bperche\?+",
]

PLAYFUL_MARKERS = [
    "ahah", "haha", "lol", "lmao", "xd", "😂", "🤣", "scherzo", "ironico", "meme", "jk", "kappa", "xD",
]
AFFECTIONATE_MARKERS = [
    "tvb", "ti voglio bene", "bro", "fra", "tesoro", "amore", "❤️", "💙", "💚", "🫶",
]

DEFAULT_SCORE_WEIGHTS = {
    "msg_rate": {"threshold": 5, "scale": 2, "cap": 30},
    "caps": {"threshold": 0.3, "scale": 50, "cap": 20},
    "negativity": {"per_hit": 5, "cap": 25},
    "mentions": {"threshold": 1, "scale": 5, "cap": 20},
    "reply_war": {"penalty": 15},
    "top1_author_share": {"threshold": 0.4, "penalty": 8},
    "top3_author_share": {"threshold": 0.75, "penalty": 10},
    "burst_ratio": {"threshold": 2.5, "penalty": 8, "max_threshold": 4.0, "max_penalty": 12},
    "contrast_per_msg": {"threshold": 0.25, "penalty": 6},
    "challenge_per_msg": {"threshold": 0.08, "penalty": 6},
}

DEFAULT_WEIGHT_MULTIPLIERS = {
    "msg_rate": 1.0,
    "caps": 1.0,
    "mentions": 1.0,
    "negativity": 1.0,
    "top3": 1.0,
    "burst": 1.0,
    "contrast": 1.0,
    "challenge": 1.0,
}

DEFAULT_MITIGATION_FACTORS = {
    "msg_rate_factor": 0.8,
    "caps_factor": 0.7,
}


@dataclass(frozen=True)
class BarcelloResult:
    score: int
    color: str
    window_start_ts: str = ""
    window_end_ts: str = ""
    reasons: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    trend: Optional[dict[str, Any]] = None
    advice: Optional[list[str]] = None


class BarcelloService:
    def __init__(self, database: DatabaseService, *, cache_ttl_seconds: int = 60) -> None:
        self._database = database
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[tuple[str, str, int, str], tuple[float, BarcelloResult]] = {}
        self._metrics = {
            "cache_hit": 0,
            "last_compute_ts": None,
            "last_score_by_channel": {},
            "last_score_by_pair": {},
        }

    def _mget(self, message: Any, key: str, default: Any = None) -> Any:
        try:
            return message[key]
        except Exception:
            try:
                return message.get(key, default)
            except Exception:
                return default

    async def compute_channel(
        self,
        guild_id: str,
        channel_id: str,
        window_minutes: int,
        now_ts: Optional[str] = None,
    ) -> BarcelloResult:
        end_dt = self._parse_ts(now_ts) if now_ts else datetime.now(timezone.utc)
        window_end_ts = end_dt.isoformat()
        cache_key = (guild_id, channel_id, window_minutes, window_end_ts)
        now_epoch = datetime.now(timezone.utc).timestamp()
        cached = self._cache.get(cache_key)
        if cached and cached[0] > now_epoch:
            self._metrics["cache_hit"] += 1
            cached[1].metrics["cache_hit"] = True
            return cached[1]

        snapshot = await self._database.get_barcello_snapshot(
            guild_id=guild_id,
            channel_id=channel_id,
            window_minutes=window_minutes,
            window_end_ts=window_end_ts,
        )
        if snapshot:
            result = await self._result_from_snapshot(snapshot, end_dt, window_minutes)
            self._cache_result(cache_key, result)
            return result

        window_start_dt = end_dt - timedelta(minutes=window_minutes)
        window_start_ts = window_start_dt.isoformat()
        messages = await self._database.fetch_messages_in_range(
            channel_id=channel_id,
            start_ts=window_start_ts,
            end_ts=window_end_ts,
            limit=2000,
        )

        metrics = self._compute_metrics(messages, window_minutes)
        metrics["cache_hit"] = False
        score_config = await self._get_score_config()
        reasons, score = self._score_from_metrics(metrics, score_config)
        color = await self.get_color(score)

        trend = await self._compute_trend(guild_id, channel_id, window_minutes, window_end_ts, score, metrics)
        previous = await self._database.get_barcello_snapshot_before(
            guild_id=guild_id,
            channel_id=channel_id,
            window_minutes=window_minutes,
            window_end_ts=window_end_ts,
        )
        previous_metrics = json.loads(previous["metrics_json"]) if previous else {}
        metrics["persistence_of_conflict_vs_previous_window"] = round(
            float(metrics.get("direct_conflict_index", 0.0)) - float(previous_metrics.get("direct_conflict_index", 0.0)),
            3,
        )
        advice = self._build_advice(metrics, score)

        result = BarcelloResult(
            score=score,
            color=color,
            window_start_ts=window_start_ts,
            window_end_ts=window_end_ts,
            reasons=reasons,
            metrics=metrics,
            trend=trend,
            advice=advice,
        )

        computed_ts = datetime.now(timezone.utc).isoformat()
        await self._database.put_barcello_snapshot(
            guild_id=guild_id,
            channel_id=channel_id,
            window_minutes=window_minutes,
            window_end_ts=window_end_ts,
            score=score,
            reasons_json=json.dumps(reasons),
            metrics_json=json.dumps(metrics),
            computed_ts=computed_ts,
        )
        if hasattr(self._database, "put_barcello_window_analysis"):
            await self._database.put_barcello_window_analysis(
                guild_id=guild_id,
                channel_id=channel_id,
                window_end_ts=window_end_ts,
                window_minutes=window_minutes,
                metrics_json=json.dumps(metrics),
                reasons_json=json.dumps(reasons),
            )
        if hasattr(self._database, "put_barcello_message_classifications"):
            await self._database.put_barcello_message_classifications(
                guild_id=guild_id,
                channel_id=channel_id,
                window_end_ts=window_end_ts,
                items_json=json.dumps(metrics.get("message_classifications", [])),
            )
        self._metrics["last_compute_ts"] = computed_ts
        last_scores = self._metrics["last_score_by_channel"]
        last_scores_key = f"{guild_id}:{channel_id}"
        last_scores[last_scores_key] = score
        if len(last_scores) > 20:
            last_scores.pop(next(iter(last_scores)))

        self._cache_result(cache_key, result)
        return result

    async def get_current_color(
        self,
        guild_id: str,
        *,
        channel_id: str,
        window_minutes: int = 180,
    ) -> str:
        result = await self.compute_channel(guild_id, channel_id, window_minutes)
        return str(result.color)

    async def get_current_status(
        self,
        guild_id: str,
        *,
        channel_id: str,
        window_minutes: int = 180,
    ) -> dict[str, object]:
        result = await self.compute_channel(guild_id, channel_id, window_minutes)
        return {
            "score": result.score,
            "color": result.color,
            "reason": self._main_reason_key(result.reasons),
            "metrics": result.metrics,
            "trend": result.trend,
        }

    async def compute_pair(
        self,
        guild_id: str,
        channel_id: str,
        user_a_id: str,
        user_b_id: str,
        window_minutes: int,
        now_ts: Optional[str] = None,
    ) -> BarcelloResult:
        end_dt = self._parse_ts(now_ts) if now_ts else datetime.now(timezone.utc)
        window_end_ts = end_dt.isoformat()
        window_start_dt = end_dt - timedelta(minutes=window_minutes)
        window_start_ts = window_start_dt.isoformat()
        messages = await self._database.fetch_messages_in_range(
            channel_id=channel_id,
            start_ts=window_start_ts,
            end_ts=window_end_ts,
            limit=2000,
        )

        user_a_key = str(user_a_id)
        user_b_key = str(user_b_id)
        pair_messages = [
            message
            for message in messages
            if (self._mget(message, "author_id") or "") in {user_a_key, user_b_key}
        ]

        metrics = self._compute_metrics(pair_messages, window_minutes)
        metrics["cache_hit"] = False
        pair_metrics = self._compute_pair_metrics(pair_messages, user_a_key, user_b_key)
        metrics.update(pair_metrics)
        score_config = await self._get_score_config()
        reasons, score = self._score_from_metrics(metrics, score_config)
        color = await self.get_color(score)

        pair_key = ":".join(sorted([user_a_key, user_b_key]))
        last_scores = self._metrics["last_score_by_pair"]
        previous_score = last_scores.get(pair_key)
        trend = self._build_trend(score, previous_score) if previous_score is not None else None
        last_scores[pair_key] = score
        if len(last_scores) > 50:
            last_scores.pop(next(iter(last_scores)))

        advice = self._build_advice(metrics, score)

        return BarcelloResult(
            score=score,
            color=color,
            window_start_ts=window_start_ts,
            window_end_ts=window_end_ts,
            reasons=reasons,
            metrics=metrics,
            trend=trend,
            advice=advice,
        )

    async def compute_channel_range(
        self,
        guild_id: str,
        channel_id: str,
        start_ts: str,
        end_ts: str,
    ) -> BarcelloResult:
        start_dt = self._parse_ts(start_ts)
        end_dt = self._parse_ts(end_ts)
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt
        window_start_ts = start_dt.isoformat()
        window_end_ts = end_dt.isoformat()
        window_minutes = max(1, int((end_dt - start_dt).total_seconds() / 60))
        messages = await self._database.fetch_messages_in_range(
            channel_id=channel_id,
            start_ts=window_start_ts,
            end_ts=window_end_ts,
            limit=2000,
        )
        metrics = self._compute_metrics(messages, window_minutes)
        metrics["cache_hit"] = False
        score_config = await self._get_score_config()
        reasons, score = self._score_from_metrics(metrics, score_config)
        color = await self.get_color(score)
        advice = self._build_advice(metrics, score)
        return BarcelloResult(
            score=score,
            color=color,
            window_start_ts=window_start_ts,
            window_end_ts=window_end_ts,
            reasons=reasons,
            metrics=metrics,
            trend=None,
            advice=advice,
        )

    async def compute_pair_range(
        self,
        guild_id: str,
        channel_id: str,
        user_a_id: str,
        user_b_id: str,
        start_ts: str,
        end_ts: str,
    ) -> BarcelloResult:
        start_dt = self._parse_ts(start_ts)
        end_dt = self._parse_ts(end_ts)
        if end_dt < start_dt:
            start_dt, end_dt = end_dt, start_dt
        window_start_ts = start_dt.isoformat()
        window_end_ts = end_dt.isoformat()
        window_minutes = max(1, int((end_dt - start_dt).total_seconds() / 60))
        messages = await self._database.fetch_messages_in_range(
            channel_id=channel_id,
            start_ts=window_start_ts,
            end_ts=window_end_ts,
            limit=2000,
        )
        user_a_key = str(user_a_id)
        user_b_key = str(user_b_id)
        pair_messages = [
            message
            for message in messages
            if (self._mget(message, "author_id") or "") in {user_a_key, user_b_key}
        ]
        metrics = self._compute_metrics(pair_messages, window_minutes)
        metrics["cache_hit"] = False
        pair_metrics = self._compute_pair_metrics(pair_messages, user_a_key, user_b_key)
        metrics.update(pair_metrics)
        score_config = await self._get_score_config()
        reasons, score = self._score_from_metrics(metrics, score_config)
        color = await self.get_color(score)
        advice = self._build_advice(metrics, score)
        return BarcelloResult(
            score=score,
            color=color,
            window_start_ts=window_start_ts,
            window_end_ts=window_end_ts,
            reasons=reasons,
            metrics=metrics,
            trend=None,
            advice=advice,
        )

    async def get_color(self, score: int) -> str:
        ranges = await self._get_color_ranges()
        for color_range in ranges:
            if color_range["min"] <= score <= color_range["max"]:
                return color_range.get("label") or color_range["color"]
        return ranges[-1].get("label") or ranges[-1]["color"]

    def status(self) -> dict[str, Any]:
        return {
            "active": True,
            "state": "running",
            "metrics": dict(self._metrics),
        }

    @staticmethod
    def _clamp_score(score: float) -> int:
        return max(0, min(100, int(round(score))))

    async def _get_color_ranges(self) -> list[dict[str, Any]]:
        raw = await self._database.get_setting("barcello.color_ranges")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    return sorted(parsed, key=lambda item: item.get("min", 0))
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in setting barcello.color_ranges")
        return DEFAULT_COLOR_RANGES

    async def _get_score_config(self) -> dict[str, Any]:
        raw = await self._database.get_setting("barcello.weights_json")
        base = {
            "rules": DEFAULT_SCORE_WEIGHTS,
            "weights": DEFAULT_WEIGHT_MULTIPLIERS,
            "mitigation": DEFAULT_MITIGATION_FACTORS,
        }
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    rules = dict(DEFAULT_SCORE_WEIGHTS)
                    weights = dict(DEFAULT_WEIGHT_MULTIPLIERS)
                    mitigation = dict(DEFAULT_MITIGATION_FACTORS)
                    if "weights" in parsed or "mitigation" in parsed or "rules" in parsed:
                        if isinstance(parsed.get("rules"), dict):
                            for key, value in parsed["rules"].items():
                                if isinstance(value, dict) and isinstance(rules.get(key), dict):
                                    rules[key] = {**rules.get(key, {}), **value}
                                else:
                                    rules[key] = value
                        if isinstance(parsed.get("weights"), dict):
                            weights.update(parsed.get("weights", {}))
                        if isinstance(parsed.get("mitigation"), dict):
                            mitigation.update(parsed.get("mitigation", {}))
                    else:
                        for key, value in parsed.items():
                            if isinstance(value, dict) and isinstance(rules.get(key), dict):
                                rules[key] = {**rules.get(key, {}), **value}
                            else:
                                rules[key] = value
                    return {"rules": rules, "weights": weights, "mitigation": mitigation}
            except json.JSONDecodeError:
                logger.warning("Invalid JSON in setting barcello.weights_json")
        return base

    async def _compute_trend(
        self,
        guild_id: str,
        channel_id: str,
        window_minutes: int,
        window_end_ts: str,
        score: int,
        current_metrics: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        previous = await self._database.get_barcello_snapshot_before(
            guild_id=guild_id,
            channel_id=channel_id,
            window_minutes=window_minutes,
            window_end_ts=window_end_ts,
        )
        if not previous:
            return None
        prev_score = int(previous["score"])
        previous_metrics_raw = previous["metrics_json"] if "metrics_json" in previous.keys() else ""
        previous_metrics = json.loads(previous_metrics_raw) if previous_metrics_raw else {}
        direction = self._build_trend(score, prev_score)["direction"]
        current_color = await self.get_color(score)
        prev_color = await self.get_color(prev_score)
        dominant_driver = self._choose_dominant_driver(
            current_metrics=current_metrics,
            previous_metrics=previous_metrics,
            direction=direction,
            current_color=current_color,
        )
        recovery_type = self._choose_recovery_type(
            direction=direction,
            current_metrics=current_metrics,
            previous_metrics=previous_metrics,
        )
        minutes_since_same_state = await self._minutes_since_last_same_color(
            guild_id=guild_id,
            channel_id=channel_id,
            window_minutes=window_minutes,
            window_end_ts=window_end_ts,
            current_color=current_color,
            fallback_minutes=window_minutes,
        )
        return self._build_trend(
            score,
            prev_score,
            dominant_driver=dominant_driver,
            stored_color=current_color,
            prev_color=prev_color,
            recovery_type=recovery_type,
            message_count_current_window=int(current_metrics.get("message_count") or 0),
            message_count_previous_window=int(previous_metrics.get("message_count") or 0),
            minutes_since_same_state=minutes_since_same_state,
        )

    @staticmethod
    def _build_trend(
        score: int,
        prev_score: int,
        *,
        dominant_driver: str = "",
        stored_color: str = "",
        prev_color: str = "",
        recovery_type: str = "",
        message_count_current_window: int = 0,
        message_count_previous_window: int = 0,
        minutes_since_same_state: int = 0,
    ) -> dict[str, Any]:
        delta = score - prev_score
        if abs(delta) < 5:
            direction = "stable"
        elif delta > 0:
            direction = "improving"
        else:
            direction = "worsening"
        return {
            "direction": direction,
            "delta": delta,
            "delta_score": delta,
            "dominant_driver": dominant_driver,
            "stored_color": stored_color,
            "prev_color": prev_color,
            "recovery_type": recovery_type,
            "message_count_current_window": int(message_count_current_window or 0),
            "message_count_previous_window": int(message_count_previous_window or 0),
            "minutes_since_same_state": int(max(0, minutes_since_same_state or 0)),
        }

    async def _minutes_since_last_same_color(
        self,
        *,
        guild_id: str,
        channel_id: str,
        window_minutes: int,
        window_end_ts: str,
        current_color: str,
        fallback_minutes: int,
    ) -> int:
        history = []
        if hasattr(self._database, "get_barcello_snapshots_before"):
            history = await self._database.get_barcello_snapshots_before(
                guild_id=guild_id,
                channel_id=channel_id,
                window_minutes=window_minutes,
                window_end_ts=window_end_ts,
                limit=72,
            )
        if not history:
            return int(max(1, fallback_minutes))
        current_dt = self._parse_ts(window_end_ts)
        for row in history:
            candidate_score = int(row["score"])
            candidate_color = await self.get_color(candidate_score)
            if candidate_color != current_color:
                continue
            candidate_dt = self._parse_ts(row["window_end_ts"])
            delta_minutes = int(max(1, round((current_dt - candidate_dt).total_seconds() / 60.0)))
            return delta_minutes
        return int(max(1, fallback_minutes))

    def _cache_result(self, cache_key: tuple[str, str, int, str], result: BarcelloResult) -> None:
        expires = datetime.now(timezone.utc).timestamp() + self._cache_ttl
        self._cache[cache_key] = (expires, result)

    async def _result_from_snapshot(
        self,
        snapshot: Any,
        end_dt: datetime,
        window_minutes: int,
    ) -> BarcelloResult:
        window_end_ts = snapshot["window_end_ts"]
        window_start_ts = (end_dt - timedelta(minutes=window_minutes)).isoformat()
        reasons = json.loads(snapshot["reasons_json"])
        metrics = json.loads(snapshot["metrics_json"])
        metrics["cache_hit"] = False
        score = int(snapshot["score"])
        color = await self.get_color(score)
        trend = await self._compute_trend(
            snapshot["guild_id"],
            snapshot["channel_id"],
            snapshot["window_minutes"],
            window_end_ts,
            score,
            metrics,
        )
        advice = self._build_advice(metrics, score)
        return BarcelloResult(
            score=score,
            color=color,
            window_start_ts=window_start_ts,
            window_end_ts=window_end_ts,
            reasons=reasons,
            metrics=metrics,
            trend=trend,
            advice=advice,
        )

    def _compute_metrics(self, messages: list[Any], window_minutes: int) -> dict[str, Any]:
        message_count = len(messages)
        timestamps: list[datetime] = []
        authors: list[str] = []
        classifications: list[dict[str, Any]] = []
        total_letters = 0
        uppercase_letters = 0
        mention_count = 0
        reply_count = 0
        directed_conflict_count = 0
        venting_count = 0
        deescalation_count = 0
        hostility_sum = 0.0
        calming_sum = 0.0
        aggressive_directed = 0
        toxicity_sum = 0.0
        aggression_sum = 0.0
        profanity_hits_total = 0
        insult_hits_total = 0
        blasphemy_hits_total = 0
        challenge_hits_total = 0
        hostile_mentions_count = 0
        playful_hits_total = 0
        affectionate_hits_total = 0
        directed_pairs: dict[tuple[str, str], int] = {}

        for message in messages:
            author_id = str(self._mget(message, "author_id") or "unknown")
            content = (self._mget(message, "content", "") or "").strip()
            ts = self._parse_ts(self._mget(message, "ts"))
            mentions = self._parse_mentions(message, content)
            reply_to_id = str(self._mget(message, "reply_to_author_id") or "").strip()
            if reply_to_id:
                reply_count += 1
            mention_count += len(mentions)
            total_letters += sum(1 for ch in content if ch.isalpha())
            uppercase_letters += sum(1 for ch in content if ch.isalpha() and ch.isupper())

            classification = self._classify_message(
                content=content,
                author_id=author_id,
                mentions=mentions,
                reply_to_id=reply_to_id,
            )
            classifications.append(classification)
            hostility_sum += float(classification["conflict_score"])
            calming_sum += float(classification["calming_score"])
            toxicity_sum += float(classification["toxicity_score"])
            aggression_sum += float(classification["aggression_score"])
            profanity_hits_total += int(classification.get("profanity_hits") or 0)
            insult_hits_total += int(classification.get("insult_hits") or 0)
            blasphemy_hits_total += int(classification.get("blasphemy_hits") or 0)
            challenge_hits_total += int(classification.get("challenge_hits") or 0)
            hostile_mentions_count += int(classification.get("hostile_mention") or 0)
            playful_hits_total += int(classification.get("playful_hits") or 0)
            affectionate_hits_total += int(classification.get("affectionate_hits") or 0)
            if classification["classification_label"] == "directed_conflict":
                directed_conflict_count += 1
            if classification["classification_label"] == "venting":
                venting_count += 1
            if classification["classification_label"] == "deescalation":
                deescalation_count += 1
            if float(classification["aggression_score"]) > 0.55 and float(classification["directedness_score"]) >= 0.55:
                aggressive_directed += 1
                target_id = str(classification.get("primary_target_id") or "")
                if target_id:
                    directed_pairs[(author_id, target_id)] = directed_pairs.get((author_id, target_id), 0) + 1

            timestamps.append(ts)
            authors.append(author_id)

        duration_minutes = max(window_minutes, 1)
        msg_per_min = message_count / duration_minutes
        caps_ratio = (uppercase_letters / total_letters) if total_letters else 0.0
        mention_per_min = mention_count / duration_minutes
        unique_users = len(set(authors))
        reply_density = (reply_count / message_count) if message_count else 0.0
        hostility_index = (hostility_sum / message_count) if message_count else 0.0
        toxicity_index = (toxicity_sum / message_count) if message_count else 0.0
        aggression_index = (aggression_sum / message_count) if message_count else 0.0
        venting_index = (venting_count / message_count) if message_count else 0.0
        direct_conflict_index = (directed_conflict_count / message_count) if message_count else 0.0
        calming_index = (calming_sum / message_count) if message_count else 0.0
        challenge_index = (challenge_hits_total / message_count) if message_count else 0.0
        hostile_mentions_index = (hostile_mentions_count / message_count) if message_count else 0.0
        playful_index = (playful_hits_total / message_count) if message_count else 0.0
        affectionate_index = (affectionate_hits_total / message_count) if message_count else 0.0
        reply_conflict_density = (directed_conflict_count / max(reply_count, 1)) if message_count else 0.0
        proportion_of_deescalation = (deescalation_count / message_count) if message_count else 0.0
        reciprocal_conflict_pairs = self._count_reciprocal_pairs(directed_pairs)

        author_counts: dict[str, int] = {}
        for author in authors:
            author_counts[author] = author_counts.get(author, 0) + 1
        top_counts = sorted(author_counts.values(), reverse=True)
        top1_author_share = (top_counts[0] / message_count) if message_count and top_counts else 0
        top3_author_share = (sum(top_counts[:3]) / message_count) if message_count and top_counts else 0

        max_msgs_per_minute = 0
        std_msgs_per_minute = 0.0
        burst_ratio = 0.0
        if timestamps:
            end_dt = max(timestamps)
            start_dt = end_dt - timedelta(minutes=duration_minutes)
            buckets = [0 for _ in range(duration_minutes)]
            for ts in timestamps:
                index = int((ts - start_dt).total_seconds() // 60)
                if 0 <= index < duration_minutes:
                    buckets[index] += 1
            max_msgs_per_minute = max(buckets) if buckets else 0
            if buckets:
                std_msgs_per_minute = statistics.pstdev(buckets)
            if msg_per_min > 0:
                burst_ratio = max_msgs_per_minute / msg_per_min

        return {
            "message_count": message_count,
            "unique_users": unique_users,
            "window_minutes": window_minutes,
            "msg_per_min": round(msg_per_min, 2),
            "caps_ratio": round(caps_ratio, 3),
            "mention_count": mention_count,
            "mention_per_min": round(mention_per_min, 2),
            "reply_density": round(reply_density, 3),
            "hostility_index": round(hostility_index, 3),
            "toxicity_index": round(toxicity_index, 3),
            "aggression_index": round(aggression_index, 3),
            "venting_index": round(venting_index, 3),
            "direct_conflict_index": round(direct_conflict_index, 3),
            "calming_index": round(calming_index, 3),
            "challenge_signals": round(challenge_index, 3),
            "hostile_mentions": round(hostile_mentions_index, 3),
            "playful_index": round(playful_index, 3),
            "affectionate_index": round(affectionate_index, 3),
            "reply_conflict_density": round(reply_conflict_density, 3),
            "profanity_hits": profanity_hits_total,
            "insult_hits": insult_hits_total,
            "blasphemy_hits": blasphemy_hits_total,
            "proportion_of_directed_conflict": round(direct_conflict_index, 3),
            "proportion_of_venting": round(venting_index, 3),
            "proportion_of_deescalation": round(proportion_of_deescalation, 3),
            "reciprocal_conflict_pairs": reciprocal_conflict_pairs,
            "aggressive_directed_count": aggressive_directed,
            "top1_author_share": round(top1_author_share, 3),
            "top3_author_share": round(top3_author_share, 3),
            "max_msgs_per_minute": max_msgs_per_minute,
            "std_msgs_per_minute": round(std_msgs_per_minute, 2),
            "burst_ratio": round(burst_ratio, 2),
            "reply_war": reciprocal_conflict_pairs > 0,
            "message_classifications": classifications,
        }

    def _compute_pair_metrics(
        self,
        messages: list[Any],
        user_a_id: str,
        user_b_id: str,
    ) -> dict[str, Any]:
        msg_count_user_a = 0
        msg_count_user_b = 0
        mentions_a_to_b = 0
        mentions_b_to_a = 0
        total_len_a = 0
        total_len_b = 0

        for message in messages:
            author_id = self._mget(message, "author_id") or ""
            content = (self._mget(message, "content", "") or "").strip()
            mentions_raw = self._mget(message, "mentions_json")
            mentions_list: list[str] = []
            if mentions_raw:
                try:
                    parsed = json.loads(mentions_raw)
                    if isinstance(parsed, list):
                        mentions_list = [str(item) for item in parsed]
                except json.JSONDecodeError:
                    mentions_list = []

            if author_id == user_a_id:
                msg_count_user_a += 1
                total_len_a += len(content)
                if mentions_list:
                    mentions_a_to_b += mentions_list.count(user_b_id)
                else:
                    mentions_a_to_b += content.count(f"<@{user_b_id}>")
            elif author_id == user_b_id:
                msg_count_user_b += 1
                total_len_b += len(content)
                if mentions_list:
                    mentions_b_to_a += mentions_list.count(user_a_id)
                else:
                    mentions_b_to_a += content.count(f"<@{user_a_id}>")

        max_msgs = max(msg_count_user_a, msg_count_user_b)
        min_msgs = min(msg_count_user_a, msg_count_user_b)
        balance_ratio = round((min_msgs / max_msgs), 3) if max_msgs else 0.0

        avg_msg_len_a = round(total_len_a / msg_count_user_a, 1) if msg_count_user_a else 0.0
        avg_msg_len_b = round(total_len_b / msg_count_user_b, 1) if msg_count_user_b else 0.0

        return {
            "msg_count_user_a": msg_count_user_a,
            "msg_count_user_b": msg_count_user_b,
            "balance_ratio": balance_ratio,
            "mentions_a_to_b": mentions_a_to_b,
            "mentions_b_to_a": mentions_b_to_a,
            "avg_msg_len_a": avg_msg_len_a,
            "avg_msg_len_b": avg_msg_len_b,
        }

    def _score_from_metrics(self, metrics: dict[str, Any], score_config: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        del score_config
        penalties: list[dict[str, Any]] = []
        msg_per_min = float(metrics.get("msg_per_min") or 0.0)
        burst_ratio = float(metrics.get("burst_ratio") or 0.0)
        top1_author_share = float(metrics.get("top1_author_share") or 0.0)
        top3_author_share = float(metrics.get("top3_author_share") or 0.0)
        hostility_index = float(metrics.get("hostility_index") or 0.0)
        toxicity_index = float(metrics.get("toxicity_index") or 0.0)
        aggression_index = float(metrics.get("aggression_index") or 0.0)
        direct_conflict_index = float(metrics.get("direct_conflict_index") or 0.0)
        venting_index = float(metrics.get("venting_index") or 0.0)
        calming_index = float(metrics.get("calming_index") or 0.0)
        reply_density = float(metrics.get("reply_density") or 0.0)
        reply_conflict_density = float(metrics.get("reply_conflict_density") or 0.0)
        hostile_mentions = float(metrics.get("hostile_mentions") or 0.0)
        challenge_signals = float(metrics.get("challenge_signals") or 0.0)
        playful_index = float(metrics.get("playful_index") or 0.0)
        affectionate_index = float(metrics.get("affectionate_index") or 0.0)
        caps_ratio = float(metrics.get("caps_ratio") or 0.0)
        aggressive_directed_count = int(metrics.get("aggressive_directed_count") or 0)
        reciprocal_conflict_pairs = int(metrics.get("reciprocal_conflict_pairs") or 0)
        persistence_conflict = float(metrics.get("persistence_of_conflict_vs_previous_window") or 0.0)

        intensity_index = min(
            1.0,
            (0.34 * min(msg_per_min / 10.0, 1.0))
            + (0.18 * min(burst_ratio / 3.5, 1.0))
            + (0.18 * min(reply_density / 0.75, 1.0))
            + (0.15 * min(top1_author_share / 0.75, 1.0))
            + (0.15 * min(top3_author_share / 0.95, 1.0)),
        )
        challenge_pressure = challenge_signals * min(
            1.0,
            (0.35 + (0.75 * direct_conflict_index) + (0.45 * hostile_mentions) + (0.35 * aggression_index)),
        )
        hostility_core = min(
            1.0,
            (0.30 * hostility_index)
            + (0.22 * toxicity_index)
            + (0.18 * aggression_index)
            + (0.18 * direct_conflict_index)
            + (0.05 * challenge_pressure)
            + (0.05 * hostile_mentions),
        )

        hostility_core_penalty = int(round(42 * hostility_core))
        if hostility_core_penalty > 0:
            penalties.append({"key": "hostility_core", "label": "Ostilità conversazionale", "weight": hostility_core_penalty, "summary": f"indice {hostility_core:.2f}"})

        target_confidence = min(
            1.0,
            (0.62 * direct_conflict_index) + (0.33 * hostile_mentions) + (0.08 * min(aggressive_directed_count / 4.0, 1.0)),
        )
        directed_conflict_penalty = int(
            round((62 * direct_conflict_index * max(0.35, target_confidence)) + (22 * hostile_mentions) + (5 * aggressive_directed_count))
        )
        directed_conflict_penalty = min(78, directed_conflict_penalty)
        if directed_conflict_penalty > 0:
            penalties.append({"key": "directed_conflict_penalty", "label": "Attacco diretto / dissing", "weight": directed_conflict_penalty, "summary": f"indice {direct_conflict_index:.2f}"})

        escalation_penalty = int(
            round(
                (18 * min(reciprocal_conflict_pairs, 3))
                + (26 * reply_conflict_density * max(0.35, target_confidence))
                + (10 * max(0.0, persistence_conflict))
            )
        )
        escalation_penalty = min(46, escalation_penalty)
        if escalation_penalty > 0:
            penalties.append({"key": "escalation_penalty", "label": "Escalation reale", "weight": escalation_penalty, "summary": f"coppie {reciprocal_conflict_pairs}"})

        venting_penalty = int(round(10 * venting_index * max(0.25, 1.0 - (direct_conflict_index * 1.35))))
        venting_penalty = min(12, venting_penalty)
        if venting_penalty > 0:
            penalties.append({"key": "venting_penalty", "label": "Sfogo personale", "weight": venting_penalty, "summary": f"indice {venting_index:.2f}"})

        hostility_gate = min(1.0, (0.52 * hostility_core) + (0.48 * direct_conflict_index))
        density_modifier = int(round(14 * intensity_index * hostility_gate * max(0.2, target_confidence)))
        density_modifier = min(18, density_modifier)
        if density_modifier > 0:
            penalties.append({"key": "density_modifier", "label": "Intensità amplifica tensione", "weight": density_modifier, "summary": f"intensità {intensity_index:.2f}"})

        playful_signal = min(1.0, (0.78 * playful_index) + (0.45 * affectionate_index))
        playful_mitigation = int(
            round(24 * intensity_index * playful_signal * max(0.0, 1.0 - (hostility_gate * 1.5)) * max(0.0, 1.0 - (direct_conflict_index * 2.2)))
        )
        if playful_mitigation > 0 and msg_per_min >= 2.0 and direct_conflict_index < 0.24:
            penalties.append({"key": "playful_mitigation", "label": "Chat attiva ma serena", "weight": -playful_mitigation, "summary": f"{msg_per_min:.1f} msg/min"})

        deescalation_bonus = int(round(26 * calming_index * max(0.55, 1.0 - direct_conflict_index)))
        deescalation_bonus = min(24, deescalation_bonus)
        if deescalation_bonus > 0:
            penalties.append({"key": "deescalation_bonus", "label": "Segnali di de-escalation", "weight": -deescalation_bonus, "summary": f"indice {calming_index:.2f}"})

        if caps_ratio > 0.45 and hostility_gate > 0.35:
            penalties.append({"key": "heated_style", "label": "Linguaggio acceso", "weight": int(round(9 * min(caps_ratio, 1.0))), "summary": f"caps {caps_ratio:.2f}"})
        if msg_per_min < 0.12 and hostility_core < 0.08:
            penalties.append({"key": "empty_chat_flatness", "label": "Calma apparente (chat vuota)", "weight": 4, "summary": "attività molto bassa"})

        penalties.sort(key=lambda item: abs(int(item["weight"])), reverse=True)
        total_penalty = sum(int(item["weight"]) for item in penalties)
        score = self._clamp_score(100 - total_penalty)
        return penalties, score

    def _parse_mentions(self, message: Any, content: str) -> list[str]:
        mentions_raw = self._mget(message, "mentions_json")
        if mentions_raw:
            try:
                parsed = json.loads(mentions_raw)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                logger.debug("Invalid mentions JSON in message payload")
        return re.findall(r"<@!?(\d+)>", content)

    def _classify_message(self, *, content: str, author_id: str, mentions: list[str], reply_to_id: str) -> dict[str, Any]:
        text = self._normalize_text(content)
        profanity_hits = self._count_keyword_hits(text, PROFANITY_KEYWORDS)
        insult_hits = self._count_keyword_hits(text, INSULT_KEYWORDS)
        blasphemy_hits = sum(1 for pattern in BLASPHEMY_PATTERNS if re.search(pattern, text))
        challenge_hits = sum(1 for pattern in CHALLENGE_PATTERNS if re.search(pattern, text))
        aggressive_hits = sum(1 for pattern in AGGRESSIVE_PATTERNS if re.search(pattern, text))
        negative_hits = self._count_keyword_hits(text, NEGATIVE_KEYWORDS)
        calming_hits = sum(text.count(word) for word in CALMING_KEYWORDS)
        venting_hits = sum(1 for pattern in VENTING_PATTERNS if re.search(pattern, text))
        second_person_hits = sum(1 for pattern in SECOND_PERSON_PATTERNS if re.search(pattern, text))
        playful_hits = sum(1 for marker in PLAYFUL_MARKERS if marker in text)
        affectionate_hits = sum(1 for marker in AFFECTIONATE_MARKERS if marker in text)
        repeated_punctuation = content.count("!!") + content.count("??")
        caps_ratio = self._caps_ratio(content)
        has_direct_target = bool(mentions or reply_to_id or second_person_hits > 0)
        has_hard_target = bool(mentions or reply_to_id)
        target_type = "none"
        primary_target_id = ""
        if mentions:
            target_type = "user"
            primary_target_id = mentions[0]
        elif reply_to_id:
            target_type = "user"
            primary_target_id = reply_to_id
        elif second_person_hits > 0:
            target_type = "generic"
        if "ragazzi" in text or "raga" in text or "voi" in text:
            target_type = "group"

        directed_language_pressure = min(
            1.0,
            (0.45 if has_hard_target else 0.0)
            + (0.14 if second_person_hits > 0 and (insult_hits > 0 or profanity_hits > 0 or aggressive_hits > 0) else 0.0)
            + (0.08 if challenge_hits > 0 and (insult_hits > 0 or profanity_hits > 0 or aggressive_hits > 0) else 0.0),
        )
        target_confidence = min(
            1.0,
            (0.6 if has_hard_target else 0.0)
            + (0.1 if second_person_hits > 0 else 0.0)
            + (0.08 if challenge_hits > 0 else 0.0),
        )
        playful_confidence = min(1.0, (0.25 * playful_hits) + (0.2 * affectionate_hits))
        direct_conflict_confidence = min(
            1.0,
            (0.45 * target_confidence)
            + (0.28 if insult_hits > 0 else 0.0)
            + (0.16 if has_hard_target and (profanity_hits > 0 or blasphemy_hits > 0) else 0.0)
            + (0.08 if aggressive_hits > 0 and has_hard_target else 0.0)
            + (0.08 if challenge_hits > 0 and (insult_hits > 0 or profanity_hits > 0) else 0.0)
            - (0.22 if playful_confidence > 0.3 and insult_hits <= 1 else 0.0),
        )

        toxicity_base = (
            0.07 * profanity_hits
            + 0.27 * insult_hits
            + 0.11 * blasphemy_hits
            + 0.08 * negative_hits
        )
        directed_toxic_boost = (
            (0.16 if profanity_hits > 0 and second_person_hits > 0 else 0.0)
            + (0.18 if profanity_hits > 0 and has_hard_target else 0.0)
            + (0.2 if insult_hits > 0 and has_hard_target else 0.0)
            + (0.1 if blasphemy_hits > 0 and has_hard_target else 0.0)
        )
        playful_softener = (0.13 if playful_hits > 0 and not has_hard_target else 0.0) + (
            0.08 if affectionate_hits > 0 and insult_hits == 0 else 0.0
        )
        toxicity_score = min(1.0, max(0.0, toxicity_base + directed_toxic_boost - playful_softener))
        aggression_score = min(
            1.0,
            (0.62 * toxicity_score)
            + (0.26 if repeated_punctuation else 0.0)
            + (0.22 if caps_ratio > 0.35 else 0.0)
            + (0.14 * aggressive_hits)
            + (0.06 * challenge_hits)
            + (0.22 * directed_language_pressure),
        )
        directedness_score = min(1.0, directed_language_pressure + (0.1 if target_type == "group" else 0.0))
        profanity_score = min(1.0, 0.2 * profanity_hits + 0.4 * blasphemy_hits)
        venting_score = min(1.0, 0.5 * venting_hits + (0.15 if "io" in text and not has_direct_target else 0.0))
        calming_score = min(1.0, 0.45 * calming_hits)
        conflict_score = min(
            1.0,
            (aggression_score * 0.38)
            + (directedness_score * 0.38)
            + (toxicity_score * 0.24),
        )
        hostile_mentions = 1 if has_hard_target and (insult_hits > 0 or profanity_hits > 0 or aggressive_hits > 0) else 0

        label = "neutral"
        if calming_score >= 0.35:
            label = "deescalation"
        elif direct_conflict_confidence >= 0.58 and directedness_score >= 0.5 and (
            insult_hits > 0
            or (profanity_hits > 0 and second_person_hits > 0)
            or (profanity_hits > 0 and has_hard_target)
            or (challenge_hits > 0 and (insult_hits > 0 or aggressive_hits > 0))
        ):
            label = "directed_conflict"
        elif conflict_score >= 0.55 and direct_conflict_confidence >= 0.52 and directedness_score >= 0.5 and (
            aggression_score >= 0.35 or insult_hits > 0 or (profanity_hits > 0 and has_hard_target)
        ):
            label = "directed_conflict"
        elif blasphemy_hits > 0 and not has_direct_target:
            label = "venting"
        elif venting_score >= 0.4 and directedness_score < 0.4:
            label = "venting"
        elif aggression_score >= 0.4 and directedness_score < 0.5:
            label = "heated_non_conflict"
        elif "grazie" in text or "brav" in text:
            label = "positive"

        result = {
            "author_id": author_id,
            "target_type": target_type,
            "primary_target_id": primary_target_id,
            "toxicity_score": round(toxicity_score, 3),
            "aggression_score": round(aggression_score, 3),
            "directedness_score": round(directedness_score, 3),
            "profanity_score": round(profanity_score, 3),
            "venting_score": round(venting_score, 3),
            "calming_score": round(calming_score, 3),
            "conflict_score": round(conflict_score, 3),
            "negative_hits": int(negative_hits),
            "profanity_hits": int(profanity_hits),
            "insult_hits": int(insult_hits),
            "blasphemy_hits": int(blasphemy_hits),
            "challenge_hits": int(challenge_hits),
            "hostile_mention": int(hostile_mentions),
            "playful_hits": int(playful_hits),
            "affectionate_hits": int(affectionate_hits),
            "target_confidence": round(target_confidence, 3),
            "direct_conflict_confidence": round(direct_conflict_confidence, 3),
            "classification_label": label,
        }
        return self._maybe_ai_fallback(result, content)

    @staticmethod
    def _normalize_text(content: str) -> str:
        lowered = (content or "").lower()
        normalized = unicodedata.normalize("NFKD", lowered)
        stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", stripped).strip()

    @staticmethod
    def _count_keyword_hits(text: str, keywords: list[str]) -> int:
        hits = 0
        for token in keywords:
            if len(token) <= 3:
                hits += len(re.findall(rf"\b{re.escape(token)}\b", text))
                continue
            if token.endswith(("at", "it", "zz", "rd", "stronz", "merd", "incazzat")):
                if token in text:
                    hits += 1
                continue
            hits += len(re.findall(rf"\b{re.escape(token)}\w*\b", text))
        return hits

    def _maybe_ai_fallback(self, classification: dict[str, Any], content: str) -> dict[str, Any]:
        del content
        conflict_score = float(classification.get("conflict_score") or 0.0)
        venting_score = float(classification.get("venting_score") or 0.0)
        if 0.35 <= conflict_score <= 0.55 and 0.25 <= venting_score <= 0.55:
            classification["ai_fallback_candidate"] = True
        else:
            classification["ai_fallback_candidate"] = False
        return classification

    @staticmethod
    def _caps_ratio(content: str) -> float:
        total_letters = sum(1 for ch in content if ch.isalpha())
        if total_letters == 0:
            return 0.0
        uppercase_letters = sum(1 for ch in content if ch.isalpha() and ch.isupper())
        return uppercase_letters / total_letters

    @staticmethod
    def _count_reciprocal_pairs(directed_pairs: dict[tuple[str, str], int]) -> int:
        count = 0
        seen: set[tuple[str, str]] = set()
        for pair, value in directed_pairs.items():
            reverse = (pair[1], pair[0])
            if pair in seen or reverse in seen:
                continue
            if value >= 1 and directed_pairs.get(reverse, 0) >= 1:
                count += 1
                seen.add(pair)
                seen.add(reverse)
        return count

    @staticmethod
    def _main_reason_key(reasons: list[dict[str, Any]]) -> str | None:
        if not reasons:
            return None
        return str(reasons[0].get("key") or "")

    @staticmethod
    def _extract_dominant_driver(reasons: list[dict[str, Any]]) -> str:
        if not reasons:
            return ""
        return str(reasons[0].get("key") or "")

    @staticmethod
    def _choose_recovery_type(
        *,
        direction: str,
        current_metrics: dict[str, Any],
        previous_metrics: dict[str, Any],
    ) -> str:
        if direction != "improving":
            return ""
        msg_current = int(current_metrics.get("message_count") or 0)
        msg_prev = int(previous_metrics.get("message_count") or 0)
        if msg_current <= max(2, int(msg_prev * 0.6)):
            return "passive_recovery"
        return "active_recovery"

    @staticmethod
    def _choose_dominant_driver(
        *,
        current_metrics: dict[str, Any],
        previous_metrics: dict[str, Any],
        direction: str,
        current_color: str,
    ) -> str:
        direct = float(current_metrics.get("direct_conflict_index") or 0.0)
        venting = float(current_metrics.get("venting_index") or 0.0)
        calming = float(current_metrics.get("calming_index") or 0.0)
        hostility = float(current_metrics.get("hostility_index") or 0.0)
        intensity = float(current_metrics.get("intensity_index") or 0.0)
        playful = float(current_metrics.get("playful_index") or 0.0)
        affectionate = float(current_metrics.get("affectionate_index") or 0.0)
        persistence = float(current_metrics.get("persistence_of_conflict_vs_previous_window") or 0.0)
        msg_current = int(current_metrics.get("message_count") or 0)
        msg_prev = int(previous_metrics.get("message_count") or 0)

        if current_color == "nero" and (direct >= 0.42 or persistence > 0.1):
            return "escalation"
        if direct >= 0.3:
            return "directed_conflict"
        if direction == "improving" and calming >= 0.12 and direct < 0.24:
            return "deescalation"
        if direction == "improving":
            if msg_current <= max(2, int(msg_prev * 0.6)):
                return "passive_recovery"
            return "active_recovery"
        if direction == "worsening" and (hostility >= 0.22 or persistence > 0.04):
            return "rising_tension"
        if venting >= 0.18 and direct < 0.26:
            return "venting"
        if (playful + affectionate) >= 0.18 and intensity >= 0.35 and direct < 0.2 and hostility < 0.2:
            return "playful_activity"
        return "stable_balance"

    def _build_advice(self, metrics: dict[str, Any], score: int) -> list[str]:
        advice: list[str] = []
        if score < 40 and metrics["msg_per_min"] > 5:
            advice.append("Rallentare il ritmo e evitare botta e risposta.")
        if metrics["mention_per_min"] > 1:
            advice.append("Evitare callout e menzioni a caldo.")
        if metrics.get("direct_conflict_index", 0) > 0.15:
            advice.append("Abbassare i toni e chiarire in privato se necessario.")
        elif metrics.get("venting_index", 0) > 0.2:
            advice.append("Valorizzare ascolto e de-escalation senza personalizzare i toni.")
        return advice[:3]

    @staticmethod
    def _parse_ts(raw: Optional[str]) -> datetime:
        if not raw:
            return datetime.now(timezone.utc)
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _detect_reply_war(self, authors: list[str], timestamps: list[datetime]) -> bool:
        if len(authors) < 10:
            return False
        counts: dict[str, int] = {}
        for author in authors:
            counts[author] = counts.get(author, 0) + 1
        top_authors = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:3]
        if len(top_authors) < 2:
            return False
        total = len(authors)
        top_ratio = sum(count for _, count in top_authors[:2]) / total
        if top_ratio < 0.7:
            return False
        close_bursts = 0
        for idx in range(1, len(authors)):
            if authors[idx] in {top_authors[0][0], top_authors[1][0]}:
                delta = (timestamps[idx] - timestamps[idx - 1]).total_seconds()
                if delta <= 90:
                    close_bursts += 1
        return close_bursts >= 5
