from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services.database import DatabaseService
from app.services.inactivity import InactivityEntry, InactivityService

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
class ChannelActivityDetails:
    score: ActivityScore
    top_active_users: list[tuple[int, int]]
    inactive_users: list[InactivityEntry]
    advice_bullets: list[str]
    stats_lines: list[str]


class ActivityInsightsService:
    def __init__(self, database: DatabaseService, inactivity_service: InactivityService) -> None:
        self._database = database
        self._inactivity = inactivity_service

    async def compute_activity_for_channel(
        self,
        guild_id: str,
        channel_id: str,
        start_ts: str,
        end_ts: str,
        tz: ZoneInfo = ROME_TZ,
    ) -> ChannelActivityDetails:
        messages = await self._database.count_messages_in_range_single_channel(guild_id, channel_id, start_ts, end_ts)
        active_users = await self._database.count_active_users_in_range_single_channel(guild_id, channel_id, start_ts, end_ts)
        top_users = await self._database.top_authors_in_channel_range(guild_id, channel_id, start_ts, end_ts, limit=8)
        timestamps = await self._database.fetch_message_timestamps_in_range_single_channel(guild_id, channel_id, start_ts, end_ts)

        hourly: dict[int, int] = {}
        for ts in timestamps:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            h = dt.astimezone(tz).hour
            hourly[h] = hourly.get(h, 0) + 1
        peak_hour = max(hourly.items(), key=lambda item: item[1])[0] if hourly else None
        continuity = len(hourly)

        start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
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

        inactive = await self._inactivity.compute_inactive_users_for_channel(
            guild_id=guild_id,
            channel_id=channel_id,
            reference_end_ts=end_ts,
            threshold_days=14,
            limit=8,
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
            inactive_users=inactive,
            advice_bullets=advice,
            stats_lines=stats,
        )
