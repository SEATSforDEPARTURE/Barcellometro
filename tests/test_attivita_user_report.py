from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord
import pytest

from tests._embed_test_utils import primary_field


@pytest.fixture
def attivita_module(import_fresh):
    return import_fresh("app.plugins.commands_modular.attivita")


def _msg(ts: str, channel_id: str, message_id: str, *, content: str = "", reply_to: str | None = None, mentions_json: str | None = None):
    return {
        "ts": ts,
        "channel_id": channel_id,
        "message_id": message_id,
        "content": content,
        "reply_to_message_id": reply_to,
        "mentions_json": mentions_json,
    }


def test_peak_day_vs_hour(attivita_module) -> None:
    multi = [_msg("2026-02-20T10:00:00+00:00", "10", "1"), _msg("2026-02-20T11:00:00+00:00", "10", "2"), _msg("2026-02-21T11:00:00+00:00", "11", "3")]
    label_day, channel_day, _ = attivita_module._compute_peak(multi, True)
    assert label_day.startswith("20/02")
    assert channel_day == "10"

    single = [_msg("2026-02-20T10:00:00+00:00", "10", "1"), _msg("2026-02-20T10:10:00+00:00", "10", "2"), _msg("2026-02-20T11:00:00+00:00", "11", "3")]
    label_hour, channel_hour, _ = attivita_module._compute_peak(single, False)
    assert label_hour.startswith("11:00") or label_hour.startswith("10:00")
    assert channel_hour == "10"


def test_silent_hour(attivita_module) -> None:
    messages = [_msg("2026-02-20T10:00:00+00:00", "10", "1"), _msg("2026-02-20T10:30:00+00:00", "10", "2")]
    assert attivita_module._silent_hour(messages) == "00:00"


def test_interactions_reply_and_mentions(attivita_module) -> None:
    messages = [
        _msg("2026-02-20T10:00:00+00:00", "10", "1", content="ciao <@2>", mentions_json='["2"]'),
        _msg("2026-02-20T10:10:00+00:00", "10", "2", content="ciao <@2>", mentions_json='["2"]'),
        _msg("2026-02-20T10:20:00+00:00", "11", "3", reply_to="ref-1"),
        _msg("2026-02-20T10:30:00+00:00", "11", "4", reply_to="missing"),
    ]
    interactions = attivita_module._build_interactions(messages, {"ref-1": 2}, bot_ids=set(), self_id=1)
    assert interactions[2]["count"] == 3
    assert interactions[2]["channels"]["10"] == 2
    assert interactions[2]["channels"]["11"] == 1


def test_interactions_format_only_top_bullets(attivita_module) -> None:
    interactions = {10: {"count": 8, "channels": {}}, 11: {"count": 4, "channels": {}}, 12: {"count": 2, "channels": {}}}
    text = attivita_module._format_interactions(interactions)
    assert "• **8 msg** → <@10>" in text
    assert "\n" in text
    assert "in #" not in text


def test_words_and_themes_filter_functional_words(attivita_module) -> None:
    messages = [
        _msg("2026-02-20T10:00:00+00:00", "10", "1", content="Dalla chat era tutto ok però progetto backend deploy"),
        _msg("2026-02-20T10:10:00+00:00", "10", "2", content="Backend deploy fix performance"),
    ]
    themes, words = attivita_module._words_and_themes(messages)
    joined = " ".join(words).lower()
    assert "dalla" not in joined
    assert "pero" not in joined
    assert "performance" in joined
    assert len(themes) <= 5 and len(words) <= 10


def test_fmt_channel_compact_no_server_prefix(attivita_module) -> None:
    class _Ch:
        id = 55
        name = "salottino"
        type = "text"

    class _GuildMock:
        def get_channel(self, channel_id: int):
            return _Ch() if channel_id == 55 else None

    assert attivita_module.fmt_channel_compact(_GuildMock(), "55") == "#salottino"


def test_split_chunks_stays_under_1024(attivita_module) -> None:
    text = "\n".join(["x" * 300 for _ in range(10)])
    chunks = attivita_module._split_chunks(text, 1024)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 1024 for chunk in chunks)


def test_add_field_safe_creates_continuation(attivita_module) -> None:
    embed = discord.Embed(title="t")
    attivita_module.add_field_safe(embed, name="N", value="\n".join(["x" * 300 for _ in range(10)]))
    assert len(embed.fields) >= 2
    assert "(CONT.)" in embed.fields[1].name
    assert all(len(f.value) <= 1024 for f in embed.fields)


