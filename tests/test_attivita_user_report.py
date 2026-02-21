from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import discord
import asyncio

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Row=dict, Connection=object)
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)


MODULE_PATH = Path(__file__).resolve().parents[1] / "app/plugins/commands_modular/attivita.py"
spec = importlib.util.spec_from_file_location("attivita_module", MODULE_PATH)
attivita_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(attivita_module)

_build_interactions = attivita_module._build_interactions
_compute_peak = attivita_module._compute_peak
_silent_hour = attivita_module._silent_hour
register_attivita = attivita_module.register_attivita


def _msg(ts: str, channel_id: str, message_id: str, *, content: str = "", reply_to: str | None = None, mentions_json: str | None = None):
    return {
        "ts": ts,
        "channel_id": channel_id,
        "message_id": message_id,
        "content": content,
        "reply_to_message_id": reply_to,
        "mentions_json": mentions_json,
    }


def test_peak_day_vs_hour() -> None:
    multi = [_msg("2026-02-20T10:00:00+00:00", "10", "1"), _msg("2026-02-20T11:00:00+00:00", "10", "2"), _msg("2026-02-21T11:00:00+00:00", "11", "3")]
    label_day, channel_day, _ = _compute_peak(multi, True)
    assert label_day.startswith("20/02")
    assert channel_day == "10"

    single = [_msg("2026-02-20T10:00:00+00:00", "10", "1"), _msg("2026-02-20T10:10:00+00:00", "10", "2"), _msg("2026-02-20T11:00:00+00:00", "11", "3")]
    label_hour, channel_hour, _ = _compute_peak(single, False)
    assert label_hour.startswith("11:00") or label_hour.startswith("10:00")
    assert channel_hour == "10"


def test_silent_hour() -> None:
    messages = [_msg("2026-02-20T10:00:00+00:00", "10", "1"), _msg("2026-02-20T10:30:00+00:00", "10", "2")]
    assert _silent_hour(messages) == "00:00"


def test_interactions_reply_and_mentions() -> None:
    messages = [
        _msg("2026-02-20T10:00:00+00:00", "10", "1", content="ciao <@2>", mentions_json='["2"]'),
        _msg("2026-02-20T10:10:00+00:00", "10", "2", content="ciao <@2>", mentions_json='["2"]'),
        _msg("2026-02-20T10:20:00+00:00", "11", "3", reply_to="ref-1"),
        _msg("2026-02-20T10:30:00+00:00", "11", "4", reply_to="missing"),
    ]
    interactions = _build_interactions(messages, {"ref-1": 2}, bot_ids=set(), self_id=1)
    assert interactions[2]["count"] == 3
    assert interactions[2]["channels"]["10"] == 2
    assert interactions[2]["channels"]["11"] == 1


class _Perms:
    view_channel = True


class _Channel:
    id = 10
    name = "generale"

    def permissions_for(self, _member):
        return _Perms()


class _Member:
    def __init__(self, mid: int, bot: bool = False) -> None:
        self.id = mid
        self.bot = bot


class _Guild:
    id = 123
    name = "Guild"

    def __init__(self) -> None:
        self.members = [_Member(1), _Member(2, bot=True)]


class _ActivityInsights:
    async def compute_activity_for_channel(self, *args, **kwargs):
        from app.services.activity_insights import ActivityScore, ChannelActivityDetails

        return ChannelActivityDetails(
            score=ActivityScore(1, 1, 10, 1, 60, "🟡", "MEDIOCRE", "Trend"),
            top_active_users=[],
            inactive_users=[],
            advice_bullets=[],
            stats_lines=[],
            range_spans_multiple_days=False,
            candidates_total=1,
        )


class _Response:
    def __init__(self) -> None:
        self.payload = None

    async def send_message(self, content: str, ephemeral: bool = False):
        self.payload = (content, ephemeral)


class _DummyResp:
    status = 403
    reason = "Forbidden"
    text = "closed"


class _User:
    async def send(self, *args, **kwargs):
        raise discord.Forbidden(response=_DummyResp(), message="closed")


class _Interaction:
    guild_id = 123
    channel_id = 10

    def __init__(self) -> None:
        self.guild = _Guild()
        self.channel = _Channel()
        self.user = _User()
        self.response = _Response()


def test_dm_forbidden_fallback(monkeypatch) -> None:
    async def _allowed(*args, **kwargs):
        return True

    monkeypatch.setattr(attivita_module, "check_permission", _allowed)
    group = discord.app_commands.Group(name="attivita", description="x")
    ctx = types.SimpleNamespace(
        config=types.SimpleNamespace(MAX_ULTIMI_MINUTI=60, MAX_ULTIMI_ORE=24, MAX_ULTIMI_GIORNI=30, MAX_ULTIMI_SETTIMANE=8),
        activity_insights=_ActivityInsights(),
    )
    register_attivita(group, ctx)
    cmd = next(c for c in group.commands if c.name == "oggi")
    interaction = _Interaction()
    asyncio.run(cmd.callback(interaction))
    assert interaction.response.payload == ("❌ Non posso inviarti DM. Abilita i DM dal server e riprova.", True)
