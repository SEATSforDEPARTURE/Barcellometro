import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.services.aura import ArchetypeAnalyzerService, AuraEligibilityService, AuraMissionService, AuraScoringService, build_discord_jump_link, compute_and_store_aura_result, load_aura_rule_definitions, load_aura_rules, normalize_text_for_matching, render_karma_bar, resolve_aura_reason_label
from app.services.database import DatabaseService
from app.services.entitlements import EntitlementsService
from app.services.barcello_window import resolve_default_window_minutes


class FakeDatabase:
    def __init__(self, *, settings=None, message_count: int = 0):
        self._settings = settings or {}
        self._message_count = message_count

    async def get_setting(self, key: str):
        return self._settings.get(key)

    async def count_user_messages_in_range(self, guild_id: str, user_id: str, start_ts: str, end_ts: str):
        return self._message_count


@dataclass
class FakeRole:
    id: int
    name: str = "member"


@dataclass
class FakePermissions:
    administrator: bool = False


@dataclass
class FakeMember:
    id: int
    roles: list[FakeRole]
    guild_permissions: FakePermissions
    bot: bool = False
    created_at: datetime = datetime.now(timezone.utc) - timedelta(days=90)


def run(coro):
    return asyncio.run(coro)


def test_aura_entitlements_eligibility_gate_and_target_disabled_for_base() -> None:
    policies = {
        "commands": {
            "aura": {
                "profiles": {
                    "base": {
                        "features": {
                            "aura": {
                                "enabled": True,
                                "limits": {"allow_target_user": False},
                                "eligibility": {"min_messages_in_range": 20, "exclude_bots": True},
                            }
                        }
                    }
                }
            }
        }
    }
    settings = {
        "entitlements.policies": json.dumps(policies),
        "entitlements.profile_map": json.dumps({"profiles": {"base": {"priority": 0}}, "role_to_profile": {}}),
        "mod.role_ids": "[]",
    }
    entitlements = EntitlementsService(FakeDatabase(settings=settings))
    member = FakeMember(id=1, roles=[], guild_permissions=FakePermissions())
    aura_cfg = run(entitlements.get_feature_profile_config(member, "aura"))
    assert aura_cfg["eligibility"]["min_messages_in_range"] == 20
    assert aura_cfg["limits"]["allow_target_user"] is False


def test_render_karma_bar_cursor_edges() -> None:
    assert "🔴" in render_karma_bar(0)
    assert render_karma_bar(0).endswith("0%")
    assert render_karma_bar(50).endswith("50%")
    assert render_karma_bar(100).endswith("100%")


