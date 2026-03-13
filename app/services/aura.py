from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from app.services.database import DatabaseService
from app.services.config_file_loader import load_json_file
from app.services.entitlements import EntitlementsService

logger = logging.getLogger(__name__)
AURA_RULES_CONFIG_PATH = "app/settings/aura_rules.json"
AURA_RULES_EXAMPLE_PATH = "app/settings/aura_rules.example.json"
AURA_MISSIONS_CONFIG_PATH = "app/settings/aura_missions.json"
AURA_MISSIONS_EXAMPLE_PATH = "app/settings/aura_missions.example.json"


@dataclass(frozen=True)
class AuraRuleDefinition:
    points: int
    label_user: str
    label_mod: str
    category: str
    sign: str
    enabled: bool = True

DEFAULT_AURA_RULES: dict[str, int] = {
    "message_participation": 1,
    "voice_participation_minute": 1,
    "first_message_of_day": 5,
    "reply_to_new_user": 8,
    "conversation_starter": 6,
    "cross_user_interaction": 7,
    "cross_channel_participation": 8,
    "positive_climate_contribution": 10,
    "barcello_invigorate_bonus": 10,
    "climate_degrade": -10,
    "monopoly_penalty": -6,
    "low_diversity_penalty": -5,
    "barcello_degrade_penalty": -10,
    "voice_join_bonus": 4,
    "voice_starter_bonus": 10,
    "helpful_reply": 6,
    "welcome_back_user": 7,
    "balanced_presence_bonus": 9,
    "high_diversity_bonus": 8,
    "sustained_consistency_bonus": 10,
    "mission_completed": 15,
    "spam_like_penalty": -8,
    "tension_chain_penalty": -7,
    "good_morning_first": 12,
}

AURA_REASON_HUMAN: dict[str, str] = {
    "message_participation": "per partecipazione ai messaggi",
    "voice_participation_minute": "per partecipazione vocale al minuto",
    "first_message_of_day": "per aver scritto per prima nel giorno",
    "reply_to_new_user": "per aver risposto a una persona nuova",
    "positive_climate_contribution": "per aver contribuito a un clima più costruttivo",
    "climate_degrade": "per aver abbassato il clima in una discussione",
    "monopoly_penalty": "per aver monopolizzato la conversazione",
    "voice_join_bonus": "per aver partecipato in canale vocale",
    "mission_completed": "per aver completato una missione giornaliera",
    "conversation_starter": "per aver avviato una conversazione",
    "cross_user_interaction": "per aver coinvolto utenti diversi",
    "low_diversity_penalty": "per bassa diversità nelle interazioni",
    "barcello_invigorate_bonus": "per aver contribuito a migliorare il barcello",
    "barcello_degrade_penalty": "per aver contribuito a degradare il barcello",
    "cross_channel_participation": "per aver partecipato in canali diversi",
    "voice_starter_bonus": "per essere entrato per primo in vocale",
    "helpful_reply": "per una risposta utile e costruttiva",
    "welcome_back_user": "per aver accolto un utente di ritorno",
    "balanced_presence_bonus": "per presenza bilanciata e costante",
    "high_diversity_bonus": "per alta diversità nelle interazioni",
    "sustained_consistency_bonus": "per costanza positiva nel periodo",
    "spam_like_penalty": "per comportamento simile a spam",
    "tension_chain_penalty": "per aver alimentato una catena di tensione",
    "good_morning_first": "per aver dato il buongiorno per prima",
    "mission_task_reward": "per aver completato una missione assegnata",
    "ondemand.aggregate": "bilancio complessivo del periodo",
    "batch.aggregate": "bilancio aggregato periodico",
}


def _build_default_rule_definitions() -> dict[str, AuraRuleDefinition]:
    out: dict[str, AuraRuleDefinition] = {}
    for code, points in DEFAULT_AURA_RULES.items():
        label = AURA_REASON_HUMAN.get(code, f"attività registrata ({code})")
        out[code] = AuraRuleDefinition(
            points=int(points),
            label_user=label,
            label_mod=label,
            category="penalita" if int(points) < 0 else "attivita",
            sign="negative" if int(points) < 0 else "positive",
            enabled=True,
        )
    return out


def _parse_rule_definition(reason_code: str, value: Any, defaults: AuraRuleDefinition | None = None) -> AuraRuleDefinition | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        points = int(value)
        base_label = defaults.label_user if defaults else AURA_REASON_HUMAN.get(reason_code, f"attività registrata ({reason_code})")
        return AuraRuleDefinition(
            points=points,
            label_user=base_label,
            label_mod=(defaults.label_mod if defaults else base_label),
            category=(defaults.category if defaults else ("penalita" if points < 0 else "attivita")),
            sign=(defaults.sign if defaults else ("negative" if points < 0 else "positive")),
            enabled=(defaults.enabled if defaults else True),
        )
    if not isinstance(value, dict):
        return None
    raw_points = value.get("points", defaults.points if defaults else 0)
    try:
        points = int(raw_points)
    except (TypeError, ValueError):
        points = defaults.points if defaults else 0
    base_label = AURA_REASON_HUMAN.get(reason_code, f"attività registrata ({reason_code})")
    label_user = str(value.get("label_user") or (defaults.label_user if defaults else base_label)).strip() or base_label
    label_mod = str(value.get("label_mod") or (defaults.label_mod if defaults else label_user)).strip() or label_user
    category = str(value.get("category") or (defaults.category if defaults else "attivita")).strip() or "attivita"
    sign = str(value.get("sign") or (defaults.sign if defaults else ("negative" if points < 0 else "positive"))).strip() or ("negative" if points < 0 else "positive")
    enabled = bool(value.get("enabled", defaults.enabled if defaults else True))
    return AuraRuleDefinition(points=points, label_user=label_user, label_mod=label_mod, category=category, sign=sign, enabled=enabled)


