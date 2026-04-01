from __future__ import annotations

import json
import logging
import re
import statistics
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
    "stupido",
    "idiota",
    "scemo",
    "cretino",
    "merda",
    "schifo",
    "odio",
    "basta",
    "muted",
    "tossico",
]

PROFANITY_KEYWORDS = [
    "cazzo",
    "merda",
    "stronzo",
    "vaffanculo",
    "porca",
    "minchia",
    "fanculo",
]

INSULT_KEYWORDS = [
    "ridicolo",
    "idiota",
    "stupido",
    "scemo",
    "patetico",
    "fallito",
    "imbecille",
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

        trend = await self._compute_trend(guild_id, channel_id, window_minutes, window_end_ts, score)
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
        dominant_driver = self._extract_dominant_driver(json.loads(previous["reasons_json"]))
        return self._build_trend(score, prev_score, dominant_driver=dominant_driver)

    @staticmethod
    def _build_trend(score: int, prev_score: int, *, dominant_driver: str = "") -> dict[str, Any]:
        delta = score - prev_score
        if abs(delta) < 5:
            direction = "stable"
        elif delta > 0:
            direction = "improving"
        else:
            direction = "worsening"
        return {"direction": direction, "delta": delta, "dominant_driver": dominant_driver}

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
            if classification["classification_label"] == "directed_conflict":
                directed_conflict_count += 1
            if classification["classification_label"] == "venting":
                venting_count += 1
            if classification["classification_label"] == "deescalation":
                deescalation_count += 1
            if float(classification["aggression_score"]) > 0.55 and float(classification["directedness_score"]) > 0.6:
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
        venting_index = (venting_count / message_count) if message_count else 0.0
        direct_conflict_index = (directed_conflict_count / message_count) if message_count else 0.0
        calming_index = (calming_sum / message_count) if message_count else 0.0
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
            "venting_index": round(venting_index, 3),
            "direct_conflict_index": round(direct_conflict_index, 3),
            "calming_index": round(calming_index, 3),
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
        hostility_index = float(metrics.get("hostility_index") or 0.0)
        direct_conflict_index = float(metrics.get("direct_conflict_index") or 0.0)
        venting_index = float(metrics.get("venting_index") or 0.0)
        calming_index = float(metrics.get("calming_index") or 0.0)
        reply_density = float(metrics.get("reply_density") or 0.0)
        caps_ratio = float(metrics.get("caps_ratio") or 0.0)
        aggressive_directed_count = int(metrics.get("aggressive_directed_count") or 0)
        reciprocal_conflict_pairs = int(metrics.get("reciprocal_conflict_pairs") or 0)

        if direct_conflict_index > 0:
            penalties.append({"key": "directed_conflict", "label": "Attacchi diretti", "weight": int(round(42 * direct_conflict_index + 6 * aggressive_directed_count)), "summary": f"indice {direct_conflict_index:.2f}"})
        if reciprocal_conflict_pairs > 0:
            penalties.append({"key": "reciprocal_conflict", "label": "Conflitto reciproco multiutente", "weight": min(24, 12 * reciprocal_conflict_pairs), "summary": f"{reciprocal_conflict_pairs} coppie"})
        if hostility_index > 0.22:
            penalties.append({"key": "hostility", "label": "Ostilità diffusa", "weight": int(round(28 * hostility_index)), "summary": f"indice {hostility_index:.2f}"})
        if caps_ratio > 0.45 and hostility_index > 0.2:
            penalties.append({"key": "heated_style", "label": "Linguaggio acceso", "weight": int(round(12 * min(caps_ratio, 1.0))), "summary": f"caps {caps_ratio:.2f}"})
        if msg_per_min > 5 and (hostility_index > 0.2 or direct_conflict_index > 0.15 or reply_density > 0.55):
            penalties.append({"key": "hostile_spike", "label": "Picco attività con ostilità", "weight": int(round(10 + (msg_per_min - 5))), "summary": f"{msg_per_min:.1f} msg/min"})
        if venting_index > 0:
            penalties.append({"key": "venting", "label": "Sfogo personale diffuso", "weight": int(round(8 * venting_index)), "summary": f"indice {venting_index:.2f}"})
        if calming_index > 0:
            penalties.append({"key": "deescalation_bonus", "label": "Segnali calmanti", "weight": -int(round(18 * calming_index)), "summary": f"indice {calming_index:.2f}"})
        if msg_per_min > 3 and hostility_index < 0.1 and direct_conflict_index == 0:
            penalties.append({"key": "healthy_activity_bonus", "label": "Chat attiva ed equilibrata", "weight": -8, "summary": f"{msg_per_min:.1f} msg/min"})

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
        text = content.lower()
        profanity_hits = sum(text.count(word) for word in PROFANITY_KEYWORDS)
        insult_hits = sum(text.count(word) for word in INSULT_KEYWORDS)
        calming_hits = sum(text.count(word) for word in CALMING_KEYWORDS)
        venting_hits = sum(1 for pattern in VENTING_PATTERNS if re.search(pattern, text))
        second_person_hits = sum(1 for pattern in SECOND_PERSON_PATTERNS if re.search(pattern, text))
        repeated_punctuation = content.count("!!") + content.count("??")
        caps_ratio = self._caps_ratio(content)
        has_direct_target = bool(mentions or reply_to_id or second_person_hits > 0)
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

        toxicity_score = min(1.0, 0.22 * profanity_hits + 0.3 * insult_hits)
        aggression_score = min(1.0, toxicity_score + (0.3 if repeated_punctuation else 0.0) + (0.25 if caps_ratio > 0.35 else 0.0))
        directedness_score = min(1.0, (0.55 if has_direct_target else 0.0) + (0.2 if second_person_hits else 0.0))
        profanity_score = min(1.0, 0.28 * profanity_hits)
        venting_score = min(1.0, 0.5 * venting_hits + (0.15 if "io" in text and not has_direct_target else 0.0))
        calming_score = min(1.0, 0.45 * calming_hits)
        conflict_score = min(1.0, (aggression_score * 0.6) + (directedness_score * 0.4))

        label = "neutral"
        if calming_score >= 0.35:
            label = "deescalation"
        elif conflict_score >= 0.45 and directedness_score >= 0.6 and (aggression_score >= 0.3 or insult_hits > 0 or profanity_hits > 0):
            label = "directed_conflict"
        elif aggression_score >= 0.35 and directedness_score < 0.45:
            label = "heated_non_conflict"
        elif venting_score >= 0.4 and directedness_score < 0.4:
            label = "venting"
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
            "classification_label": label,
        }
        return self._maybe_ai_fallback(result, content)

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