def test_eligibility_bots_and_min_messages() -> None:
    policies = {
        "commands": {
            "aura": {
                "profiles": {
                    "base": {
                        "features": {
                            "aura": {
                                "enabled": True,
                                "eligibility": {
                                    "min_account_age_days": 7,
                                    "min_messages_in_range": 20,
                                    "exclude_bots": True,
                                    "exclude_roles": [],
                                    "exclude_if_flagged_fake": True,
                                },
                            }
                        }
                    }
                }
            }
        }
    }
    settings = {
        "entitlements.policies": json.dumps(policies),
        "entitlements.profile_map": json.dumps({"profiles": {"base": {"priority": 0}}, "role_to_profile": {}}),
        "mod.role_ids": "[]",
    }

    db_low = FakeDatabase(settings=settings, message_count=5)
    ent = EntitlementsService(db_low)
    service = AuraEligibilityService(db_low, ent)
    member = FakeMember(id=1, roles=[], guild_permissions=FakePermissions(), bot=False)
    result = run(service.evaluate_member(member, "10", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
    assert result.eligible is False
    assert "almeno 20 messaggi" in result.reason

    db_ok = FakeDatabase(settings=settings, message_count=100)
    ent_ok = EntitlementsService(db_ok)
    service_ok = AuraEligibilityService(db_ok, ent_ok)
    bot_member = FakeMember(id=2, roles=[], guild_permissions=FakePermissions(), bot=True)
    bot_result = run(service_ok.evaluate_member(bot_member, "10", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
    assert bot_result.eligible is False
    assert "bot" in bot_result.reason.lower()


def test_compute_and_store_aura_result_creates_missing_window_row() -> None:
    async def _scenario() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now.replace(hour=0, minute=0)
        end = now.replace(hour=23, minute=59)
        start_ts = start.isoformat()
        end_ts = end.isoformat()

        await db.execute(
            """
            INSERT INTO messages (message_id, guild_id, channel_id, author_id, ts, content, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            ("m1", "10", "99", "1", start_ts, "hello"),
        )
        await db.upsert_aura_rolling_on_message(guild_id="10", user_id="1", window_key=start.date().isoformat(), ts=start_ts, unique_increment=2)

        before = await db.fetch_latest_aura_result("10", "1", start_ts, end_ts, channel_id=None)
        assert before is None

        await compute_and_store_aura_result(db, guild_id="10", user_id="1", start_ts=start_ts, end_ts=end_ts, channel_id=None)

        after = await db.fetch_latest_aura_result("10", "1", start_ts, end_ts, channel_id=None)
        assert after is not None
        assert int(after["karma_percent"]) >= 0
        await db.close()

    run(_scenario())


def test_resolve_default_window_minutes_matches_overrides() -> None:
    trigger = {"channel_overrides": {"99": {"window_minutes": 45}}}
    assert resolve_default_window_minutes("99", "30", trigger) == 45
    assert resolve_default_window_minutes("100", "30", trigger) == 30
    assert resolve_default_window_minutes("100", "bad", trigger) == 30


def test_aura_entitlements_target_enabled_for_mod() -> None:
    policies = {
        "commands": {
            "aura": {
                "profiles": {
                    "base": {"features": {"aura": {"enabled": True, "limits": {"allow_target_user": False}}}},
                    "mod": {"features": {"aura": {"enabled": True, "limits": {"allow_target_user": True}}}},
                }
            }
        }
    }
    settings = {
        "entitlements.policies": json.dumps(policies),
        "entitlements.profile_map": json.dumps({"profiles": {"base": {"priority": 0}}, "role_to_profile": {}}),
        "mod.role_ids": "[]",
    }
    entitlements = EntitlementsService(FakeDatabase(settings=settings))
    mod_member = FakeMember(id=99, roles=[], guild_permissions=FakePermissions(administrator=True))
    aura_cfg = run(entitlements.get_feature_profile_config(mod_member, "aura"))
    assert aura_cfg["limits"]["allow_target_user"] is True




class FakeLedgerDB:
    def __init__(self) -> None:
        self.events = []
        self.missions = []

    async def insert_aura_ledger_event(self, guild_id, user_id, channel_id, ts, reason_code, delta_points, meta, *, event_id=None):
        self.events.append({
            "id": event_id or f"id-{len(self.events)+1}",
            "guild_id": guild_id,
            "user_id": user_id,
            "channel_id": channel_id,
            "ts": ts,
            "reason_code": reason_code,
            "delta_points": delta_points,
            "meta": meta,
        })
        return self.events[-1]["id"]

    async def aura_ledger_event_already_recorded(self, *, guild_id, user_id, reason_code, message_id, source_event, mission_id=None):
        for ev in self.events:
            meta = ev.get("meta", {})
            if ev.get("guild_id") != guild_id or ev.get("user_id") != user_id:
                continue
            if ev.get("reason_code") != reason_code:
                continue
            if str(meta.get("message_id") or "") != str(message_id):
                continue
            if str(meta.get("source_event") or "") != str(source_event):
                continue
            if mission_id is not None and str(meta.get("mission_id") or "") != str(mission_id):
                continue
            return True
        return False

    async def list_aura_missions_for_user(self, guild_id, user_id, start_ts, end_ts):
        return self.missions

    async def complete_aura_mission(self, **kwargs):
        self.completed = kwargs

    async def count_guild_good_morning_before(self, guild_id, day_iso, before_ts, keywords):
        return 0


def test_aura_scoring_service_records_positive_and_negative_deltas() -> None:
    async def _scenario() -> None:
        db = FakeLedgerDB()
        scoring = AuraScoringService(db)  # type: ignore[arg-type]
        ts = datetime.now(timezone.utc).isoformat()
        await scoring.award_points(guild_id="10", user_id="1", reason_code="first_message_of_day", ts=ts, channel_id="99")
        await scoring.penalize_points(guild_id="10", user_id="1", reason_code="climate_degrade", ts=ts, channel_id="99")
        assert len(db.events) == 2
        deltas = sorted(int(x["delta_points"]) for x in db.events)
        assert deltas[0] < 0
        assert deltas[1] > 0
        assert db.events[0]["meta"]["reason_human"]

    run(_scenario())


def test_load_aura_rules_contains_extended_reason_codes() -> None:
    rules = load_aura_rules()
    assert "first_message_of_day" in rules
    assert "cross_user_interaction" in rules


def test_normalize_text_for_matching_good_morning_variants() -> None:
    out = normalize_text_for_matching("Buongiornooooo a tuttI!!!")
    assert "buongiorno" in out


def test_mission_good_morning_completes_without_single_mission_reward(monkeypatch) -> None:
    async def _scenario() -> None:
        db = FakeLedgerDB()
        db.missions = [
            {
                "mission_id": "good_morning",
                "assigned_at": "2026-03-07T07:00:00+00:00",
                "status": "assigned",
                "reward_points": 12,
                "meta": {"label": "Dai il buongiorno per prima."},
            }
        ]
        scoring = AuraScoringService(db)  # type: ignore[arg-type]
        service = AuraMissionService(db, scoring)  # type: ignore[arg-type]

        def _fake_cfg():
            return {"good_morning": {"start_hour": 5, "end_hour": 11, "keywords": ["buongiorno"]}}

        monkeypatch.setattr("app.services.aura.load_aura_missions_config", _fake_cfg)

        done = await service.process_message_for_missions(
            guild_id="10",
            user_id="1",
            channel_id="99",
            message_id="m1",
            ts="2026-03-07T08:00:00+00:00",
            content="Buongiornooooo raga",
            mentions=[],
        )
        assert "good_morning" in done
        assert len(db.events) == 1
        assert all(ev["reason_code"] == "mission_completed" for ev in db.events)

    run(_scenario())


def test_archetype_analyzer_normalizes_scores_to_100() -> None:
    service = ArchetypeAnalyzerService(database=None, bot=None, eligibility_service=None)  # type: ignore[arg-type]
    raw = {k: float(idx + 1) for idx, k in enumerate(service.ARCHETYPE_KEYS)}
    normalized = service._normalize_archetype_scores(raw)
    assert sum(normalized.values()) == 100
    assert set(normalized.keys()) == set(service.ARCHETYPE_KEYS)


def test_archetype_analyzer_computes_multiscore_12_archetypes() -> None:
    service = ArchetypeAnalyzerService(database=None, bot=None, eligibility_service=None)  # type: ignore[arg-type]
    metrics = {
        "msg_count": 42,
        "unique_interactions": 16,
        "reply_received": 12,
        "replies_sent": 15,
        "invigorate_events": 6,
        "degrade_events": 2,
        "quality_counter": 11,
        "channel_diversity": 7,
        "first_message_of_day": 4,
        "mentions_count": 10,
        "missions_completed": 3,
        "active_days": 18,
        "daily_regularity": 0.82,
    }
    raw = service._compute_archetype_raw_scores(metrics)
    assert len(raw) == 12
    assert raw["collante"] > 0
    assert raw["esploratore_sociale"] > 0
    assert raw["costante"] > 0


def test_load_aura_rule_definitions_supports_number_and_object(monkeypatch) -> None:
    def _fake_loader(path: str):
        if path.endswith("aura_rules.json"):
            return {
                "first_message_of_day": 7,
                "good_morning_first": {
                    "points": 12,
                    "label_user": "per aver dato il buongiorno per prima",
                    "label_mod": "buongiorno per prima nel server",
                    "category": "missione_sociale",
                    "sign": "positive",
                    "enabled": True,
                },
            }
        return {}

    monkeypatch.setattr("app.services.aura.load_json_file", _fake_loader)
    defs = load_aura_rule_definitions()
    assert defs["first_message_of_day"].points == 7
    assert defs["good_morning_first"].points == 12
    assert defs["good_morning_first"].label_user.startswith("per aver dato")


def test_single_mission_completion_does_not_assign_reward_points(monkeypatch) -> None:
    async def _scenario() -> None:
        db = FakeLedgerDB()
        db.missions = [
            {
                "mission_id": "good_morning",
                "assigned_at": "2026-03-07T07:00:00+00:00",
                "status": "assigned",
                "reward_points": 12,
                "meta": {"label": "Dai il buongiorno per prima."},
            },
            {
                "mission_id": "talk_new_user",
                "assigned_at": "2026-03-07T07:01:00+00:00",
                "status": "assigned",
                "reward_points": 8,
                "meta": {"label": "Talk"},
            },
        ]
        scoring = AuraScoringService(db)  # type: ignore[arg-type]
        service = AuraMissionService(db, scoring)  # type: ignore[arg-type]

        monkeypatch.setattr("app.services.aura.load_aura_missions_config", lambda: {"good_morning": {"start_hour": 5, "end_hour": 11, "keywords": ["buongiorno"]}})

        done = await service.process_message_for_missions(
            guild_id="10",
            user_id="1",
            channel_id="99",
            message_id="m1",
            ts="2026-03-07T08:00:00+00:00",
            content="Buongiornooooo raga",
            mentions=[],
        )
        assert "good_morning" in done
        assert all(e["reason_code"] != "good_morning_first" for e in db.events)
        assert all(e["reason_code"] != "mission_task_reward" for e in db.events)
        assert all(e["reason_code"] != "mission_completed" for e in db.events)

    run(_scenario())


def test_resolve_aura_reason_label_and_jump_link_fallback() -> None:
    label = resolve_aura_reason_label("unknown.reason", audience="user")
    assert "unknown.reason" in label
    assert resolve_aura_reason_label("mission_completed", audience="mod")
    assert build_discord_jump_link("1", "2", "3") == "https://discord.com/channels/1/2/3"
    assert build_discord_jump_link("1", None, "3") is None


def test_two_different_events_same_message_do_not_collide() -> None:
    async def _scenario() -> None:
        db = FakeLedgerDB()
        scoring = AuraScoringService(db)  # type: ignore[arg-type]
        ts = "2026-03-07T08:00:00+00:00"
        await scoring.apply_rule(
            guild_id="10",
            user_id="1",
            rule_code="mission_completed",
            ts=ts,
            channel_id="99",
            message_id="m42",
            source_service="mission",
            source_event="mission.completed",
            meta={"mission_id": "good_morning"},
        )
        await scoring.award_points(
            guild_id="10",
            user_id="1",
            reason_code="good_morning_first",
            ts=ts,
            channel_id="99",
            points=12,
            message_id="m42",
            source_service="mission",
            source_event="mission.reward",
            meta={"mission_id": "good_morning"},
        )
        assert len(db.events) == 2
        assert db.events[0]["id"] != db.events[1]["id"]

    run(_scenario())


def test_same_event_duplicate_not_recorded_twice_logically() -> None:
    async def _scenario() -> None:
        db = FakeLedgerDB()
        scoring = AuraScoringService(db)  # type: ignore[arg-type]
        ts = "2026-03-07T08:00:00+00:00"
        kwargs = {
            "guild_id": "10",
            "user_id": "1",
            "rule_code": "mission_completed",
            "ts": ts,
            "channel_id": "99",
            "message_id": "m77",
            "source_service": "mission",
            "source_event": "mission.completed",
            "meta": {"mission_id": "good_morning"},
        }
        await scoring.apply_rule(**kwargs)
        await scoring.apply_rule(**kwargs)
        events = [e for e in db.events if e["reason_code"] == "mission_completed"]
        assert len(events) == 1

    run(_scenario())


def test_database_insert_aura_ledger_event_generates_unique_ids() -> None:
    async def _scenario() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        ts = "2026-03-07T08:00:00+00:00"
        id1 = await db.insert_aura_ledger_event("10", "1", "99", ts, "mission_completed", 15, {"message_id": "m1", "source_event": "mission.completed"})
        id2 = await db.insert_aura_ledger_event("10", "1", "99", ts, "good_morning_first", 12, {"message_id": "m1", "source_event": "mission.reward"})
        assert id1 != id2
        rows = await db.fetchall("SELECT COUNT(*) AS cnt FROM aura_events_ledger")
        assert int(rows[0]["cnt"] or 0) == 2
        await db.close()

    run(_scenario())


def test_channel_scoped_aura_report_filters_by_channel() -> None:
    async def _scenario() -> None:
        db = DatabaseService(":memory:")
        await db.connect()
        await db.initialize_schema()
        ts = "2026-01-02T10:00:00+00:00"
        await db.insert_aura_ledger_event("1", "u1", "c1", ts, "mission_completed", 15, {})
        await db.insert_aura_ledger_event("1", "u2", "c2", ts, "mission_completed", 20, {})

        report = await db.fetch_aura_channel_ledger_report("1", "c1", "2026-01-02T00:00:00+00:00", "2026-01-02T23:59:59+00:00")
        top = await db.fetch_aura_channel_top_users("1", "c1", "2026-01-02T00:00:00+00:00", "2026-01-02T23:59:59+00:00")

        assert report["totals"]["positive"] == 15
        assert report["totals"]["users_count"] == 1
        assert [r["user_id"] for r in top] == ["u1"]
        await db.close()

    run(_scenario())


def test_mission_completed_only_after_all_assigned_done(monkeypatch) -> None:
    async def _scenario() -> None:
        db = FakeLedgerDB()
        db.missions = [
            {
                "mission_id": "talk_new_user",
                "assigned_at": "2026-03-07T07:00:00+00:00",
                "status": "assigned",
                "reward_points": 8,
                "meta": {"label": "Talk"},
            },
            {
                "mission_id": "balanced_participation",
                "assigned_at": "2026-03-07T07:01:00+00:00",
                "status": "assigned",
                "reward_points": 11,
                "meta": {"label": "Balanced"},
            },
        ]

        async def _complete(**kwargs):
            mid = kwargs["mission_id"]
            for m in db.missions:
                if m["mission_id"] == mid:
                    m["status"] = "completed"

        db.complete_aura_mission = _complete  # type: ignore[method-assign]
        scoring = AuraScoringService(db)  # type: ignore[arg-type]
        service = AuraMissionService(db, scoring)  # type: ignore[arg-type]

        monkeypatch.setattr(
            "app.services.aura.load_aura_missions_config",
            lambda: {"missions": [{"id": "talk_new_user"}, {"id": "balanced_participation"}]},
        )

        done_first = await service.process_message_for_missions(
            guild_id="10",
            user_id="1",
            channel_id="99",
            message_id="m1",
            ts="2026-03-07T10:00:00+00:00",
            content="ciao",
            mentions=["2"],
        )
        assert "talk_new_user" in done_first
        assert all(ev["reason_code"] != "mission_completed" for ev in db.events)

        done_second = await service.process_message_for_missions(
            guild_id="10",
            user_id="1",
            channel_id="99",
            message_id="m2",
            ts="2026-03-07T10:05:00+00:00",
            content="ancora",
            mentions=["2"],
        )
        assert "balanced_participation" in done_second
        mission_completed_events = [ev for ev in db.events if ev["reason_code"] == "mission_completed"]
        assert len(mission_completed_events) == 1

        await service.process_message_for_missions(
            guild_id="10",
            user_id="1",
            channel_id="99",
            message_id="m3",
            ts="2026-03-07T10:10:00+00:00",
            content="ancora",
            mentions=["2"],
        )
        mission_completed_events_again = [ev for ev in db.events if ev["reason_code"] == "mission_completed"]
        assert len(mission_completed_events_again) == 1

    run(_scenario())


def test_archetype_dominante_not_for_high_volume_with_high_diversity() -> None:
    service = ArchetypeAnalyzerService(database=None, bot=None, eligibility_service=None)  # type: ignore[arg-type]
    metrics = {
        "msg_count": 120,
        "unique_interactions": 85,
        "reply_received": 24,
        "replies_sent": 42,
        "invigorate_events": 12,
        "degrade_events": 2,
        "quality_counter": 30,
        "channel_diversity": 18,
        "first_message_of_day": 2,
        "mentions_count": 30,
        "missions_completed": 4,
        "active_days": 36,
        "daily_regularity": 0.8,
    }
    raw = service._compute_archetype_raw_scores(metrics)
    assert raw["dominante"] < raw["collante"]
    assert raw["dominante"] < raw["esploratore_sociale"]


def test_archetype_dominante_for_high_volume_monopoly_low_distribution() -> None:
    service = ArchetypeAnalyzerService(database=None, bot=None, eligibility_service=None)  # type: ignore[arg-type]
    metrics = {
        "msg_count": 130,
        "unique_interactions": 12,
        "reply_received": 10,
        "replies_sent": 8,
        "invigorate_events": 10,
        "degrade_events": 3,
        "quality_counter": 4,
        "channel_diversity": 2,
        "first_message_of_day": 3,
        "mentions_count": 5,
        "missions_completed": 1,
        "active_days": 26,
        "daily_regularity": 0.55,
    }
    raw = service._compute_archetype_raw_scores(metrics)
    top = max(raw, key=raw.get)
    assert top == "dominante"


def test_archetype_costante_emerges_on_regular_presence() -> None:
    service = ArchetypeAnalyzerService(database=None, bot=None, eligibility_service=None)  # type: ignore[arg-type]
    metrics = {
        "msg_count": 58,
        "unique_interactions": 20,
        "reply_received": 14,
        "replies_sent": 20,
        "invigorate_events": 5,
        "degrade_events": 1,
        "quality_counter": 10,
        "channel_diversity": 8,
        "first_message_of_day": 2,
        "mentions_count": 12,
        "missions_completed": 3,
        "active_days": 45,
        "daily_regularity": 0.93,
    }
    raw = service._compute_archetype_raw_scores(metrics)
    assert raw["costante"] > raw["dominante"]


def test_archetype_lampo_can_emerge_with_low_volume_high_impact() -> None:
    service = ArchetypeAnalyzerService(database=None, bot=None, eligibility_service=None)  # type: ignore[arg-type]
    metrics = {
        "msg_count": 8,
        "unique_interactions": 5,
        "reply_received": 11,
        "replies_sent": 4,
        "invigorate_events": 4,
        "degrade_events": 0,
        "quality_counter": 8,
        "channel_diversity": 3,
        "first_message_of_day": 2,
        "mentions_count": 3,
        "missions_completed": 1,
        "active_days": 5,
        "daily_regularity": 0.5,
    }
    raw = service._compute_archetype_raw_scores(metrics)
    assert raw["lampo"] > raw["dominante"]