def load_aura_rule_definitions() -> dict[str, AuraRuleDefinition]:
    data = load_json_file(AURA_RULES_CONFIG_PATH)
    if not data:
        data = load_json_file(AURA_RULES_EXAMPLE_PATH)
    defaults = _build_default_rule_definitions()
    if not isinstance(data, dict):
        return defaults
    parsed = dict(defaults)
    for k, v in data.items():
        code = str(k)
        parsed_rule = _parse_rule_definition(code, v, parsed.get(code))
        if parsed_rule is not None:
            parsed[code] = parsed_rule
    return parsed


def resolve_aura_reason_label(reason_code: str, *, audience: str = "user") -> str:
    rules = load_aura_rule_definitions()
    reason = rules.get(reason_code)
    if reason is not None:
        label = reason.label_mod if audience == "mod" else reason.label_user
        return label.strip() or AURA_REASON_HUMAN.get(reason_code, reason_code)
    if reason_code in AURA_REASON_HUMAN:
        return AURA_REASON_HUMAN[reason_code]
    return f"attività registrata ({reason_code})"


def build_discord_jump_link(guild_id: str, channel_id: str | None, message_id: str | None) -> str | None:
    if not channel_id or not message_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


@dataclass
class AuraEligibilityResult:
    eligible: bool
    reason: str


def render_karma_bar(percent: int) -> str:
    value = max(0, min(100, int(percent)))
    center = "🟢"
    if value < 35:
        center = "🔴"
    elif value < 67:
        center = "🟡"
    return f"😈━━━━━━━━{center}━━━━😇  {value}%"


def aura_reason_to_human(reason_code: str) -> str:
    return resolve_aura_reason_label(reason_code, audience="user")


def load_aura_rules() -> dict[str, int]:
    return {k: v.points for k, v in load_aura_rule_definitions().items()}


def load_aura_missions_config() -> dict[str, Any]:
    data = load_json_file(AURA_MISSIONS_CONFIG_PATH)
    if not data:
        data = load_json_file(AURA_MISSIONS_EXAMPLE_PATH)
    if not isinstance(data, dict):
        return {"max_per_day": 3, "missions": []}
    return data


def normalize_text_for_matching(text: str) -> str:
    raw = " ".join((text or "").lower().split())
    chars: list[str] = []
    prev = ""
    streak = 0
    for ch in raw:
        if ch == prev:
            streak += 1
        else:
            streak = 1
            prev = ch
        if streak <= 2:
            chars.append(ch)
    return "".join(chars)


