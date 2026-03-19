from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.features.barcello.services.barcello import DEFAULT_MITIGATION_FACTORS, DEFAULT_WEIGHT_MULTIPLIERS
from app.services.database import DatabaseService

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    updated: bool
    samples: int
    weights_version: int | None
    summary: str


class BarcelloCalibrationService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def run_calibration(self, days: int = 14, min_samples: int = 20) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        feedback_rows = await self._database.fetch_barcello_feedback(
            time_from=start.isoformat(),
            time_to=now.isoformat(),
        )
        usable = [row for row in feedback_rows if row["delta_target"] is not None and row["rater_user_id"]]
        if len(usable) < min_samples:
            logger.info("Calibration skipped: %s feedback (<%s).", len(usable), min_samples)
            return CalibrationResult(updated=False, samples=len(usable), weights_version=None, summary="Not enough samples.").__dict__

        weights_current = await self._get_current_weights()
        weights_new = dict(weights_current)
        accum: dict[str, float] = {key: 0.0 for key in weights_new}
        reason_counts: dict[str, int] = {}
        reason_deltas: dict[str, int] = {}

        used_samples = 0
        for row in usable:
            delta_target = int(row["delta_target"])
            reason = row["reason"] or "unspecified"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            reason_deltas[reason] = reason_deltas.get(reason, 0) + delta_target

            snapshot = await self._load_snapshot(row["snapshot_id"])
            if snapshot is None:
                continue
            used_samples += 1
            metrics = json.loads(snapshot["metrics_json"])
            features = self._build_features(metrics)
            for key, value in features.items():
                accum[key] += -0.02 * delta_target * value

            if reason == "sarcasmo":
                accum["msg_rate"] -= 0.02
                accum["caps"] -= 0.02
            if reason == "tensione_fredda":
                accum["contrast"] += 0.02
                accum["challenge"] += 0.02

        samples = used_samples
        if samples < min_samples:
            logger.info("Calibration skipped: %s usable snapshots (<%s).", samples, min_samples)
            return CalibrationResult(updated=False, samples=samples, weights_version=None, summary="Not enough usable snapshots.").__dict__
        for key in weights_new:
            delta = accum[key] / samples
            weights_new[key] += delta
            weights_new[key] = self._clamp_weight(key, weights_new[key])
            weights_new[key] = 0.95 * weights_current[key] + 0.05 * weights_new[key]

        mitigation = await self._get_current_mitigation()
        if reason_counts.get("sarcasmo"):
            mitigation["msg_rate_factor"] = max(0.6, mitigation["msg_rate_factor"] - 0.02)
            mitigation["caps_factor"] = max(0.5, mitigation["caps_factor"] - 0.02)
        if reason_counts.get("tensione_fredda"):
            weights_new["contrast"] = min(weights_new["contrast"] * 1.02, 2.0)
            weights_new["challenge"] = min(weights_new["challenge"] * 1.02, 2.0)

        prev_raw = await self._database.get_setting("barcello.weights_json")
        if prev_raw:
            await self._database.set_setting("barcello.weights_prev_json", prev_raw)
        version_raw = await self._database.get_setting("barcello.weights_version")
        version = int(version_raw) + 1 if version_raw and version_raw.isdigit() else 1
        payload = json.dumps(
            {
                "weights": weights_new,
                "mitigation": mitigation,
            },
            ensure_ascii=False,
        )
        await self._database.set_setting("barcello.weights_json", payload)
        await self._database.set_setting("barcello.weights_version", str(version))
        await self._database.set_setting("barcello.weights_updated_at", now.isoformat())

        diff_lines = [f"{key}: {weights_current[key]:.3f} -> {weights_new[key]:.3f}" for key in weights_new]
        logger.info("Calibration updated weights. samples=%s", samples)
        logger.info("Calibration diffs: %s", "; ".join(diff_lines))
        for reason, count in reason_counts.items():
            avg_delta = reason_deltas[reason] / count
            logger.info("Calibration reason=%s count=%s avg_delta=%.2f", reason, count, avg_delta)

        summary = f"Aggiornati {len(weights_new)} pesi. Campioni: {samples}."
        return CalibrationResult(updated=True, samples=samples, weights_version=version, summary=summary).__dict__

    async def _get_current_weights(self) -> dict[str, float]:
        raw = await self._database.get_setting("barcello.weights_json")
        if not raw:
            return dict(DEFAULT_WEIGHT_MULTIPLIERS)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return dict(DEFAULT_WEIGHT_MULTIPLIERS)
        weights = parsed.get("weights") if isinstance(parsed, dict) else None
        if not isinstance(weights, dict):
            return dict(DEFAULT_WEIGHT_MULTIPLIERS)
        merged = dict(DEFAULT_WEIGHT_MULTIPLIERS)
        for key, value in weights.items():
            try:
                merged[key] = float(value)
            except (TypeError, ValueError):
                continue
        return merged

    async def _get_current_mitigation(self) -> dict[str, float]:
        raw = await self._database.get_setting("barcello.weights_json")
        if not raw:
            return dict(DEFAULT_MITIGATION_FACTORS)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return dict(DEFAULT_MITIGATION_FACTORS)
        mitigation = parsed.get("mitigation") if isinstance(parsed, dict) else None
        if not isinstance(mitigation, dict):
            return dict(DEFAULT_MITIGATION_FACTORS)
        merged = dict(DEFAULT_MITIGATION_FACTORS)
        for key, value in mitigation.items():
            try:
                merged[key] = float(value)
            except (TypeError, ValueError):
                continue
        return merged

    def _clamp_weight(self, key: str, value: float) -> float:
        default_value = DEFAULT_WEIGHT_MULTIPLIERS.get(key, 1.0)
        return max(0.2 * default_value, min(2.0 * default_value, value))

    def _build_features(self, metrics: dict[str, Any]) -> dict[str, float]:
        def clamp(value: float) -> float:
            return max(0.0, min(1.0, value))

        playful_ratio = float(metrics.get("playful_emoji_ratio", 0))
        passive_ratio = float(metrics.get("passive_aggressive_emoji_ratio", 0))
        sarcasm_hits_raw = float(metrics.get("sarcasm_marker_hits_raw", 0))
        negativity_hits = float(metrics.get("negativity_hits", 0))
        is_playful = (
            (playful_ratio >= 0.65 or sarcasm_hits_raw >= 3)
            and passive_ratio <= 0.35
            and negativity_hits == 0
        )
        msg_rate = clamp(float(metrics.get("msg_per_min", 0)) / 10.0)
        caps_ratio = clamp(float(metrics.get("caps_ratio", 0)))
        mention_per_min = clamp(float(metrics.get("mention_per_min", 0)) / 5.0)
        negativity_hits_norm = clamp(negativity_hits / 5.0)
        top3 = clamp(float(metrics.get("top3_author_share", 0)))
        burst = clamp(float(metrics.get("burst_ratio", 0)) / 5.0)
        contrast = clamp(float(metrics.get("contrast_per_msg", 0)) / 0.5)
        challenge = clamp(float(metrics.get("challenge_per_msg", 0)) / 0.2)
        return {
            "msg_rate": msg_rate,
            "caps": caps_ratio,
            "mentions": mention_per_min,
            "negativity": negativity_hits_norm,
            "top3": top3,
            "burst": burst,
            "contrast": contrast,
            "challenge": challenge,
            "playful": 1.0 if is_playful else 0.0,
        }

    async def _load_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        parts = snapshot_id.split(":")
        if len(parts) != 3:
            return None
        channel_id, start_ts, end_ts = parts
        try:
            start_dt = datetime.fromisoformat(start_ts)
            end_dt = datetime.fromisoformat(end_ts)
        except ValueError:
            return None
        window_minutes = max(1, int(round((end_dt - start_dt).total_seconds() / 60)))
        snapshot = await self._database.get_barcello_snapshot_by_end(
            channel_id=channel_id,
            window_minutes=window_minutes,
            window_end_ts=end_ts,
        )
        if snapshot is None:
            logger.info("Calibration snapshot not found for %s", snapshot_id)
            return None
        return snapshot
