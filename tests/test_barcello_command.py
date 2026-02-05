import asyncio

from app.plugins.commands import _handle_barcello_command


class FakeUser:
    def __init__(self) -> None:
        self.sent_messages: list[str] = []

    async def send(self, message: str) -> None:
        self.sent_messages.append(message)


class FakeResponse:
    def __init__(self) -> None:
        self._done = False
        self.messages: list[str] = []

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, message: str, ephemeral: bool = False) -> None:
        self._done = True
        self.messages.append(message)


class FakeFollowup:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    async def send(self, message: str, ephemeral: bool = False) -> None:
        self._response.messages.append(message)


class FakeInteraction:
    def __init__(self) -> None:
        self.user = FakeUser()
        self.guild_id = 123
        self.channel_id = 456
        self.response = FakeResponse()
        self.followup = FakeFollowup(self.response)


class FakeEntitlements:
    def __init__(self, profile: str, config: dict, ai_allowed: bool = False) -> None:
        self._profile = profile
        self._config = config
        self._ai_allowed = ai_allowed

    async def get_command_profile_config(self, member, command: str) -> dict:
        return self._config

    async def resolve_profile(self, member) -> str:
        return self._profile

    async def is_feature_allowed(self, member, feature: str) -> bool:
        return self._ai_allowed


class FakeBarcelloResult:
    def __init__(self) -> None:
        self.score = 70
        self.color = "verde"
        self.window_start_ts = "2024-01-01T00:00:00+00:00"
        self.window_end_ts = "2024-01-01T00:30:00+00:00"
        self.reasons = [{"label": "Toni negativi", "summary": "2 hit"}]
        self.metrics = {"message_count": 10, "msg_per_min": 1.2}
        self.trend = {"direction": "stable", "delta": 0}
        self.advice = ["Rallentare il ritmo."]


class FakeBarcelloService:
    def __init__(self) -> None:
        self.calls = 0

    async def compute_channel(self, *args, **kwargs):
        self.calls += 1
        return FakeBarcelloResult()


class FakeDatabase:
    async def get_setting(self, key: str):
        return None


def run(coro):
    return asyncio.run(coro)


def test_barcello_denied_sends_dm_and_skips_compute() -> None:
    interaction = FakeInteraction()
    barcello = FakeBarcelloService()
    entitlements = FakeEntitlements(
        "base",
        {"allowed": False, "messages": {"dm_text": "Serve PLUS."}, "output": {}},
    )

    async def check_permission(*args, **kwargs):
        return True

    run(
        _handle_barcello_command(
            interaction,
            barcello=barcello,
            entitlements=entitlements,
            ai_service=None,
            database=FakeDatabase(),
            check_permission=check_permission,
            window_minutes=None,
        )
    )

    assert barcello.calls == 0
    assert interaction.user.sent_messages == ["Serve PLUS."]
    assert interaction.response.messages[-1] == "Ti ho inviato un DM"


def test_barcello_footer_without_trend_or_advice() -> None:
    interaction = FakeInteraction()
    barcello = FakeBarcelloService()
    entitlements = FakeEntitlements(
        "role1",
        {
            "allowed": True,
            "output": {"show_score": True, "show_motivation": True, "show_trend": False, "show_advice": False},
            "messages": {"footer_text": "Passa a PRO per trend."},
        },
    )

    async def check_permission(*args, **kwargs):
        return True

    run(
        _handle_barcello_command(
            interaction,
            barcello=barcello,
            entitlements=entitlements,
            ai_service=None,
            database=FakeDatabase(),
            check_permission=check_permission,
            window_minutes=30,
        )
    )

    dm_text = interaction.user.sent_messages[-1]
    assert "Passa a PRO per trend." in dm_text
    assert "Trend:" not in dm_text
    assert "Consigli:" not in dm_text


def test_barcello_metrics_only_for_mod() -> None:
    barcello = FakeBarcelloService()

    async def check_permission(*args, **kwargs):
        return True

    mod_interaction = FakeInteraction()
    mod_entitlements = FakeEntitlements(
        "mod",
        {
            "allowed": True,
            "output": {"show_score": True, "show_mod_metrics": True},
            "messages": {},
        },
    )
    run(
        _handle_barcello_command(
            mod_interaction,
            barcello=barcello,
            entitlements=mod_entitlements,
            ai_service=None,
            database=FakeDatabase(),
            check_permission=check_permission,
            window_minutes=30,
        )
    )
    assert "Metriche:" in mod_interaction.user.sent_messages[-1]

    base_interaction = FakeInteraction()
    base_entitlements = FakeEntitlements(
        "base",
        {
            "allowed": True,
            "output": {"show_score": True, "show_mod_metrics": True},
            "messages": {},
        },
    )
    run(
        _handle_barcello_command(
            base_interaction,
            barcello=barcello,
            entitlements=base_entitlements,
            ai_service=None,
            database=FakeDatabase(),
            check_permission=check_permission,
            window_minutes=30,
        )
    )
    assert "Metriche:" not in base_interaction.user.sent_messages[-1]