def test_long_embed_triggers_txt_fallback_flag(attivita_module) -> None:
    huge_stats = [f"• Riga {i}: " + ("x" * 300) for i in range(40)]
    embeds, fallback = attivita_module._build_user_activity_embeds_safe(
        display_name="User",
        period_label="Ultimi 30 giorni",
        emoji="🟡",
        label="MEDIOCRE",
        score=55,
        trend_text="Messaggi stabile (+0% vs finestra precedente).",
        stats_lines=huge_stats,
        interaction_lines=["• top", "• bottom"],
        topics_lines=["• temi", "• parole"],
        advice_lines=["a", "b", "c", "d"],
    )
    assert fallback is True
    assert len(embeds) == 2
    assert attivita_module.embed_total_len(embeds[0]) <= 6000
    assert attivita_module.embed_total_len(embeds[1]) <= 6000


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

    def is_done(self) -> bool:
        return self.payload is not None

    async def send_message(self, content: str | None = None, embed: discord.Embed | None = None, ephemeral: bool = False, **kwargs):
        self.payload = {"content": content, "embed": embed, "ephemeral": ephemeral, **kwargs}


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


def test_dm_forbidden_fallback(attivita_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allowed(*args, **kwargs):
        return True

    monkeypatch.setattr(attivita_module, "check_permission", _allowed)
    group = discord.app_commands.Group(name="attivita", description="x")
    ctx = SimpleNamespace(
        config=SimpleNamespace(MAX_ULTIMI_MINUTI=60, MAX_ULTIMI_ORE=24, MAX_ULTIMI_GIORNI=30, MAX_ULTIMI_SETTIMANE=8),
        activity_insights=_ActivityInsights(),
        footer=None,
    )
    attivita_module.register_attivita(group, ctx)
    cmd = next(c for c in group.commands if c.name == "oggi")
    interaction = _Interaction()
    asyncio.run(cmd.callback(interaction))
    payload = interaction.response.payload
    assert payload is not None
    assert payload["ephemeral"] is True
    assert payload["content"] is None
    assert payload["embed"] is not None
    warning_field = primary_field(payload["embed"])
    assert warning_field.name == "❌ __**ERROR**__"
    assert "Non posso inviarti DM. Abilita i DM dal server e riprova." in warning_field.value


class _NoopUser:
    async def send(self, *args, **kwargs):
        return None


def test_attivita_ultimi_validation_uses_standard_embed(attivita_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allowed(*args, **kwargs):
        return True

    monkeypatch.setattr(attivita_module, "check_permission", _allowed)
    group = discord.app_commands.Group(name="attivita", description="x")
    ctx = SimpleNamespace(
        config=SimpleNamespace(MAX_ULTIMI_MINUTI=60, MAX_ULTIMI_ORE=24, MAX_ULTIMI_GIORNI=30, MAX_ULTIMI_SETTIMANE=8),
        activity_insights=_ActivityInsights(),
        footer=None,
    )
    attivita_module.register_attivita(group, ctx)
    cmd = next(c for c in group.commands if c.name == "ultimi")
    interaction = _Interaction()
    interaction.user = _NoopUser()
    interaction.command = cmd
    asyncio.run(cmd.callback(interaction, 0, discord.app_commands.Choice(name="giorni", value="giorni")))
    payload = interaction.response.payload
    assert payload is not None
    assert payload["embed"] is not None
    embed = payload["embed"]
    assert "ULTIMI 0 GIORNI" in (embed.title or "")
    assert "ATTIVITA" not in (embed.title or "")
    assert getattr(embed.author, "name", "").upper().startswith("SERVIZIO ")
    info_field = primary_field(embed)
    assert info_field.name == "❌ __**ERROR**__"
    assert payload["content"] is None


def test_attivita_ultimi_dm_status_keeps_runtime_window_in_subtitle(attivita_module, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _allowed(*args, **kwargs):
        return True

    monkeypatch.setattr(attivita_module, "check_permission", _allowed)
    group = discord.app_commands.Group(name="attivita", description="x")
    ctx = SimpleNamespace(
        config=SimpleNamespace(MAX_ULTIMI_MINUTI=60, MAX_ULTIMI_ORE=24, MAX_ULTIMI_GIORNI=30, MAX_ULTIMI_SETTIMANE=8),
        activity_insights=_ActivityInsights(),
        footer=None,
    )
    attivita_module.register_attivita(group, ctx)
    cmd = next(c for c in group.commands if c.name == "ultimi")
    interaction = _Interaction()
    interaction.user = _NoopUser()
    interaction.command = cmd
    asyncio.run(cmd.callback(interaction, 7, discord.app_commands.Choice(name="giorni", value="giorni")))
    payload = interaction.response.payload

    assert payload is not None
    embed = payload["embed"]
    assert "ULTIMI 7 GIORNI" in (embed.title or "")
    assert "ATTIVITA" not in (embed.title or "")
    assert getattr(embed.author, "name", "").upper().startswith("SERVIZIO ")
    info_field = primary_field(embed)
    assert info_field.name == "✅ __**OK**__"
