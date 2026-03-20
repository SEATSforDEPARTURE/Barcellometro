import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Connection=object)

from app.plugins.commands_modular.riassunto import _build_period_prefix, _summary_footer_inputs
from app.renderers.channel_summary import _barcello_emoji_from_color, _bold_known_names
from app.renderers.detail_embeds import build_summary_detail_embeds
from app.services.barcello_service import BarcelloResult
from app.services.content_summary_service import (
    SummaryItem,
    SummaryResult,
    _build_summary_prompt_payload,
    _estimate_summary_prompt_tokens,
    _summary_prompt_budget,
)
from app.services.footer import FooterService, attach_footer_meta_to_all
from app.shared.discord.delivery import send_dm_or_followup
from app.shared.discord.footer_pipeline import finalize_embeds
from app.shared.discord.report_embeds import apply_standard_report_style


class _FakeDatabase:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def execute(self, _query: str, _params: tuple[str, ...]) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def fetchall(self, _query: str, _params: tuple[str, ...]):
        return []


def _build_footer_service() -> FooterService:
    return FooterService(_FakeDatabase())


def _dummy_summary() -> SummaryResult:
    return SummaryResult(
        themes=["salute", "community"],
        moments=[],
        quotes=[],
        dynamics=[],
        degrade=[],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )


def _format_runtime_moment_line(**kwargs) -> str:
    moment = kwargs["moment"]
    display_name = kwargs.get("display_name")
    include_names = kwargs.get("include_names", False)
    text = str(moment.text or "").strip() or "(nessun dettaglio)"
    clean_names: list[str] = []
    if include_names and display_name and display_name.lower() not in {"un utente", "utente", "unknown"}:
        clean_names.append(display_name)
    if clean_names:
        text = _bold_known_names(text, clean_names)
    barcello_status = kwargs.get("barcello_status")
    emoji = _barcello_emoji_from_color(getattr(barcello_status, "color", None))
    score = getattr(barcello_status, "score", None)
    safe_score = int(score) if isinstance(score, int) or str(score).isdigit() else "--"
    return f"**19/03 06:28** {emoji} **{safe_score}** — {text}"


def _format_runtime_quote_line(**kwargs) -> str:
    quote = kwargs["quote"]
    display_name = kwargs.get("display_name")
    text = str(kwargs.get("text_override") or quote.text or "").strip()
    if display_name and display_name.lower() not in {"un utente", "utente", "unknown"}:
        text = _bold_known_names(text, [display_name])
        return f"**19/03 06:28** — “{text}” — **{display_name}**"
    return f"**19/03 06:28** — “{text}”"


def _format_runtime_dynamic_line(**kwargs) -> str:
    dynamic = kwargs["dynamic"]
    display_names = [name for name in kwargs.get("display_names", []) if str(name or "").strip()]
    text = str(dynamic.text or "").strip() or "(nessun dettaglio)"
    if display_names:
        text = _bold_known_names(text, display_names)
        suffix = f" — Coinvolti: {', '.join([f'**{name}**' for name in display_names])}"
    else:
        suffix = ""
    return f"**19/03 06:28** — {text}{suffix}"


def _format_runtime_impact_line(**kwargs) -> str:
    display_name = kwargs.get("display_name")
    impact = kwargs["impact"]
    prefix = kwargs.get("prefix", "🔥")
    if display_name:
        return f"**19/03 06:28** — {prefix} **{display_name}** — {impact.reason}"
    return f"**19/03 06:28** — {prefix} {impact.reason}"


