from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


ROME_TZ = ZoneInfo("Europe/Rome")
ROLLING_WINDOW_UNITS: tuple[str, ...] = ("minuti", "ore", "giorni", "settimane")


@dataclass
class TimeWindowResult:
    start_dt: datetime
    end_dt: datetime
    period_label: str
    label_periodo: str
    requested_quantity: int | None = None
    requested_unit: str | None = None


def _normalize_requested_unit(unit: str | None) -> str:
    normalized = str(unit or "").strip().lower()
    aliases = {
        "minuto": "minuti",
        "minuti": "minuti",
        "ora": "ore",
        "ore": "ore",
        "giorno": "giorni",
        "giorni": "giorni",
        "settimana": "settimane",
        "settimane": "settimane",
    }
    return aliases.get(normalized, "minuti")


def rolling_window_timedelta(quantity: int, unit: str | None) -> timedelta:
    qty = max(1, int(quantity))
    normalized_unit = _normalize_requested_unit(unit)
    delta_map = {
        "minuti": timedelta(minutes=qty),
        "ore": timedelta(hours=qty),
        "giorni": timedelta(days=qty),
        "settimane": timedelta(weeks=qty),
    }
    return delta_map.get(normalized_unit, timedelta(minutes=qty))


def _format_qty_unit(qty: int, singular: str, plural: str) -> str:
    safe_qty = max(1, int(qty))
    return f"{safe_qty} {singular if safe_qty == 1 else plural}"


def _minutes_equivalence_label(total_minutes: int) -> str | None:
    if total_minutes < 1440:
        return None
    days = total_minutes // 1440
    hours = (total_minutes % 1440) // 60
    if days <= 0:
        return None
    day_label = _format_qty_unit(days, "giorno", "giorni")
    if hours <= 0:
        return day_label
    hour_label = _format_qty_unit(hours, "ora", "ore")
    return f"{day_label} e {hour_label}"


def format_rolling_window_label(quantity: int, unit: str, *, include_equivalence: bool = True) -> str:
    qty = max(1, int(quantity))
    normalized_unit = _normalize_requested_unit(unit)
    if normalized_unit == "ore":
        base = "Ultima ora" if qty == 1 else f"Ultime {qty} ore"
        if include_equivalence and qty >= 24:
            base += f" ({_format_qty_unit(qty // 24, 'giorno', 'giorni')})"
        return base
    if normalized_unit == "giorni":
        return "Ultimo giorno" if qty == 1 else f"Ultimi {qty} giorni"
    if normalized_unit == "settimane":
        return "Ultima settimana" if qty == 1 else f"Ultime {qty} settimane"

    base = "Ultimo minuto" if qty == 1 else f"Ultimi {qty} minuti"
    if include_equivalence:
        eq = _minutes_equivalence_label(qty)
        if eq:
            base += f" ({eq})"
    return base


def infer_rolling_window_request(start_dt: datetime, end_dt: datetime) -> tuple[int, str]:
    delta = max(timedelta(minutes=1), end_dt - start_dt)
    total_seconds = int(delta.total_seconds())
    if total_seconds % (7 * 24 * 3600) == 0:
        return max(1, total_seconds // (7 * 24 * 3600)), "settimane"
    if total_seconds % (24 * 3600) == 0:
        return max(1, total_seconds // (24 * 3600)), "giorni"
    if total_seconds % 3600 == 0:
        return max(1, total_seconds // 3600), "ore"
    return max(1, total_seconds // 60), "minuti"


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


def build_period_label(
    period_label: str,
    *,
    start_dt: datetime,
    end_dt: datetime,
    start_ts: str,
    end_ts: str,
    requested_quantity: int | None = None,
    requested_unit: str | None = None,
) -> str:
    if period_label == "oggi":
        return "Oggi"
    if period_label == "ieri":
        return "Ieri"
    if period_label == "ultimi":
        qty = requested_quantity
        unit = _normalize_requested_unit(requested_unit)
        if qty is None:
            qty, unit = infer_rolling_window_request(start_dt, end_dt)
        return format_rolling_window_label(qty, unit)
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
    _ = config
    if quantita <= 0:
        return None, "Specifica una quantità valida."

    now = datetime.now(ROME_TZ)
    start_dt = now - rolling_window_timedelta(quantita, unita)
    return TimeWindowResult(
        start_dt=start_dt,
        end_dt=now,
        period_label="ultimi",
        label_periodo=build_period_label(
            "ultimi",
            start_dt=start_dt,
            end_dt=now,
            start_ts=start_dt.astimezone(timezone.utc).isoformat(),
            end_ts=now.astimezone(timezone.utc).isoformat(),
            requested_quantity=quantita,
            requested_unit=unita,
        ),
        requested_quantity=quantita,
        requested_unit=unita,
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
    _ = config
    start_dt = parse_italian_datetime(da)
    end_dt = parse_italian_datetime(a)
    if not start_dt or not end_dt:
        return None, "Formato data/ora non valido. Usa DD/MM/YYYY HH:MM."
    start_utc = start_dt.astimezone(timezone.utc)
    end_utc = end_dt.astimezone(timezone.utc)
    if end_utc < start_utc:
        start_utc, end_utc = end_utc, start_utc
        start_dt, end_dt = end_dt, start_dt
    return TimeWindowResult(
        start_dt=start_dt,
        end_dt=end_dt,
        period_label="range",
        label_periodo=build_period_label("range", start_dt=start_dt, end_dt=end_dt, start_ts=start_utc.isoformat(), end_ts=end_utc.isoformat()),
    ), None
