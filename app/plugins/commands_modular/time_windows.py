from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

ROME_TZ = ZoneInfo("Europe/Rome")


@dataclass
class TimeWindowResult:
    start_dt: datetime
    end_dt: datetime
    period_label: str
    label_periodo: str


def parse_italian_datetime(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%y %H:%M"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.replace(tzinfo=ROME_TZ)
        except ValueError:
            continue
    return None


def build_period_label(period_label: str, *, start_dt: datetime, end_dt: datetime, start_ts: str, end_ts: str) -> str:
    if period_label == "oggi":
        return "Oggi"
    if period_label == "ieri":
        return "Ieri"
    if period_label == "ultimi":
        delta = end_dt - start_dt
        if delta.days >= 7:
            weeks = max(1, int(round(delta.days / 7)))
            unit = "settimane" if weeks > 1 else "settimana"
            return f"Ultime {weeks} {unit}"
        if delta.days >= 1:
            days = max(1, delta.days)
            unit = "giorni" if days > 1 else "giorno"
            return f"Ultimi {days} {unit}"
        hours = max(1, int(delta.total_seconds() // 3600))
        if hours >= 1:
            unit = "ore" if hours > 1 else "ora"
            return f"Ultime {hours} {unit}"
        minutes = max(1, int(delta.total_seconds() // 60))
        unit = "minuti" if minutes > 1 else "minuto"
        return f"Ultimi {minutes} {unit}"
    if period_label == "range":
        return f"Dal {format_italian_ts(start_ts)} al {format_italian_ts(end_ts)}"
    return "Periodo personalizzato"


def format_italian_ts(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return str(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ROME_TZ).strftime("%d/%m %H:%M")


def resolve_ultimi_window(quantita: int, unita: str, config: Any) -> tuple[TimeWindowResult | None, str | None]:
    if quantita <= 0:
        return None, "Specifica una quantità valida."
    if unita == "minuti" and quantita > config.riassunto_max_minutes:
        return None, "❌ Limite massimo: ultimi 60 minuti. Prova con le ore (es: /riassunto ultimi 2 ore)."
    if unita == "ore" and quantita > config.riassunto_max_hours:
        return None, "❌ Limite massimo: ultime 24 ore. Prova con i giorni (es: /riassunto ultimi 2 giorni)."
    if unita == "giorni" and quantita > config.riassunto_max_days:
        return None, "❌ Limite massimo: ultimi 30 giorni. Prova con le settimane (es: /riassunto ultimi 2 settimane)."
    if unita == "settimane" and quantita > config.riassunto_max_weeks:
        return None, "❌ Limite massimo: ultime 4 settimane. Riduci la finestra temporale."

    now = datetime.now(ROME_TZ)
    delta_map = {
        "minuti": timedelta(minutes=quantita),
        "ore": timedelta(hours=quantita),
        "giorni": timedelta(days=quantita),
        "settimane": timedelta(weeks=quantita),
    }
    start_dt = now - delta_map.get(unita, timedelta(minutes=quantita))
    return TimeWindowResult(
        start_dt=start_dt,
        end_dt=now,
        period_label="ultimi",
        label_periodo=build_period_label("ultimi", start_dt=start_dt, end_dt=now, start_ts=start_dt.astimezone(timezone.utc).isoformat(), end_ts=now.astimezone(timezone.utc).isoformat()),
    ), None


def resolve_oggi_window() -> TimeWindowResult:
    now = datetime.now(ROME_TZ)
    start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return TimeWindowResult(start_dt=start_dt, end_dt=now, period_label="oggi", label_periodo="Oggi")


def resolve_ieri_window() -> TimeWindowResult:
    now = datetime.now(ROME_TZ)
    end_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=1)
    return TimeWindowResult(start_dt=start_dt, end_dt=end_dt, period_label="ieri", label_periodo="Ieri")


def resolve_range_window(da: str, a: str, config: Any) -> tuple[TimeWindowResult | None, str | None]:
    start_dt = parse_italian_datetime(da)
    end_dt = parse_italian_datetime(a)
    if not start_dt or not end_dt:
        return None, "Formato data/ora non valido. Usa DD/MM/YYYY HH:MM."
    start_utc = start_dt.astimezone(timezone.utc)
    end_utc = end_dt.astimezone(timezone.utc)
    if end_utc < start_utc:
        start_utc, end_utc = end_utc, start_utc
        start_dt, end_dt = end_dt, start_dt
    duration_days = (end_utc - start_utc).total_seconds() / 86400
    if duration_days > config.riassunto_range_max_days:
        return None, "❌ Range troppo elevato (max 30 giorni). Riduci la finestra temporale."
    return TimeWindowResult(
        start_dt=start_dt,
        end_dt=end_dt,
        period_label="range",
        label_periodo=build_period_label("range", start_dt=start_dt, end_dt=end_dt, start_ts=start_utc.isoformat(), end_ts=end_utc.isoformat()),
    ), None