def _build_detail_embeds(*, contributors: list[str], used_local_processing: bool, groups: int = 1) -> list[discord.Embed]:
    extra_sections = [(f"📎 EXTRA {idx}", f"Dettaglio {idx}", idx + 1) for idx in range(groups - 1)]
    return build_summary_detail_embeds(
        profile="mod",
        summary=_dummy_summary(),
        include_names=False,
        include_date_in_time=False,
        guild_id=1,
        channel_id=2,
        name_map={},
        moment_primary={},
        quote_primary={},
        dynamic_primary={},
        impact_primary={},
        moment_display={},
        quote_display={},
        dynamic_names={},
        quote_texts={},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=extra_sections,
        tier_label="MOD",
        tier_config={"sections": ["themes", "extra"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=_format_runtime_quote_line,
        format_dynamic_line=_format_runtime_dynamic_line,
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(lines),
        footer_contributors=contributors,
        footer_used_local_processing=used_local_processing,
        dm_mode=False,
        moment_barcello={},
    )


def _build_runtime_payload_embeds(*, contributors: list[str], used_local_processing: bool, groups: int = 1) -> list[discord.Embed]:
    embeds = [
        discord.Embed(title="🗒️ RIASSUNTO"),
        *_build_detail_embeds(
            contributors=contributors,
            used_local_processing=used_local_processing,
            groups=groups,
        ),
    ]
    styled = apply_standard_report_style(embeds, service_name="riassunto", cover_title="🗒️ RIASSUNTO")
    attach_footer_meta_to_all(
        styled,
        service_name="riassunto",
        contributors=contributors,
        used_local_processing=used_local_processing,
    )
    return styled


class _DummyResp:
    status = 403
    reason = "Forbidden"
    text = "closed"


class _CapturingFollowup:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        return None


class _CapturingUser:
    def __init__(self, *, forbidden: bool = False) -> None:
        self.forbidden = forbidden
        self.calls: list[dict[str, object]] = []

    async def send(self, **kwargs):
        if self.forbidden:
            raise discord.Forbidden(response=_DummyResp(), message="closed")
        self.calls.append(kwargs)
        return None


class _OversizeThenCapturingUser(_CapturingUser):
    def __init__(self) -> None:
        super().__init__(forbidden=False)
        self._raised_oversize = False

    async def send(self, **kwargs):
        embeds = kwargs.get("embeds") or []
        if not self._raised_oversize and len(embeds) >= 2:
            self._raised_oversize = True
            raise discord.HTTPException(
                response=SimpleNamespace(status=400, reason="Bad Request", text="closed"),
                message={
                    "code": 50035,
                    "message": "Invalid Form Body",
                    "errors": {
                        "embeds": {
                            "0": {
                                "_errors": [
                                    {
                                        "message": "Embed size exceeds maximum size of 6000",
                                        "code": "BASE_TYPE_MAX_LENGTH",
                                    }
                                ]
                            }
                        }
                    },
                },
            )
        self.calls.append(kwargs)
        return None


def _build_interaction(*, forbidden_dm: bool = False):
    return SimpleNamespace(
        user=_CapturingUser(forbidden=forbidden_dm),
        followup=_CapturingFollowup(),
    )


def _build_interaction_with_oversize_dm():
    return SimpleNamespace(
        user=_OversizeThenCapturingUser(),
        followup=_CapturingFollowup(),
    )


def test_build_period_prefix_uses_correct_italian_for_feminine_plural_weeks() -> None:
    start_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(weeks=4)
    assert _build_period_prefix(
        "ultimi",
        start_dt=start_dt,
        end_dt=end_dt,
        start_ts=start_dt.isoformat(),
        end_ts=end_dt.isoformat(),
    ) == "Nelle ultime 4 settimane"


def test_build_period_prefix_uses_correct_italian_for_singular_week() -> None:
    start_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(weeks=1)
    assert _build_period_prefix(
        "ultimi",
        start_dt=start_dt,
        end_dt=end_dt,
        start_ts=start_dt.isoformat(),
        end_ts=end_dt.isoformat(),
    ) == "Nell'ultima settimana"


def test_build_period_prefix_uses_correct_italian_for_hours() -> None:
    start_dt = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(hours=2)
    assert _build_period_prefix(
        "ultimi",
        start_dt=start_dt,
        end_dt=end_dt,
        start_ts=start_dt.isoformat(),
        end_ts=end_dt.isoformat(),
    ) == "Nelle ultime 2 ore"


def test_build_period_prefix_uses_correct_italian_for_days_and_minutes() -> None:
    start_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _build_period_prefix(
        "ultimi",
        start_dt=start_dt,
        end_dt=start_dt + timedelta(days=3),
        start_ts=start_dt.isoformat(),
        end_ts=(start_dt + timedelta(days=3)).isoformat(),
    ) == "Negli ultimi 3 giorni"
    assert _build_period_prefix(
        "ultimi",
        start_dt=start_dt,
        end_dt=start_dt + timedelta(minutes=15),
        start_ts=start_dt.isoformat(),
        end_ts=(start_dt + timedelta(minutes=15)).isoformat(),
    ) == "Negli ultimi 15 minuti"


def test_summary_budget_scales_down_for_long_ranges() -> None:
    short_budget = _summary_prompt_budget(
        start_ts="2026-01-01T00:00:00+00:00",
        end_ts="2026-01-01T12:00:00+00:00",
        granularity_hint="hours",
        period_label="oggi",
        is_ollama=False,
        ollama_compatible_fallback=False,
    )
    long_budget = _summary_prompt_budget(
        start_ts="2026-01-01T00:00:00+00:00",
        end_ts="2026-02-15T00:00:00+00:00",
        granularity_hint="days",
        period_label="range",
        is_ollama=False,
        ollama_compatible_fallback=False,
    )
    assert long_budget["max_items"] < short_budget["max_items"]
    assert long_budget["buckets"] < short_budget["buckets"]
    assert long_budget["per_message_char_limit"] < short_budget["per_message_char_limit"]
    assert long_budget["total_prompt_char_budget"] < short_budget["total_prompt_char_budget"]


def test_summary_budget_keeps_prompt_under_target_char_budget() -> None:
    budget = _summary_prompt_budget(
        start_ts="2026-01-01T00:00:00+00:00",
        end_ts="2026-02-20T00:00:00+00:00",
        granularity_hint="days",
        period_label="range",
        is_ollama=False,
        ollama_compatible_fallback=False,
    )
    messages = [
        {
            "ts": f"2026-01-{(idx % 28) + 1:02d}T10:00:00+00:00",
            "author_id": f"u{idx % 5}",
            "content": ("messaggio molto lungo " * 60) + str(idx),
            "meta": {"kind": "message", "in_call": (idx % 7 == 0)},
            "message_id": f"m{idx}",
        }
        for idx in range(300)
    ]
    system_prompt = "s" * 6000
    user_payload, compact_messages, stats = _build_summary_prompt_payload(
        messages=messages,
        payload_base={"tier": "role1", "metrics": {}, "summary_context": {}, "granularity_hint": "giorni"},
        system_prompt=system_prompt,
        budget=budget,
    )
    prompt_chars = len(user_payload) + len(system_prompt)
    assert compact_messages
    assert prompt_chars <= int(budget["total_prompt_char_budget"])
    assert len(user_payload) <= int(budget["hard_prompt_char_cap"])
    assert stats["sampled_after_budget"] <= stats["sampled_before_budget"]
    assert _estimate_summary_prompt_tokens(prompt_chars) <= 10000


def test_riassunto_footer_includes_used_display_model_even_when_not_dm_mode() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs(
            {"used_ai_output": True, "used_display_model": "gpt-4o"}
        )
        embeds = [discord.Embed(title="🗒️ RIASSUNTO"), *_build_detail_embeds(contributors=contributors, used_local_processing=used_local_processing)]
        styled = apply_standard_report_style(embeds, service_name="riassunto", cover_title="🗒️ RIASSUNTO")
        attach_footer_meta_to_all(
            styled,
            service_name="riassunto",
            contributors=contributors,
            used_local_processing=used_local_processing,
        )
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")
        await finalize_embeds(styled, service, default_service_name="riassunto")

        assert all("Dati elaborati con gpt-4o" in (embed.footer.text or "") for embed in styled)

    asyncio.run(_run())


def test_riassunto_footer_includes_used_display_model_on_runtime_send_path() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs({"used_ai_output": True, "used_display_model": "gpt-4o"})
        interaction = _build_interaction()
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        sent_dm = await send_dm_or_followup(
            interaction,
            embeds=_build_runtime_payload_embeds(contributors=contributors, used_local_processing=used_local_processing),
            footer_service=service,
            default_service_name="riassunto",
        )

        assert sent_dm is True
        assert len(interaction.user.calls) == 1
        sent_embeds = interaction.user.calls[0]["embeds"]
        assert sent_embeds
        assert all("Dati elaborati con gpt-4o" in (embed.footer.text or "") for embed in sent_embeds)

    asyncio.run(_run())


def test_riassunto_footer_includes_used_display_model_on_followup_fallback_path() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs({"used_ai_output": True, "used_display_model": "gpt-4o"})
        interaction = _build_interaction(forbidden_dm=True)
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        sent_dm = await send_dm_or_followup(
            interaction,
            embeds=_build_runtime_payload_embeds(contributors=contributors, used_local_processing=used_local_processing),
            footer_service=service,
            default_service_name="riassunto",
        )

        assert sent_dm is False
        assert interaction.followup.calls
        followup_embeds = interaction.followup.calls[0]["embeds"]
        assert followup_embeds
        assert all("Dati elaborati con gpt-4o" in (embed.footer.text or "") for embed in followup_embeds)

    asyncio.run(_run())


def test_riassunto_footer_stays_local_when_ai_output_not_used() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs(
            {"used_ai_output": False, "used_display_model": "gpt-4o"}
        )
        embeds = [discord.Embed(title="🗒️ RIASSUNTO"), *_build_detail_embeds(contributors=contributors, used_local_processing=used_local_processing)]
        styled = apply_standard_report_style(embeds, service_name="riassunto", cover_title="🗒️ RIASSUNTO")
        attach_footer_meta_to_all(
            styled,
            service_name="riassunto",
            contributors=contributors,
            used_local_processing=used_local_processing,
        )
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")
        await finalize_embeds(styled, service, default_service_name="riassunto")

        assert all("Dati elaborati con" not in (embed.footer.text or "") for embed in styled)

    asyncio.run(_run())


def test_riassunto_footer_stays_local_when_ai_output_not_used_runtime_path() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs({"used_ai_output": False, "used_display_model": "gpt-4o"})
        interaction = _build_interaction()
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        await send_dm_or_followup(
            interaction,
            embeds=_build_runtime_payload_embeds(contributors=contributors, used_local_processing=used_local_processing),
            footer_service=service,
            default_service_name="riassunto",
        )

        sent_embeds = interaction.user.calls[0]["embeds"]
        assert all("Dati elaborati con" not in (embed.footer.text or "") for embed in sent_embeds)

    asyncio.run(_run())


def test_riassunto_multipage_embeds_keep_same_ai_footer_on_all_pages() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs(
            {"used_ai_output": True, "used_display_model": "gpt-4o-mini"}
        )
        embeds = [discord.Embed(title="🗒️ RIASSUNTO"), *_build_detail_embeds(contributors=contributors, used_local_processing=used_local_processing, groups=4)]
        styled = apply_standard_report_style(embeds, service_name="riassunto", cover_title="🗒️ RIASSUNTO")
        attach_footer_meta_to_all(
            styled,
            service_name="riassunto",
            contributors=contributors,
            used_local_processing=used_local_processing,
        )
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")
        await finalize_embeds(styled, service, default_service_name="riassunto")

        footers = [embed.footer.text for embed in styled]
        assert len(styled) >= 3
        assert len(set(footers)) == 1
        assert footers[0] == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o-mini"

    asyncio.run(_run())


def test_riassunto_multipage_footer_remains_consistent_after_send_pipeline() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs({"used_ai_output": True, "used_display_model": "gpt-4o-mini"})
        interaction = _build_interaction()
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        await send_dm_or_followup(
            interaction,
            embeds=_build_runtime_payload_embeds(contributors=contributors, used_local_processing=used_local_processing, groups=4),
            footer_service=service,
            default_service_name="riassunto",
        )

        sent_embeds = interaction.user.calls[0]["embeds"]
        footers = [embed.footer.text for embed in sent_embeds]
        assert len(sent_embeds) >= 4
        assert len(set(footers)) == 1
        assert footers[0] == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o-mini"

    asyncio.run(_run())


def test_riassunto_ai_footer_survives_dm_oversize_retry_path() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs({"used_ai_output": True, "used_display_model": "gpt-4o-mini"})
        interaction = _build_interaction_with_oversize_dm()
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        sent_dm = await send_dm_or_followup(
            interaction,
            embeds=_build_runtime_payload_embeds(contributors=contributors, used_local_processing=used_local_processing, groups=4),
            footer_service=service,
            default_service_name="riassunto",
        )

        assert sent_dm is True
        assert len(interaction.user.calls) == 2
        retried_embeds = [embed for call in interaction.user.calls for embed in call.get("embeds", [])]
        assert retried_embeds
        assert all(embed.footer.text == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o-mini" for embed in retried_embeds)
        assert not interaction.followup.calls

    asyncio.run(_run())


def test_riassunto_moments_include_barcello_dot_and_bold_score() -> None:
    summary = SummaryResult(
        themes=[],
        moments=[SummaryItem(ts="2026-03-19T05:28:00+00:00", text="Mario chiude il task", author_id="u1")],
        quotes=[],
        dynamics=[],
        degrade=[],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )
    embeds = build_summary_detail_embeds(
        profile="role1",
        summary=summary,
        include_names=True,
        include_date_in_time=True,
        guild_id=1,
        channel_id=2,
        name_map={},
        moment_primary={id(summary.moments[0]): "111"},
        quote_primary={},
        dynamic_primary={},
        impact_primary={},
        moment_display={id(summary.moments[0]): "Mario"},
        quote_display={},
        dynamic_names={},
        quote_texts={},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="PLUS",
        tier_config={"sections": ["themes", "moments"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=_format_runtime_quote_line,
        format_dynamic_line=_format_runtime_dynamic_line,
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={id(summary.moments[0]): BarcelloResult(score=64, color="verde")},
    )
    value = embeds[0].fields[1].value
    assert "🟢" in value
    assert "**64**" in value


def test_riassunto_themes_are_rendered_as_hashtags() -> None:
    embeds = _build_detail_embeds(contributors=[], used_local_processing=True)
    assert embeds[0].fields[0].value == "#salute, #community"


def test_riassunto_bolds_known_names_in_moments_or_dynamics() -> None:
    summary = SummaryResult(
        themes=[],
        moments=[SummaryItem(ts=None, text="Mario ha risolto il blocco", author_id="u1")],
        quotes=[],
        dynamics=[SummaryItem(ts=None, text="Mario e Luca hanno coordinato il rilascio", author_id="u1")],
        degrade=[],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )
    embeds = build_summary_detail_embeds(
        profile="role3",
        summary=summary,
        include_names=True,
        include_date_in_time=False,
        guild_id=1,
        channel_id=2,
        name_map={},
        moment_primary={},
        quote_primary={},
        dynamic_primary={},
        impact_primary={},
        moment_display={id(summary.moments[0]): "Mario"},
        quote_display={},
        dynamic_names={id(summary.dynamics[0]): ["Mario", "Luca"]},
        quote_texts={},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="PRO MAX",
        tier_config={"sections": ["themes", "moments", "dynamics"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=_format_runtime_quote_line,
        format_dynamic_line=_format_runtime_dynamic_line,
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={id(summary.moments[0]): BarcelloResult(score=64, color="verde")},
    )
    rendered = "\n".join(field.value for embed in embeds for field in embed.fields)
    assert "**Mario**" in rendered
    assert "**Luca**" in rendered