class AuraMissionService:
    def __init__(self, database: DatabaseService, scoring: AuraScoringService) -> None:
        self._db = database
        self._scoring = scoring

    async def assign_daily_missions_for_user(
        self,
        *,
        guild_id: str,
        user_id: str,
        ts: str,
        metrics: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        cfg = load_aura_missions_config()
        mission_defs = cfg.get("missions", []) if isinstance(cfg.get("missions", []), list) else []
        if not mission_defs:
            return []
        current_day = datetime.fromisoformat(ts).date().isoformat()
        active = await self._db.list_aura_missions_for_user(guild_id, user_id, f"{current_day}T00:00:00+00:00", f"{current_day}T23:59:59+00:00")
        existing_ids = {str(item.get("mission_id")) for item in active}
        max_per_day = int(cfg.get("max_per_day", 3) or 3)
        remaining = max(0, max_per_day - len(existing_ids))
        if remaining <= 0:
            return active

        chosen: list[dict[str, Any]] = []
        m = metrics or {}
        unique = int(m.get("unique_interactions", 0) or 0)
        degrade = int(m.get("degrade_events", 0) or 0)
        msg_count = int(m.get("msg_count", 0) or 0)
        for item in mission_defs:
            if remaining <= 0:
                break
            if not isinstance(item, dict) or not bool(item.get("enabled", True)):
                continue
            mission_id = str(item.get("id", "")).strip()
            if not mission_id or mission_id in existing_ids:
                continue
            cond = str(item.get("condition", "always")).strip().lower()
            ok = cond == "always"
            if cond == "low_diversity":
                ok = unique < 2
            elif cond == "tension":
                ok = degrade > 0
            elif cond == "high_activity":
                ok = msg_count >= 8
            if not ok:
                continue
            due = f"{current_day}T23:59:59+00:00"
            reward = int(item.get("reward_points", item.get("bonus_points", 0)) or 0)
            await self._db.assign_aura_mission(
                guild_id=guild_id,
                user_id=user_id,
                mission_id=mission_id,
                assigned_at=ts,
                due_date=due,
                reward_points=reward,
                meta={"label": str(item.get("text", mission_id)), "config": item},
            )
            chosen.append({"mission_id": mission_id, "reward_points": reward})
            existing_ids.add(mission_id)
            remaining -= 1
        return chosen

    async def process_message_for_missions(
        self,
        *,
        guild_id: str,
        user_id: str,
        channel_id: str,
        message_id: str,
        ts: str,
        content: str,
        mentions: list[str],
    ) -> list[str]:
        now = datetime.fromisoformat(ts)
        day = now.date().isoformat()
        cfg = load_aura_missions_config()
        mission_defs = cfg.get("missions", []) if isinstance(cfg.get("missions", []), list) else []
        mission_by_id = {str(item.get("id", "")): item for item in mission_defs if isinstance(item, dict)}
        active = await self._db.list_aura_missions_for_user(guild_id, user_id, f"{day}T00:00:00+00:00", f"{day}T23:59:59+00:00")
        completed: list[str] = []
        normalized = normalize_text_for_matching(content)
        for mission in active:
            if mission.get("status") != "assigned":
                continue
            mission_id = str(mission.get("mission_id", ""))
            reward = int(mission.get("reward_points", 0) or 0)
            meta = mission.get("meta", {}) if isinstance(mission.get("meta"), dict) else {}
            mission_cfg = mission_by_id.get(mission_id, {})
            completion_text = str(mission_cfg.get("completion_text") or f"aver completato la missione '{meta.get('label', mission_id)}'")
            if mission_id == "good_morning":
                gm = cfg.get("good_morning", {}) if isinstance(cfg, dict) else {}
                start_hour = int(gm.get("start_hour", 5) or 5)
                end_hour = int(gm.get("end_hour", 11) or 11)
                keywords = [str(x).lower() for x in gm.get("keywords", ["buongiorno", "buon giorno"]) if str(x).strip()]
                if now.hour < start_hour or now.hour > end_hour:
                    continue
                if not any(k in normalized for k in keywords):
                    continue
                if await self._db.count_guild_good_morning_before(guild_id, day, ts, keywords) != 0:
                    continue
            elif mission_id == "talk_new_user":
                if len(set(mentions)) < 1:
                    continue
            elif mission_id == "cross_channel_presence":
                req = int(meta.get("config", {}).get("require_channels_count", 2) if isinstance(meta.get("config"), dict) else 2)
                channels = await self._db.count_user_distinct_channels_for_day(guild_id, user_id, day)
                if channels < req:
                    continue
            elif mission_id == "balanced_participation":
                req = int(meta.get("config", {}).get("require_messages", 8) if isinstance(meta.get("config"), dict) else 8)
                msg_count = await self._db.count_user_messages_for_day(guild_id, user_id, day)
                if msg_count < req:
                    continue
            elif mission_id == "voice_starter":
                continue

            if hasattr(self._db, "aura_ledger_event_already_recorded"):
                already_processed = await self._db.aura_ledger_event_already_recorded(
                    guild_id=guild_id,
                    user_id=user_id,
                    reason_code="mission_completed",
                    message_id=message_id,
                    source_event="mission.completed",
                    mission_id=mission_id,
                )
                if already_processed:
                    logger.info(
                        "Skipping mission processing already completed on message: guild=%s user=%s mission=%s message_id=%s",
                        guild_id,
                        user_id,
                        mission_id,
                        message_id,
                    )
                    continue

            await self._db.complete_aura_mission(guild_id=guild_id, user_id=user_id, mission_id=mission_id, assigned_at=str(mission.get("assigned_at")), completed_at=ts)
            if reward > 0:
                reward_reason = str(mission_cfg.get("rule_on_complete") or ("good_morning_first" if mission_id == "good_morning" else "mission_task_reward"))
                if reward_reason == "mission_completed":
                    reward_reason = "mission_task_reward"
                await self._scoring.award_points(
                    guild_id=guild_id,
                    user_id=user_id,
                    reason_code=reward_reason,
                    ts=ts,
                    channel_id=channel_id,
                    points=reward,
                    message_id=message_id,
                    source_service="mission",
                    source_event="mission.reward",
                    meta={"mission_id": mission_id, "mission_label": meta.get("label", mission_id), "completion_text": completion_text, "mission_reward_points": reward},
                )
            await self._maybe_apply_all_missions_completion_bonus(
                guild_id=guild_id,
                user_id=user_id,
                day=day,
                ts=ts,
                channel_id=channel_id,
                message_id=message_id,
                mission_id=mission_id,
            )
            completed.append(mission_id)
        return completed

    async def _maybe_apply_all_missions_completion_bonus(
        self,
        *,
        guild_id: str,
        user_id: str,
        day: str,
        ts: str,
        channel_id: str,
        message_id: str,
        mission_id: str,
    ) -> None:
        assigned = await self._db.list_aura_missions_for_user(guild_id, user_id, f"{day}T00:00:00+00:00", f"{day}T23:59:59+00:00")
        if not assigned:
            return
        if any(str(item.get("status", "")) != "completed" for item in assigned):
            return
        completion_event_id = f"mission-all-completed:{day}"
        if hasattr(self._db, "aura_ledger_event_already_recorded"):
            already = await self._db.aura_ledger_event_already_recorded(
                guild_id=guild_id,
                user_id=user_id,
                reason_code="mission_completed",
                message_id=completion_event_id,
                source_event="mission.all_completed",
                mission_id=None,
            )
            if already:
                return
        await self._scoring.apply_rule(
            guild_id=guild_id,
            user_id=user_id,
            rule_code="mission_completed",
            ts=ts,
            channel_id=channel_id,
            message_id=completion_event_id,
            source_service="mission",
            source_event="mission.all_completed",
            meta={"mission_id": mission_id, "trigger_message_id": message_id, "day": day, "all_missions_completed_rewarded": True},
        )

    async def expire_missions(self, *, guild_id: str, user_id: str, ts: str) -> None:
        await self._db.expire_aura_missions(guild_id=guild_id, user_id=user_id, now_ts=ts)


class AuraScoringService:
    def __init__(self, database: DatabaseService) -> None:
        self._db = database
        self._rules = load_aura_rules()

    async def award_points(
        self,
        *,
        guild_id: str,
        user_id: str,
        reason_code: str,
        ts: str,
        channel_id: str | None = None,
        points: int | None = None,
        message_id: str | None = None,
        source_service: str = "aura",
        source_event: str = "award",
        meta: dict[str, Any] | None = None,
    ) -> int:
        delta = abs(int(points if points is not None else self._rules.get(reason_code, 1)))
        await self.record_event(
            guild_id=guild_id,
            user_id=user_id,
            reason_code=reason_code,
            delta_points=delta,
            ts=ts,
            channel_id=channel_id,
            message_id=message_id,
            source_service=source_service,
            source_event=source_event,
            meta=meta,
        )
        return delta

    async def penalize_points(
        self,
        *,
        guild_id: str,
        user_id: str,
        reason_code: str,
        ts: str,
        channel_id: str | None = None,
        points: int | None = None,
        message_id: str | None = None,
        source_service: str = "aura",
        source_event: str = "penalty",
        meta: dict[str, Any] | None = None,
    ) -> int:
        base = int(points if points is not None else abs(self._rules.get(reason_code, -1)))
        delta = -abs(base)
        await self.record_event(
            guild_id=guild_id,
            user_id=user_id,
            reason_code=reason_code,
            delta_points=delta,
            ts=ts,
            channel_id=channel_id,
            message_id=message_id,
            source_service=source_service,
            source_event=source_event,
            meta=meta,
        )
        return delta

    async def record_event(
        self,
        *,
        guild_id: str,
        user_id: str,
        reason_code: str,
        delta_points: int,
        ts: str,
        channel_id: str | None = None,
        message_id: str | None = None,
        source_service: str = "aura",
        source_event: str = "record",
        meta: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(meta or {})
        payload.setdefault("reason_human", resolve_aura_reason_label(reason_code, audience="user"))
        payload.setdefault("reason_human_mod", resolve_aura_reason_label(reason_code, audience="mod"))
        payload.setdefault("message_id", message_id)
        payload.setdefault("source_service", source_service)
        payload.setdefault("source_event", source_event)

        mission_id = str(payload.get("mission_id") or "").strip() or None
        normalized_message_id = str(message_id or payload.get("message_id") or "").strip()
        if normalized_message_id and hasattr(self._db, "aura_ledger_event_already_recorded"):
            already = await self._db.aura_ledger_event_already_recorded(
                guild_id=guild_id,
                user_id=user_id,
                reason_code=reason_code,
                message_id=normalized_message_id,
                source_event=source_event,
                mission_id=mission_id,
            )
            if already:
                logger.info(
                    "Skipping already processed aura ledger event: guild=%s user=%s reason=%s source_event=%s message_id=%s mission_id=%s",
                    guild_id,
                    user_id,
                    reason_code,
                    source_event,
                    normalized_message_id,
                    mission_id,
                )
                return

        await self._db.insert_aura_ledger_event(
            guild_id,
            user_id,
            channel_id,
            ts,
            reason_code,
            int(delta_points),
            payload,
        )

    async def apply_rule(
        self,
        *,
        guild_id: str,
        user_id: str,
        rule_code: str,
        ts: str,
        channel_id: str | None = None,
        message_id: str | None = None,
        source_service: str = "aura",
        source_event: str = "rule",
        meta: dict[str, Any] | None = None,
    ) -> int:
        points = int(self._rules.get(rule_code, 0))
        if points >= 0:
            return await self.award_points(
                guild_id=guild_id,
                user_id=user_id,
                reason_code=rule_code,
                ts=ts,
                channel_id=channel_id,
                points=points,
                message_id=message_id,
                source_service=source_service,
                source_event=source_event,
                meta=meta,
            )
        return await self.penalize_points(
            guild_id=guild_id,
            user_id=user_id,
            reason_code=rule_code,
            ts=ts,
            channel_id=channel_id,
            points=abs(points),
            message_id=message_id,
            source_service=source_service,
            source_event=source_event,
            meta=meta,
        )


class AuraEligibilityService:
    def __init__(self, database: DatabaseService, entitlements: EntitlementsService) -> None:
        self._db = database
        self._entitlements = entitlements

    async def evaluate_member(self, member: discord.abc.User, guild_id: str, start_ts: str, end_ts: str) -> AuraEligibilityResult:
        aura_config = await self._entitlements.get_feature_profile_config(member, "aura")
        eligibility = aura_config.get("eligibility", {}) if isinstance(aura_config, dict) else {}
        if not bool(aura_config.get("enabled", False)):
            return AuraEligibilityResult(False, "Aura non attiva per il tuo tier")

        if bool(eligibility.get("exclude_bots", True)) and bool(getattr(member, "bot", False)):
            return AuraEligibilityResult(False, "Aura non attiva: account bot escluso")

        min_age = int(eligibility.get("min_account_age_days", 7) or 7)
        created_at = getattr(member, "created_at", None)
        if isinstance(created_at, datetime):
            created_dt = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created_dt < timedelta(days=min_age):
                return AuraEligibilityResult(False, f"Aura non attiva: account troppo recente (min {min_age} giorni)")

        exclude_roles = {str(r).lower() for r in eligibility.get("exclude_roles", []) if r is not None}
        if exclude_roles:
            for role in getattr(member, "roles", []):
                if str(getattr(role, "id", "")).lower() in exclude_roles or str(getattr(role, "name", "")).lower() in exclude_roles:
                    return AuraEligibilityResult(False, "Aura non attiva: ruolo escluso")

        if bool(eligibility.get("exclude_if_flagged_fake", True)):
            fake_users_raw = await self._db.get_setting("aura.fake_user_ids")
            fake_users: set[str] = set()
            if fake_users_raw:
                try:
                    parsed = json.loads(fake_users_raw)
                    if isinstance(parsed, list):
                        fake_users = {str(x) for x in parsed}
                except json.JSONDecodeError:
                    logger.warning("Invalid aura.fake_user_ids setting")
            if str(getattr(member, "id", "")) in fake_users:
                return AuraEligibilityResult(False, "Aura non attiva: account segnalato")

        min_messages = int(eligibility.get("min_messages_in_range", 20) or 20)
        user_id = str(getattr(member, "id", ""))
        count = await self._db.count_user_messages_in_range(guild_id, user_id, start_ts, end_ts)
        if count < min_messages:
            return AuraEligibilityResult(False, f"Aura non attiva: servono almeno {min_messages} messaggi nel periodo")

        return AuraEligibilityResult(True, "ok")


class AuraRollingStatsService:
    def __init__(self, database: DatabaseService) -> None:
        self._db = database
        self._scoring = AuraScoringService(database)
        self._missions = AuraMissionService(database, self._scoring)

    async def on_message_saved(self, *, guild_id: str, channel_id: str, user_id: str, ts: str, mentions: list[str], message_id: str | None = None, content: str = "") -> None:
        window_key = datetime.fromisoformat(ts).date().isoformat()
        await self._db.upsert_aura_rolling_on_message(
            guild_id=guild_id,
            user_id=user_id,
            window_key=window_key,
            ts=ts,
            unique_increment=max(1, len(set(mentions))),
        )
        await self._scoring.apply_rule(
            guild_id=guild_id,
            user_id=user_id,
            rule_code="message_participation",
            ts=ts,
            channel_id=channel_id,
            message_id=message_id,
            source_service="discord_adapter",
            source_event="message.participation",
        )
        if await self._db.count_user_messages_for_day(guild_id, user_id, window_key) == 1:
            await self._scoring.apply_rule(
                guild_id=guild_id,
                user_id=user_id,
                rule_code="first_message_of_day",
                ts=ts,
                channel_id=channel_id,
                message_id=message_id,
                source_service="discord_adapter",
                source_event="message.first_of_day",
            )
        if mentions:
            await self._scoring.apply_rule(
                guild_id=guild_id,
                user_id=user_id,
                rule_code="cross_user_interaction" if "cross_user_interaction" in self._scoring._rules else "reply_to_new_user",
                ts=ts,
                channel_id=channel_id,
                message_id=message_id,
                source_service="discord_adapter",
                source_event="message.mentions",
                meta={"mentions_count": len(set(mentions))},
            )
        await self._apply_message_penalties(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            ts=ts,
            message_id=message_id,
            content=content,
        )
        metrics_today = await self._db.fetch_aura_metrics(guild_id, user_id, f"{window_key}T00:00:00+00:00", f"{window_key}T23:59:59+00:00", channel_id=None)
        await self._missions.expire_missions(guild_id=guild_id, user_id=user_id, ts=ts)
        await self._missions.assign_daily_missions_for_user(guild_id=guild_id, user_id=user_id, ts=ts, metrics=metrics_today)
        if message_id:
            await self._missions.process_message_for_missions(
                guild_id=guild_id,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_id,
                ts=ts,
                content=content,
                mentions=mentions,
            )

    async def on_barcello_event(self, *, guild_id: str, ts: str, invigorate: bool) -> None:
        active_users = await self._db.fetch_recent_active_users(guild_id, ts, minutes=30)
        for user_id in active_users:
            await self._db.upsert_aura_rolling_on_barcello(
                guild_id=guild_id,
                user_id=user_id,
                window_key=datetime.fromisoformat(ts).date().isoformat(),
                ts=ts,
                invigorate=invigorate,
            )
            await self._scoring.apply_rule(
                guild_id=guild_id,
                user_id=str(user_id),
                rule_code="barcello_invigorate_bonus" if invigorate and "barcello_invigorate_bonus" in self._scoring._rules else "positive_climate_contribution" if invigorate else "barcello_degrade_penalty" if "barcello_degrade_penalty" in self._scoring._rules else "climate_degrade",
                ts=ts,
                source_service="barcello",
                source_event="barcello.result",
                meta={"invigorate": invigorate},
            )
            await self._scoring.apply_rule(
                guild_id=guild_id,
                user_id=str(user_id),
                rule_code="positive_climate_contribution" if invigorate else "climate_degrade",
                ts=ts,
                source_service="barcello",
                source_event="barcello.climate",
                meta={"invigorate": invigorate},
            )

    async def _apply_message_penalties(self, *, guild_id: str, channel_id: str, user_id: str, ts: str, message_id: str | None, content: str) -> None:
        day = datetime.fromisoformat(ts).date().isoformat()
        metrics = await self._db.fetch_aura_metrics(guild_id, user_id, f"{day}T00:00:00+00:00", f"{day}T23:59:59+00:00", channel_id=None)
        msg_count = int(metrics.get("msg_count", 0) or 0)
        unique_interactions = int(metrics.get("unique_interactions", 0) or 0)
        degrade_events = int(metrics.get("degrade_events", 0) or 0)
        source_event = "message.quality.penalty"
        synthetic_message_id = f"{day}:{channel_id}:{user_id}"

        if msg_count >= 12 and unique_interactions <= 2:
            await self._scoring.apply_rule(
                guild_id=guild_id,
                user_id=user_id,
                rule_code="monopoly_penalty",
                ts=ts,
                channel_id=channel_id,
                message_id=f"{synthetic_message_id}:monopoly",
                source_service="discord_adapter",
                source_event=source_event,
            )
        if msg_count >= 8 and unique_interactions <= 1:
            await self._scoring.apply_rule(
                guild_id=guild_id,
                user_id=user_id,
                rule_code="low_diversity_penalty",
                ts=ts,
                channel_id=channel_id,
                message_id=f"{synthetic_message_id}:low_diversity",
                source_service="discord_adapter",
                source_event=source_event,
            )
        if degrade_events >= 3:
            await self._scoring.apply_rule(
                guild_id=guild_id,
                user_id=user_id,
                rule_code="tension_chain_penalty",
                ts=ts,
                channel_id=channel_id,
                message_id=f"{synthetic_message_id}:tension",
                source_service="discord_adapter",
                source_event=source_event,
            )
        if content and hasattr(self._db, "count_recent_user_messages_with_same_content"):
            repeated = await self._db.count_recent_user_messages_with_same_content(guild_id=guild_id, user_id=user_id, content=content, until_ts=ts, lookback_minutes=5)
            if repeated >= 3:
                await self._scoring.apply_rule(
                    guild_id=guild_id,
                    user_id=user_id,
                    rule_code="spam_like_penalty",
                    ts=ts,
                    channel_id=channel_id,
                    message_id=message_id,
                    source_service="discord_adapter",
                    source_event="message.spam_like",
                    meta={"repeated_messages": repeated},
                )

    async def on_voice_participation(self, *, guild_id: str, voice_channel_id: str, user_id: str, minutes: int, ts: str, voice_session_id: str | None = None) -> None:
        valid_minutes = max(0, int(minutes))
        if valid_minutes <= 0:
            return
        voice_event_id = f"voice-minutes:{voice_session_id or voice_channel_id}:{user_id}:{valid_minutes}"
        await self._scoring.award_points(
            guild_id=guild_id,
            user_id=user_id,
            reason_code="voice_participation_minute",
            ts=ts,
            channel_id=voice_channel_id,
            points=valid_minutes,
            message_id=voice_event_id,
            source_service="voice",
            source_event="voice.participation.minutes",
            meta={"voice_session_id": voice_session_id, "minutes": valid_minutes},
        )

    async def on_voice_join(self, *, guild_id: str, voice_channel_id: str, user_id: str, ts: str, event_id: str) -> None:
        await self._scoring.apply_rule(
            guild_id=guild_id,
            user_id=user_id,
            rule_code="voice_join_bonus",
            ts=ts,
            channel_id=voice_channel_id,
            message_id=event_id,
            source_service="voice",
            source_event="voice.join",
        )

    async def on_voice_starter(self, *, guild_id: str, voice_channel_id: str, user_id: str, ts: str, day_key: str) -> None:
        await self._scoring.apply_rule(
            guild_id=guild_id,
            user_id=user_id,
            rule_code="voice_starter_bonus",
            ts=ts,
            channel_id=voice_channel_id,
            message_id=f"voice-starter:{voice_channel_id}:{day_key}",
            source_service="voice",
            source_event="voice.starter",
        )


async def compute_and_store_aura_result(
    db: DatabaseService,
    *,
    guild_id: str,
    user_id: str,
    start_ts: str,
    end_ts: str,
    channel_id: str | None,
    reason_code: str | None = None,
) -> None:
    metrics = await db.fetch_aura_metrics(guild_id, user_id, start_ts, end_ts, channel_id=channel_id)
    if channel_id is None:
        karma_percent = max(0, min(100, 50 + metrics["invigorate_events"] * 4 - metrics["degrade_events"] * 6 + min(metrics["msg_count"], 40) // 2))
        trend_delta = metrics["invigorate_events"] - metrics["degrade_events"]
        points_total = karma_percent + trend_delta
    else:
        karma_percent = max(0, min(100, 45 + metrics["invigorate_events"] * 4 - metrics["degrade_events"] * 6 + min(metrics["msg_count"], 30) // 2))
        trend_delta = metrics["invigorate_events"] - metrics["degrade_events"]
        points_total = karma_percent

    await db.upsert_aura_result(
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        period_start=start_ts,
        period_end=end_ts,
        karma_percent=karma_percent,
        trend_delta=trend_delta,
        points_total=points_total,
        metrics_json=json.dumps(metrics),
        computed_at=end_ts,
    )

    if reason_code:
        await db.insert_aura_ledger_event(
            guild_id,
            user_id,
            channel_id,
            end_ts,
            reason_code,
            points_total,
            {"period_start": start_ts, "period_end": end_ts, "channel_id": channel_id},
        )


class AuraAggregationJob:
    def __init__(
        self,
        database: DatabaseService,
        bot: discord.Client,
        eligibility_service: AuraEligibilityService,
        *,
        interval_seconds: int = 21600,
    ) -> None:
        self._db = database
        self._bot = bot
        self._eligibility = eligibility_service
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Aura aggregation tick failed")
            await asyncio.sleep(self._interval_seconds)

    async def run_once(self) -> None:
        now = datetime.now(timezone.utc)
        period_start = (now - timedelta(days=30)).isoformat()
        period_end = now.isoformat()
        for guild in self._bot.guilds:
            guild_id = str(guild.id)
            for member in guild.members:
                eligibility = await self._eligibility.evaluate_member(member, guild_id, period_start, period_end)
                role_tier = await self._eligibility._entitlements.resolve_profile(member)
                await self._db.upsert_aura_user_profile(
                    guild_id=guild_id,
                    user_id=str(member.id),
                    eligible=1 if eligibility.eligible else 0,
                    eligibility_reason=eligibility.reason,
                    role_tier=role_tier,
                    last_computed_at=period_end,
                )
                if not eligibility.eligible:
                    continue
                await compute_and_store_aura_result(
                    self._db,
                    guild_id=guild_id,
                    user_id=str(member.id),
                    start_ts=period_start,
                    end_ts=period_end,
                    channel_id=None,
                    reason_code="batch.aggregate",
                )
                channels = await self._db.fetch_user_channels_in_range(guild_id, str(member.id), period_start, period_end)
                for channel_id in channels:
                    await compute_and_store_aura_result(
                        self._db,
                        guild_id=guild_id,
                        user_id=str(member.id),
                        start_ts=period_start,
                        end_ts=period_end,
                        channel_id=channel_id,
                    )


class ArchetypeAnalyzerService:
    ARCHETYPE_KEYS: tuple[str, ...] = (
        "scintilla",
        "pacificatore",
        "agitatore",
        "collante",
        "mediatore",
        "esploratore_sociale",
        "costante",
        "lampo",
        "silenzioso",
        "ascoltatore",
        "selettivo",
        "dominante",
    )
    ARCHETYPE_PERIOD_DAYS = 90

    def __init__(
        self,
        database: DatabaseService,
        bot: discord.Client,
        eligibility_service: AuraEligibilityService,
        *,
        interval_seconds: int = 86400,
    ) -> None:
        self._db = database
        self._bot = bot
        self._eligibility = eligibility_service
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Archetype analyzer tick failed")
            await asyncio.sleep(self._interval_seconds)

    async def run_once(self) -> None:
        now = datetime.now(timezone.utc)
        period_start = (now - timedelta(days=self.ARCHETYPE_PERIOD_DAYS)).isoformat()
        period_end = now.isoformat()
        for guild in self._bot.guilds:
            guild_id = str(guild.id)
            for member in guild.members:
                eligibility = await self._eligibility.evaluate_member(member, guild_id, period_start, period_end)
                if not eligibility.eligible:
                    continue
                metrics = await self._db.fetch_aura_metrics(guild_id, str(member.id), period_start, period_end)
                metrics_detail = await self._fetch_archetype_metrics(guild_id=guild_id, user_id=str(member.id), period_start=period_start, period_end=period_end, base_metrics=metrics)
                raw_scores = self._compute_archetype_raw_scores(metrics_detail)
                score_payload = self._normalize_archetype_scores(raw_scores)
                reasons = self._build_archetype_debug_reasons(metrics_detail, raw_scores, score_payload)
                insights = [
                    "Mantieni costanza settimanale per aumentare la stabilità.",
                    "Interagire con utenti diversi migliora la diversità.",
                ]
                await self._db.upsert_archetype_profile(
                    guild_id=guild_id,
                    user_id=str(member.id),
                    period_days=self.ARCHETYPE_PERIOD_DAYS,
                    archetype_scores_json=json.dumps(score_payload),
                    metrics_json=json.dumps({"insights": insights, "scores": score_payload, "metrics": metrics_detail, "reasons": reasons}),
                    computed_at=period_end,
                )

    async def _fetch_archetype_metrics(self, *, guild_id: str, user_id: str, period_start: str, period_end: str, base_metrics: dict[str, int]) -> dict[str, float | int]:
        totals = await self._db.fetchone(
            """
            SELECT
                COUNT(*) AS msg_count,
                COUNT(DISTINCT channel_id) AS channel_diversity,
                COUNT(DISTINCT substr(ts, 1, 10)) AS active_days,
                SUM(CASE WHEN reply_to_message_id IS NOT NULL THEN 1 ELSE 0 END) AS replies_sent
            FROM messages
            WHERE guild_id = ? AND author_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            """,
            (guild_id, user_id, period_start, period_end),
        )
        day_rows = await self._db.fetchall(
            """
            SELECT substr(ts, 1, 10) AS day_key, COUNT(*) AS day_msgs
            FROM messages
            WHERE guild_id = ? AND author_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            GROUP BY day_key
            """,
            (guild_id, user_id, period_start, period_end),
        )
        mention_rows = await self._db.fetchall(
            """
            SELECT mentions_json
            FROM messages
            WHERE guild_id = ? AND author_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
            """,
            (guild_id, user_id, period_start, period_end),
        )
        first_msg_days = await self._db.fetchone(
            """
            SELECT COUNT(*) AS cnt
            FROM (
                SELECT m.message_id
                FROM messages m
                JOIN (
                    SELECT substr(ts, 1, 10) AS day_key, MIN(ts) AS min_ts
                    FROM messages
                    WHERE guild_id = ? AND ts >= ? AND ts <= ? AND COALESCE(is_deleted, 0) = 0
                    GROUP BY day_key
                ) first_of_day ON substr(m.ts, 1, 10) = first_of_day.day_key AND m.ts = first_of_day.min_ts
                WHERE m.guild_id = ? AND m.author_id = ?
            ) t
            """,
            (guild_id, period_start, period_end, guild_id, user_id),
        )
        mission_row = await self._db.fetchone(
            """
            SELECT COUNT(*) AS completed
            FROM aura_events_ledger
            WHERE guild_id = ? AND user_id = ? AND ts >= ? AND ts <= ? AND reason_code = 'mission_completed'
            """,
            (guild_id, user_id, period_start, period_end),
        )

        mention_targets: set[str] = set()
        mention_count = 0
        for row in mention_rows:
            raw = row["mentions_json"]
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, list):
                for item in payload:
                    target = str(item).strip()
                    if target and target != user_id:
                        mention_targets.add(target)
                        mention_count += 1

        day_counts = [int(r["day_msgs"] or 0) for r in day_rows]
        avg_msgs = (sum(day_counts) / len(day_counts)) if day_counts else 0.0
        variance = (sum((x - avg_msgs) ** 2 for x in day_counts) / len(day_counts)) if day_counts else 0.0
        std_dev = variance ** 0.5
        regularity = max(0.0, min(1.0, 1.0 - (std_dev / (avg_msgs + 1.0)))) if day_counts else 0.0

        return {
            "msg_count": int(totals["msg_count"] or base_metrics.get("msg_count", 0) or 0) if totals else int(base_metrics.get("msg_count", 0) or 0),
            "replies_sent": int(totals["replies_sent"] or 0) if totals else 0,
            "unique_interactions": int(base_metrics.get("unique_interactions", 0) or 0),
            "reply_received": int(base_metrics.get("reply_received", 0) or 0),
            "degrade_events": int(base_metrics.get("degrade_events", 0) or 0),
            "invigorate_events": int(base_metrics.get("invigorate_events", 0) or 0),
            "quality_counter": int(base_metrics.get("quality_counter", 0) or 0),
            "channel_diversity": int(totals["channel_diversity"] or 0) if totals else 0,
            "active_days": int(totals["active_days"] or 0) if totals else 0,
            "first_message_of_day": int(first_msg_days["cnt"] or 0) if first_msg_days else 0,
            "mentions_count": mention_count,
            "mentions_unique_users": len(mention_targets),
            "missions_completed": int(mission_row["completed"] or 0) if mission_row else 0,
            "daily_regularity": round(regularity, 4),
        }

    def _compute_archetype_raw_scores(self, m: dict[str, float | int]) -> dict[str, float]:
        import math

        msg = float(m.get("msg_count", 0) or 0)
        unique = float(m.get("unique_interactions", 0) or 0)
        replies = float(m.get("reply_received", 0) or 0)
        replies_sent = float(m.get("replies_sent", 0) or 0)
        invigorate = float(m.get("invigorate_events", 0) or 0)
        degrade = float(m.get("degrade_events", 0) or 0)
        quality = float(m.get("quality_counter", 0) or 0)
        channels = float(m.get("channel_diversity", 0) or 0)
        first_day = float(m.get("first_message_of_day", 0) or 0)
        mentions = float(m.get("mentions_count", 0) or 0)
        missions = float(m.get("missions_completed", 0) or 0)
        active_days = float(m.get("active_days", 0) or 0)
        regularity = float(m.get("daily_regularity", 0) or 0)

        interactions_per_msg = unique / max(msg, 1.0)
        channels_per_msg = channels / max(msg, 1.0)
        mentions_per_msg = mentions / max(msg, 1.0)
        replies_per_msg = replies_sent / max(msg, 1.0)
        climate_push = invigorate + degrade
        climate_balance = max(0.0, invigorate - degrade)
        monopoly_ratio = max(0.0, (msg - unique) / max(msg, 1.0))
        impact_per_msg = (invigorate * 1.5 + replies + quality + missions * 2.0) / max(msg, 1.0)
        low_presence = max(0.0, 1.0 - min(1.0, msg / 30.0))

        msg_log = math.log1p(msg)
        volume_factor = min(1.0, msg_log / math.log1p(140.0))
        low_relational_diversity = max(0.0, 1.0 - min(1.0, interactions_per_msg * 2.2))
        low_channel_diversity = max(0.0, 1.0 - min(1.0, channels_per_msg * 5.0))
        low_reciprocity = max(0.0, 1.0 - min(1.0, replies_per_msg * 2.4))
        low_quality_density = max(0.0, 1.0 - min(1.0, quality / max(msg * 0.35, 1.0)))
        dominant_behavior_pressure = (
            monopoly_ratio * 0.35
            + low_relational_diversity * 0.2
            + low_channel_diversity * 0.2
            + low_reciprocity * 0.15
            + low_quality_density * 0.1
        )

        return {
            "scintilla": 0.50 * first_day + 0.35 * invigorate + 0.2 * missions + 0.12 * replies,
            "pacificatore": 0.45 * climate_balance + 0.3 * quality + 0.25 * regularity * 10.0 + 0.15 * replies_sent - 0.35 * degrade,
            "agitatore": 0.35 * climate_push + 0.25 * max(0.0, degrade * 2.0 - quality) + 0.2 * first_day + 0.1 * msg,
            "collante": 0.45 * unique + 0.33 * mentions + 0.22 * active_days + 0.2 * replies_sent,
            "mediatore": 0.35 * climate_balance + 0.3 * replies_sent + 0.25 * quality + 0.15 * unique - 0.3 * degrade,
            "esploratore_sociale": 0.4 * unique + 0.4 * channels + 0.2 * mentions,
            "costante": 0.55 * active_days + 0.35 * regularity * 20.0 + 0.1 * min(msg, 50.0),
            "lampo": (impact_per_msg * 20.0) * low_presence + 0.25 * first_day,
            "silenzioso": max(0.0, (22.0 - msg) * 0.8 + active_days * 0.6 - monopoly_ratio * 10.0),
            "ascoltatore": 0.5 * replies_sent + 0.32 * quality + 0.12 * unique + 10.0 * max(0.0, 0.42 - mentions_per_msg),
            "selettivo": max(0.0, (1.0 - min(1.0, interactions_per_msg * 1.7)) * 35.0 + active_days * 0.5 + quality * 0.2),
            # Dominante is intentionally less volume-driven: raw message count is log-smoothed
            # and only becomes strong when monopoly + low distribution behaviours coexist.
            "dominante": 42.0 * volume_factor * dominant_behavior_pressure
            + monopoly_ratio * 10.0
            + low_channel_diversity * 5.0
            + low_relational_diversity * 4.0
            - quality * 0.25,
        }

    def _normalize_archetype_scores(self, raw_scores: dict[str, float]) -> dict[str, int]:
        positive = {k: max(0.0, float(raw_scores.get(k, 0.0) or 0.0)) for k in self.ARCHETYPE_KEYS}
        total = sum(positive.values())
        if total <= 0:
            base = round(100 / len(self.ARCHETYPE_KEYS))
            normalized = {k: base for k in self.ARCHETYPE_KEYS}
            normalized[self.ARCHETYPE_KEYS[0]] += 100 - sum(normalized.values())
            return normalized
        weights = {k: (v / total) * 100 for k, v in positive.items()}
        rounded = {k: int(round(v)) for k, v in weights.items()}
        diff = 100 - sum(rounded.values())
        if diff != 0:
            direction = 1 if diff > 0 else -1
            ranking = sorted(self.ARCHETYPE_KEYS, key=lambda key: weights[key] - rounded[key], reverse=(diff > 0))
            idx = 0
            while diff != 0 and ranking:
                key = ranking[idx % len(ranking)]
                if rounded[key] + direction >= 0:
                    rounded[key] += direction
                    diff -= direction
                idx += 1
        return rounded

    def _build_archetype_debug_reasons(self, metrics: dict[str, float | int], raw_scores: dict[str, float], normalized: dict[str, int]) -> dict[str, str]:
        top_keys = sorted(self.ARCHETYPE_KEYS, key=lambda k: normalized.get(k, 0), reverse=True)[:4]
        base: dict[str, str] = {}
        snippets = {
            "scintilla": "attivi spesso i momenti iniziali della giornata e aumenti il ritmo",
            "pacificatore": "mantieni il clima più costruttivo con buona qualità",
            "agitatore": "muovi molto il clima e alzi l'intensità delle discussioni",
            "collante": "connetti persone diverse con interazioni distribuite",
            "mediatore": "favorisci equilibrio e risposte utili nei confronti",
            "esploratore_sociale": "ti muovi tra più canali e contatti diversi",
            "costante": "hai una presenza regolare su più giorni",
            "lampo": "sei poco presente ma con impatto relativo molto alto",
            "silenzioso": "osservi e partecipi poco, senza occupare troppo spazio",
            "ascoltatore": "intervieni con risposte mirate e tono calmo",
            "selettivo": "concentri le interazioni su pochi contesti in modo mirato",
            "dominante": "occupi una quota ampia dello spazio conversazionale",
        }
        for key in top_keys:
            base[key] = snippets.get(key, "profilo emerso dalle metriche aggregate")
        base["_debug"] = f"msg={int(metrics.get('msg_count', 0) or 0)}, unique={int(metrics.get('unique_interactions', 0) or 0)}, raw_top={sorted(raw_scores.items(), key=lambda kv: kv[1], reverse=True)[:3]}"
        return base
