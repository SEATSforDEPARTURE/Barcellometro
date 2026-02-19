from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.database import DatabaseService

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")


@dataclass
class ActivityScore:
    messages_count: int
    active_users_count: int
    peak_hour_local: int | None
    continuity_hours: int
    score: int
    emoji: str
    label: str
    trend_text: str


@dataclass
class UserActivityEntry:
    user_id: int
    count_in_range: int
    peak_count: int
    peak_hour_ts: str | None
    last_ts_in_range: str | None
    last_message_id_in_range: str | None
    last_ts_channel: str | None = None
    last_message_id_channel: str | None = None


@dataclass
class ChannelActivityDetails:
    score: ActivityScore
    top_active_users: list[UserActivityEntry]
    inactive_users: list[UserActivityEntry]
    advice_bullets: list[str]
    stats_lines: list[str]


class ActivityInsightsService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    @staticmethod
    def _parse_ts(ts: str) -> datetime:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    async def compute_activity_for_channel(
        self,
        guild_id: str,
        channel_id: str,
        start_ts: str,
        end_ts: str,
        *,
        candidate_user_ids: list[int] | None = None,
        inactive_threshold: int = 1,
        lookback_days: int = 90,
        tz: ZoneInfo = ROME_TZ,
    ) -> ChannelActivityDetails:
        messages = await self._database.count_messages_in_range_single_channel(guild_id, channel_id, start_ts, end_ts)
        active_users = await self._database.count_active_users_in_range_single_channel(guild_id, channel_id, start_ts, end_ts)

        per_user_counts = await self._database.fetch_user_counts_in_range_channel(guild_id, channel_id, start_ts, end_ts)
        per_user_last_in_range = await self._database.fetch_user_last_message_in_range_channel(guild_id, channel_id, start_ts, end_ts)
        user_ts_rows = await self._database.fetch_user_timestamps_in_range_channel(guild_id, channel_id, start_ts, end_ts)

        per_user_hourly: dict[int, dict[datetime, int]] = {}
        hourly_channel: dict[int, int] = {}
        for user_id, ts in user_ts_rows:
            dt_local = self._parse_ts(ts).astimezone(tz)
            hour_bucket = dt_local.replace(minute=0, second=0, microsecond=0)
            user_map = per_user_hourly.setdefault(user_id, {})
            user_map[hour_bucket] = user_map.get(hour_bucket, 0) + 1
            hourly_channel[dt_local.hour] = hourly_channel.get(dt_local.hour, 0) + 1

        per_user_peak: dict[int, tuple[int, str | None]] = {}
        for user_id, bucket_map in per_user_hourly.items():
            if not bucket_map:
                per_user_peak[user_id] = (0, None)
                continue
            peak_dt, peak_count = max(bucket_map.items(), key=lambda item: item[1])
            per_user_peak[user_id] = (int(peak_count), peak_dt.astimezone(timezone.utc).isoformat())

        peak_hour = max(hourly_channel.items(), key=lambda item: item[1])[0] if hourly_channel else None
        continuity = len(hourly_channel)

        start_dt = self._parse_ts(start_ts)
        end_dt = self._parse_ts(end_ts)
        duration_hours = max(1, int((end_dt - start_dt).total_seconds() // 3600))
        continuity_ratio = min(1.0, continuity / max(1, min(24, duration_hours)))

        prev_start = start_dt - (end_dt - start_dt)
        prev_messages = await self._database.count_messages_in_range_single_channel(
            guild_id,
            channel_id,
            prev_start.isoformat(),
            start_dt.isoformat(),
        )
        baseline = prev_messages if prev_messages > 0 else max(1, messages)
        normalized_volume = min(1.0, messages / max(1, baseline))
        normalized_users = min(1.0, active_users / max(1, int(active_users * 0.8) or 1))
        score = int(round((normalized_volume * 0.6 + normalized_users * 0.25 + continuity_ratio * 0.15) * 100))
        score = max(0, min(100, score))

        if score <= 20:
            emoji, label = "⚫", "ASSENTE"
        elif score <= 40:
            emoji, label = "🔴", "SCARSA"
        elif score <= 60:
            emoji, label = "🟡", "MEDIOCRE"
        else:
            emoji, label = "🟢", "INTENSA"

        trend = "Trend stabile rispetto alla finestra precedente."
        if prev_messages > 0:
            delta = int(round(((messages - prev_messages) / prev_messages) * 100))
            direction = "in crescita" if delta > 0 else "in calo" if delta < 0 else "stabile"
            trend = f"Messaggi {direction} ({delta:+d}% vs finestra precedente)."

        ordered_active = sorted(per_user_counts.items(), key=lambda item: item[1], reverse=True)
        top_users: list[UserActivityEntry] = []
        for user_id, count in ordered_active:
            peak_count, peak_ts = per_user_peak.get(user_id, (0, None))
            last = per_user_last_in_range.get(user_id)
            top_users.append(
                UserActivityEntry(
                    user_id=user_id,
                    count_in_range=int(count),
                    peak_count=int(peak_count),
                    peak_hour_ts=peak_ts,
                    last_ts_in_range=last[0] if last else None,
                    last_message_id_in_range=last[1] if last else None,
                    last_ts_channel=last[0] if last else None,
                    last_message_id_channel=last[1] if last else None,
                )
            )

        lookback_start = (end_dt - timedelta(days=max(1, lookback_days))).isoformat()
        per_user_last_lookback = await self._database.fetch_user_last_message_in_channel_since(guild_id, channel_id, lookback_start)

        inactive_users: list[UserActivityEntry] = []
        candidate_ids = candidate_user_ids or list(per_user_counts.keys())
        candidate_set = set(candidate_ids)
        excluded_not_candidates = max(0, len([uid for uid in per_user_counts if uid not in candidate_set]))
        for user_id in candidate_ids:
            count_in_range = int(per_user_counts.get(user_id, 0))
            if count_in_range > inactive_threshold:
                continue
            peak_count, peak_ts = per_user_peak.get(user_id, (0, None))
            in_range_last = per_user_last_in_range.get(user_id)
            lookback_last = per_user_last_lookback.get(user_id)
            inactive_users.append(
                UserActivityEntry(
                    user_id=user_id,
                    count_in_range=count_in_range,
                    peak_count=int(peak_count),
                    peak_hour_ts=peak_ts,
                    last_ts_in_range=in_range_last[0] if in_range_last else None,
                    last_message_id_in_range=in_range_last[1] if in_range_last else None,
                    last_ts_channel=lookback_last[0] if lookback_last else None,
                    last_message_id_channel=lookback_last[1] if lookback_last else None,
                )
            )

        # Più critici prima: "mai visto" in cima, poi ultimo messaggio più vecchio
        inactive_users.sort(key=lambda item: (item.last_ts_channel is not None, item.last_ts_channel or ""), reverse=False)

        logger.info(
            "attivita self-check guild=%s channel=%s active_count=%s inactive_count=%s excluded_not_candidates=%s",
            guild_id,
            channel_id,
            len(top_users),
            len(inactive_users),
            excluded_not_candidates,
        )

        advice: list[str] = []
        if active_users <= 2:
            advice.append("Provate a lanciare una domanda aperta per coinvolgere più persone.")
        if continuity_ratio < 0.35:
            advice.append("Concentrate i messaggi in fasce orarie condivise per aumentare continuità.")
        if messages == 0:
            advice.append("Nessun messaggio nel periodo: utile programmare un prompt leggero di riattivazione.")
        if not advice:
            advice.append("Buon ritmo: mantenete il tono attuale e valorizzate i contributi utili.")

        stats = [
            f"• Messaggi: **{messages}**",
            f"• Utenti attivi: **{active_users}**",
            f"• Ora di picco: **{peak_hour:02d}:00**" if peak_hour is not None else "• Ora di picco: **n/d**",
            f"• Continuità oraria: **{continuity}** ore con attività",
        ]

        return ChannelActivityDetails(
            score=ActivityScore(
                messages_count=messages,
                active_users_count=active_users,
                peak_hour_local=peak_hour,
                continuity_hours=continuity,
                score=score,
                emoji=emoji,
                label=label,
                trend_text=trend,
            ),
            top_active_users=top_users,
            inactive_users=inactive_users,
            advice_bullets=advice,
            stats_lines=stats,
        )
