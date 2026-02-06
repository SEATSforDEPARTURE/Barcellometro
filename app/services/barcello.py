from __future__ import annotations

import json
import logging
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
        reasons, score = self._score_from_metrics(metrics)
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

        for message in messages:
            content = (self._mget(message, "content", "") or "").strip()
            total_letters += sum(1 for ch in content if ch.isalpha())
            uppercase_letters += sum(1 for ch in content if ch.isalpha() and ch.isupper())
            content_lower = content.lower()
            negativity_hits += sum(content_lower.count(keyword) for keyword in NEGATIVE_KEYWORDS)

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

        return {
            "message_count": message_count,
            "window_minutes": window_minutes,
            "msg_per_min": round(msg_per_min, 2),
            "caps_ratio": round(caps_ratio, 3),
            "negativity_hits": negativity_hits,
            "mention_count": mention_count,
            "mention_per_min": round(mention_per_min, 2),
            "reply_war": reply_war,
        }

    def _score_from_metrics(self, metrics: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        penalties: list[dict[str, Any]] = []
        msg_per_min = metrics["msg_per_min"]
        caps_ratio = metrics["caps_ratio"]
        negativity_hits = metrics["negativity_hits"]
        mention_per_min = metrics["mention_per_min"]
        reply_war = metrics["reply_war"]

        msg_penalty = min(max(msg_per_min - 5, 0) * 2, 30)
        if msg_penalty:
            penalties.append(
                {
                    "key": "density",
                    "label": "Alta densità messaggi",
                    "weight": int(msg_penalty),
                    "summary": f"{msg_per_min} msg/min",
                }
            )

        caps_penalty = min(max(caps_ratio - 0.3, 0) * 50, 20)
        if caps_penalty:
            penalties.append(
                {
                    "key": "caps",
                    "label": "Uso eccessivo di MAIUSCOLE",
                    "weight": int(round(caps_penalty)),
                    "summary": f"caps ratio {caps_ratio}",
                }
            )

        negativity_penalty = min(negativity_hits * 5, 25)
        if negativity_penalty:
            penalties.append(
                {
                    "key": "negativity",
                    "label": "Toni negativi",
                    "weight": int(negativity_penalty),
                    "summary": f"{negativity_hits} hit",
                }
            )

        mention_penalty = min(max(mention_per_min - 1, 0) * 5, 20)
        if mention_penalty:
            penalties.append(
                {
                    "key": "mentions",
                    "label": "Molte menzioni",
                    "weight": int(round(mention_penalty)),
                    "summary": f"{mention_per_min} mention/min",
                }
            )

        reply_war_penalty = 15 if reply_war else 0
        if reply_war_penalty:
            penalties.append(
                {
                    "key": "reply_war",
                    "label": "Botta e risposta acceso",
                    "weight": reply_war_penalty,
                    "summary": "concentrato tra pochi utenti",
                }
            )

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
