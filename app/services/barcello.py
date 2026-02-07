from __future__ import annotations

import json
import logging
import re
import statistics
from dataclasses import dataclass
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
    window_start_ts: str
    window_end_ts: str
    reasons: list[dict[str, Any]]
    metrics: dict[str, Any]
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
        score_config = await self._get_score_config()
        reasons, score = self._score_from_metrics(metrics, score_config)
        color = await self.get_color(score)

        trend = await self._compute_trend(guild_id, channel_id, window_minutes, window_end_ts, score)
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
        self._metrics["last_compute_ts"] = computed_ts
        last_scores = self._metrics["last_score_by_channel"]
        last_scores_key = f"{guild_id}:{channel_id}"
        last_scores[last_scores_key] = score
        if len(last_scores) > 20:
            last_scores.pop(next(iter(last_scores)))

        self._cache_result(cache_key, result)
        return result

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
        return self._build_trend(score, prev_score)

    @staticmethod
    def _build_trend(score: int, prev_score: int) -> dict[str, Any]:
        delta = score - prev_score
        if abs(delta) < 5:
            direction = "stable"
        elif delta > 0:
            direction = "improving"
        else:
            direction = "worsening"
        return {"direction": direction, "delta": delta}

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
        total_letters = 0
        uppercase_letters = 0
        negativity_hits = 0
        mention_count = 0
        authors: list[str] = []
        timestamps: list[datetime] = []
        contrast_hits = 0
        challenge_hits = 0
        playful_hits = 0
        passive_aggressive_hits = 0
        sarcasm_marker_hits = 0

        contrast_patterns = [
            r"\bma\b",
            r"\bper[òo]\b",
            r"\bcomunque\b",
            r"\bno\b",
            r"in realt[àa]",
        ]
        contrast_regex = re.compile("|".join(contrast_patterns))
        challenge_regex = re.compile(r"\b(perch[eéè]|perché)\b")
        playful_emojis = ["😂", "🤣", "😅", "😆", "😊", "😜", "😝", "😹", "😸", "😺", "😻", "🤪", "😉"]
        passive_aggressive_emojis = ["🙃", "😒", "😤", "😏", "😑", "😐", "🙄", "😬", "😶‍🌫️"]
        sarcasm_markers = ["/s", "ironia", "sarcasmo", "scherzo", "scherzavo"]

        for message in messages:
            content = (self._mget(message, "content", "") or "").strip()
            total_letters += sum(1 for ch in content if ch.isalpha())
            uppercase_letters += sum(1 for ch in content if ch.isalpha() and ch.isupper())
            content_lower = content.lower()
            negativity_hits += sum(content_lower.count(keyword) for keyword in NEGATIVE_KEYWORDS)
            contrast_hits += len(contrast_regex.findall(content_lower))
            if "?" in content_lower:
                if "??" in content_lower:
                    challenge_hits += content_lower.count("??")
                if "tu" in content_lower:
                    challenge_hits += 1
                if challenge_regex.search(content_lower):
                    challenge_hits += 1
            sarcasm_marker_hits += sum(content_lower.count(marker) for marker in sarcasm_markers)
            playful_hits += sum(content.count(emoji) for emoji in playful_emojis)
            passive_aggressive_hits += sum(content.count(emoji) for emoji in passive_aggressive_emojis)

            mentions_raw = self._mget(message, "mentions_json")
            if mentions_raw:
                try:
                    mentions = json.loads(mentions_raw)
                    if isinstance(mentions, list):
                        mention_count += len(mentions)
                except json.JSONDecodeError:
                    logger.debug("Invalid mentions JSON in message payload")
                    mention_count += content.count("<@")
            else:
                mention_count += content.count("<@")

            authors.append(self._mget(message, "author_id") or "unknown")
            timestamps.append(self._parse_ts(self._mget(message, "ts")))

        duration_minutes = max(window_minutes, 1)
        msg_per_min = message_count / duration_minutes if duration_minutes else 0
        caps_ratio = (uppercase_letters / total_letters) if total_letters else 0
        mention_per_min = mention_count / duration_minutes if duration_minutes else 0

        reply_war = self._detect_reply_war(authors, timestamps)
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
            mean_msgs = msg_per_min
            if buckets:
                std_msgs_per_minute = statistics.pstdev(buckets)
            if mean_msgs > 0:
                burst_ratio = max_msgs_per_minute / mean_msgs

        contrast_per_msg = contrast_hits / message_count if message_count else 0
        challenge_per_msg = challenge_hits / message_count if message_count else 0
        playful_emoji_ratio = playful_hits / message_count if message_count else 0
        passive_aggressive_emoji_ratio = passive_aggressive_hits / message_count if message_count else 0
        sarcasm_marker_hits_per_msg = sarcasm_marker_hits / message_count if message_count else 0

        return {
            "message_count": message_count,
            "window_minutes": window_minutes,
            "msg_per_min": round(msg_per_min, 2),
            "caps_ratio": round(caps_ratio, 3),
            "negativity_hits": negativity_hits,
            "mention_count": mention_count,
            "mention_per_min": round(mention_per_min, 2),
            "reply_war": reply_war,
            "top1_author_share": round(top1_author_share, 3),
            "top3_author_share": round(top3_author_share, 3),
            "max_msgs_per_minute": max_msgs_per_minute,
            "std_msgs_per_minute": round(std_msgs_per_minute, 2),
            "burst_ratio": round(burst_ratio, 2),
            "contrast_per_msg": round(contrast_per_msg, 3),
            "challenge_per_msg": round(challenge_per_msg, 3),
            "playful_emoji_ratio": round(playful_emoji_ratio, 3),
            "passive_aggressive_emoji_ratio": round(passive_aggressive_emoji_ratio, 3),
            "sarcasm_marker_hits": round(sarcasm_marker_hits_per_msg, 3),
            "sarcasm_marker_hits_raw": sarcasm_marker_hits,
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
        penalties: list[dict[str, Any]] = []
        msg_per_min = metrics["msg_per_min"]
        caps_ratio = metrics["caps_ratio"]
        negativity_hits = metrics["negativity_hits"]
        mention_per_min = metrics["mention_per_min"]
        reply_war = metrics["reply_war"]
        top1_author_share = metrics.get("top1_author_share", 0)
        top3_author_share = metrics.get("top3_author_share", 0)
        burst_ratio = metrics.get("burst_ratio", 0)
        contrast_per_msg = metrics.get("contrast_per_msg", 0)
        challenge_per_msg = metrics.get("challenge_per_msg", 0)
        playful_ratio = metrics.get("playful_emoji_ratio", 0)
        passive_ratio = metrics.get("passive_aggressive_emoji_ratio", 0)
        sarcasm_hits_raw = metrics.get("sarcasm_marker_hits_raw", 0)

        rules = score_config["rules"]
        weights = score_config["weights"]
        mitigation_cfg = score_config["mitigation"]

        msg_cfg = rules["msg_rate"]
        caps_cfg = rules["caps"]
        negativity_cfg = rules["negativity"]
        mention_cfg = rules["mentions"]
        reply_cfg = rules["reply_war"]
        top1_cfg = rules["top1_author_share"]
        top3_cfg = rules["top3_author_share"]
        burst_cfg = rules["burst_ratio"]
        contrast_cfg = rules["contrast_per_msg"]
        challenge_cfg = rules["challenge_per_msg"]

        msg_penalty = min(max(msg_per_min - msg_cfg["threshold"], 0) * msg_cfg["scale"], msg_cfg["cap"])
        msg_penalty *= float(weights.get("msg_rate", 1.0))
        if msg_penalty:
            penalties.append(
                {
                    "key": "density",
                    "label": "Alta densità messaggi",
                    "weight": int(msg_penalty),
                    "summary": f"{msg_per_min} msg/min",
                }
            )

        caps_penalty = min(max(caps_ratio - caps_cfg["threshold"], 0) * caps_cfg["scale"], caps_cfg["cap"])
        caps_penalty *= float(weights.get("caps", 1.0))
        if caps_penalty:
            penalties.append(
                {
                    "key": "caps",
                    "label": "Uso eccessivo di MAIUSCOLE",
                    "weight": int(round(caps_penalty)),
                    "summary": f"caps ratio {caps_ratio}",
                }
            )

        negativity_penalty = min(negativity_hits * negativity_cfg["per_hit"], negativity_cfg["cap"])
        negativity_penalty *= float(weights.get("negativity", 1.0))
        if negativity_penalty:
            penalties.append(
                {
                    "key": "negativity",
                    "label": "Toni negativi",
                    "weight": int(negativity_penalty),
                    "summary": f"{negativity_hits} hit",
                }
            )

        mention_penalty = min(
            max(mention_per_min - mention_cfg["threshold"], 0) * mention_cfg["scale"],
            mention_cfg["cap"],
        )
        mention_penalty *= float(weights.get("mentions", 1.0))
        if mention_penalty:
            penalties.append(
                {
                    "key": "mentions",
                    "label": "Molte menzioni",
                    "weight": int(round(mention_penalty)),
                    "summary": f"{mention_per_min} mention/min",
                }
            )

        reply_war_penalty = reply_cfg["penalty"] if reply_war else 0
        if reply_war_penalty:
            penalties.append(
                {
                    "key": "reply_war",
                    "label": "Botta e risposta acceso",
                    "weight": reply_war_penalty,
                    "summary": "concentrato tra pochi utenti",
                }
            )

        if top1_author_share > top1_cfg["threshold"]:
            top1_weight = float(weights.get("top3", 1.0))
            penalties.append(
                {
                    "key": "top1_author_share",
                    "label": "Concentrazione su un autore",
                    "weight": int(round(top1_cfg["penalty"] * top1_weight)),
                    "summary": f"{top1_author_share:.2f} top1",
                }
            )

        if top3_author_share > top3_cfg["threshold"]:
            top3_weight = float(weights.get("top3", 1.0))
            penalties.append(
                {
                    "key": "top3_author_share",
                    "label": "Concentrazione su pochi autori",
                    "weight": int(round(top3_cfg["penalty"] * top3_weight)),
                    "summary": f"{top3_author_share:.2f} top3",
                }
            )

        if burst_ratio > burst_cfg["threshold"]:
            burst_penalty = burst_cfg["penalty"]
            if burst_ratio > burst_cfg.get("max_threshold", burst_cfg["threshold"]):
                burst_penalty = burst_cfg.get("max_penalty", burst_penalty)
            burst_penalty = int(round(burst_penalty * float(weights.get("burst", 1.0))))
            penalties.append(
                {
                    "key": "burst_ratio",
                    "label": "Burst di messaggi",
                    "weight": burst_penalty,
                    "summary": f"ratio {burst_ratio:.2f}",
                }
            )

        if contrast_per_msg > contrast_cfg["threshold"]:
            contrast_penalty = int(round(contrast_cfg["penalty"] * float(weights.get("contrast", 1.0))))
            penalties.append(
                {
                    "key": "contrast_per_msg",
                    "label": "Frizione lessicale",
                    "weight": contrast_penalty,
                    "summary": f"{contrast_per_msg:.2f} per msg",
                }
            )

        if challenge_per_msg > challenge_cfg["threshold"]:
            challenge_penalty = int(round(challenge_cfg["penalty"] * float(weights.get("challenge", 1.0))))
            penalties.append(
                {
                    "key": "challenge_per_msg",
                    "label": "Domande sfidanti",
                    "weight": challenge_penalty,
                    "summary": f"{challenge_per_msg:.2f} per msg",
                }
            )

        is_playful = (
            (playful_ratio >= 0.65 or sarcasm_hits_raw >= 3)
            and passive_ratio <= 0.35
            and negativity_hits == 0
        )
        if is_playful:
            msg_penalty *= float(mitigation_cfg.get("msg_rate_factor", 0.8))
            caps_penalty *= float(mitigation_cfg.get("caps_factor", 0.7))
            for item in penalties:
                if item["key"] == "density":
                    item["weight"] = int(round(msg_penalty))
                if item["key"] == "caps":
                    item["weight"] = int(round(caps_penalty))

        penalties.sort(key=lambda item: item["weight"], reverse=True)
        total_penalty = sum(item["weight"] for item in penalties)
        score = self._clamp_score(100 - total_penalty)
        return penalties, score

    def _build_advice(self, metrics: dict[str, Any], score: int) -> list[str]:
        advice: list[str] = []
        if score < 40 and metrics["msg_per_min"] > 5:
            advice.append("Rallentare il ritmo e evitare botta e risposta.")
        if metrics["mention_per_min"] > 1:
            advice.append("Evitare callout e menzioni a caldo.")
        if metrics["negativity_hits"] > 0:
            advice.append("Abbassare i toni e chiarire in privato se necessario.")
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
