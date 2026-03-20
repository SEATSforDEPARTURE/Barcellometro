import asyncio
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Connection=object)

from app.plugins.commands_modular.riassunto import (
    _build_period_prefix,
    _format_summary_time_link,
    _resolve_summary_primary_ref,
    _summary_footer_inputs,
)
from app.renderers.channel_summary import _barcello_emoji_from_color, _bold_known_names
from app.renderers.detail_embeds import _truncate_line_preserve_md_link, build_summary_detail_embeds
from app.services.barcello_service import BarcelloResult
from app.services.content_summary_service import (
    DEFAULT_SUMMARY_CONFIG,
    SummaryService,
    SummaryImpact,
    SummaryItem,
    SummaryQuote,
    SummaryResult,
    _build_summary_prompt_payload,
    _estimate_summary_prompt_tokens,
    _summary_prompt_budget,
)
from app.services.footer import FooterService, attach_footer_meta_to_all
from app.shared.discord.delivery import _prepare_embeds_for_send, send_dm_or_followup
from app.shared.discord.embed_limits import (
    _SUMMARY_LINK_PREFIX_RE,
    _split_field_chunks,
    count_summary_clickable_timestamps_in_values,
    extract_protected_summary_prefix,
    normalize_embeds_for_discord,
    split_markdown_lines_into_field_values,
    truncate_line_preserve_links,
)
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


class _PrimaryRefDb:
    def __init__(self, *, existing: set[str] | None = None, nearest: str | None = None) -> None:
        self.existing = existing or set()
        self.nearest = nearest

    async def message_exists_in_channel(self, *, channel_id: str, message_id: str) -> bool:
        _ = channel_id
        return message_id in self.existing

    async def fetch_nearest_message_id_in_range(self, **_kwargs):
        return self.nearest


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


def test_riassunto_footer_survives_explicit_finalize_then_auto_finalize_runtime_path() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs({"used_ai_output": True, "used_display_model": "gpt-4o"})
        embeds = _build_runtime_payload_embeds(contributors=contributors, used_local_processing=used_local_processing)
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        prepared = await _prepare_embeds_for_send(
            embeds,
            footer_service=service,
            default_service_name="riassunto",
        )
        before_second_finalize = [embed.footer.text for embed in prepared]

        await finalize_embeds(prepared, service, default_service_name="riassunto")

        after_second_finalize = [embed.footer.text for embed in prepared]
        assert before_second_finalize
        assert before_second_finalize == after_second_finalize
        assert all(text == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o" for text in after_second_finalize)

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


def test_riassunto_footer_survives_explicit_finalize_then_auto_finalize_followup_fallback() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs({"used_ai_output": True, "used_display_model": "gpt-4o"})
        embeds = _build_runtime_payload_embeds(contributors=contributors, used_local_processing=used_local_processing)
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        prepared = await _prepare_embeds_for_send(
            embeds,
            footer_service=service,
            default_service_name="riassunto",
        )
        await finalize_embeds(prepared, service, default_service_name="riassunto")

        assert all("Dati elaborati con gpt-4o" in (embed.footer.text or "") for embed in prepared)

        interaction = _build_interaction(forbidden_dm=True)
        sent_dm = await send_dm_or_followup(
            interaction,
            embeds=prepared,
            footer_service=service,
            default_service_name="riassunto",
        )

        assert sent_dm is False
        followup_embeds = interaction.followup.calls[0]["embeds"]
        assert followup_embeds
        assert all(embed.footer.text == "Barcellometro dev6 · In via di sviluppo. · Dati elaborati con gpt-4o" for embed in followup_embeds)

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


def test_riassunto_multipage_footer_remains_consistent_after_double_finalize() -> None:
    async def _run() -> None:
        contributors, used_local_processing = _summary_footer_inputs({"used_ai_output": True, "used_display_model": "gpt-4o-mini"})
        embeds = _build_runtime_payload_embeds(contributors=contributors, used_local_processing=used_local_processing, groups=4)
        service = _build_footer_service()
        await service.set_version("dev6")
        await service.set_global_phrase("In via di sviluppo.")

        prepared = await _prepare_embeds_for_send(
            embeds,
            footer_service=service,
            default_service_name="riassunto",
        )
        await finalize_embeds(prepared, service, default_service_name="riassunto")

        footers = [embed.footer.text for embed in prepared]
        assert len(prepared) >= 4
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


def test_riassunto_moment_timestamp_link_is_clickable_when_primary_ref_exists() -> None:
    rendered = _format_summary_time_link(
        "2026-03-19T05:28:00+00:00",
        "123456789012345678",
        guild_id=1,
        channel_id=2,
    )
    assert rendered == "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"


def test_riassunto_impact_timestamp_link_uses_nearest_message_fallback_when_message_id_missing() -> None:
    async def _run() -> None:
        db = _PrimaryRefDb(existing={"223456789012345678"}, nearest="223456789012345678")
        resolved = await _resolve_summary_primary_ref(
            db,
            item_type="impact",
            channel_id="2",
            start_ts="2026-03-19T00:00:00+00:00",
            end_ts="2026-03-19T23:59:59+00:00",
            ts="2026-03-19T05:28:00+00:00",
            explicit_refs=[],
        )
        assert resolved == "223456789012345678"

    asyncio.run(_run())


def test_resolve_summary_primary_ref_uses_nearest_when_explicit_missing() -> None:
    async def _run() -> None:
        db = _PrimaryRefDb(existing={"223456789012345678"}, nearest="223456789012345678")
        resolved = await _resolve_summary_primary_ref(
            db,
            item_type="moment",
            channel_id="2",
            start_ts="2026-03-19T00:00:00+00:00",
            end_ts="2026-03-19T23:59:59+00:00",
            ts="2026-03-19T06:28:00+00:00",
            explicit_refs=None,
        )
        assert resolved == "223456789012345678"

    asyncio.run(_run())


def test_resolve_summary_primary_ref_accepts_valid_jump_url_or_normalizes_it() -> None:
    async def _run() -> None:
        channel_id = "223456789012345678"
        jump_url = f"https://discord.com/channels/999999999999999999/{channel_id}/123456789012345678"
        db = _PrimaryRefDb(existing={"123456789012345678"})
        resolved = await _resolve_summary_primary_ref(
            db,
            item_type="quote",
            channel_id=channel_id,
            start_ts="2026-03-19T00:00:00+00:00",
            end_ts="2026-03-19T23:59:59+00:00",
            ts="2026-03-19T06:28:00+00:00",
            explicit_refs=[jump_url],
        )
        assert resolved == jump_url

    asyncio.run(_run())


def test_riassunto_moment_line_keeps_clickable_timestamp_after_split() -> None:
    link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    long_line = (
        f"• {link} 🟢 **64** — "
        + "Mario coordina il rilascio con molto contesto operativo e dettagli utili " * 20
    ).strip()
    chunks = _split_field_chunks(long_line, 180)
    assert len(chunks) >= 2
    assert link in chunks[0]
    assert all("123456789012345678" not in chunk or link in chunk for chunk in chunks)


def test_riassunto_quote_line_keeps_clickable_timestamp_after_long_text_chunking() -> None:
    quote_link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    summary = SummaryResult(
        themes=[],
        moments=[],
        quotes=[SummaryQuote(ts="2026-03-19T05:28:00+00:00", text="placeholder", author_id="u1")],
        dynamics=[],
        degrade=[],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )
    embeds = build_summary_detail_embeds(
        profile="role2",
        summary=summary,
        include_names=True,
        include_date_in_time=False,
        guild_id=1,
        channel_id=2,
        name_map={},
        moment_primary={},
        quote_primary={id(summary.quotes[0]): "123456789012345678"},
        dynamic_primary={},
        impact_primary={},
        moment_display={},
        quote_display={id(summary.quotes[0]): "Mario"},
        dynamic_names={},
        quote_texts={id(summary.quotes[0]): "Messaggio molto lungo " * 80},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="PRO",
        tier_config={"sections": ["quotes"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=lambda **kwargs: f"{quote_link} — “{kwargs['text_override']}” — **Mario**",
        format_dynamic_line=_format_runtime_dynamic_line,
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={},
    )
    rendered = "\n".join(field.value for embed in embeds for field in embed.fields)
    assert quote_link in rendered


def test_embed_limits_do_not_break_masked_links_in_summary_fields() -> None:
    link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    value = "\n".join(
        [
            f"• {link} — Mario coordina il rilascio con molto contesto operativo {'utile ' * 20}".strip(),
            f"• {link} — Luca conferma il piano {'dettagliato ' * 18}".strip(),
        ]
    )
    chunks = _split_field_chunks(value, 220)
    assert len(chunks) >= 2
    combined = "\n".join(chunks)
    assert combined.count(link) == 2
    assert "](" in combined


def test_riassunto_timestamp_links_survive_full_normalize_and_pagination_pipeline() -> None:
    link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    summary = SummaryResult(
        themes=[],
        moments=[],
        quotes=[],
        dynamics=[
            SummaryItem(
                ts="2026-03-19T05:28:00+00:00",
                text=("Mario coordina il rilascio " + ("con molto contesto " * 50)).strip(),
                author_id="u1",
            )
            for _ in range(20)
        ],
        degrade=[],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )
    dynamic_primary = {id(item): "123456789012345678" for item in summary.dynamics}
    embeds = build_summary_detail_embeds(
        profile="role3",
        summary=summary,
        include_names=False,
        include_date_in_time=False,
        guild_id=1,
        channel_id=2,
        name_map={},
        moment_primary={},
        quote_primary={},
        dynamic_primary=dynamic_primary,
        impact_primary={},
        moment_display={},
        quote_display={},
        dynamic_names={},
        quote_texts={},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="PRO MAX",
        tier_config={"sections": ["dynamics"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=_format_runtime_quote_line,
        format_dynamic_line=lambda **kwargs: f"{link} — {kwargs['dynamic'].text}",
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={},
    )
    normalized = normalize_embeds_for_discord(embeds, max_chars=4500)
    rendered = "\n".join(field.value for embed in normalized for field in embed.fields)
    assert link in rendered
    assert rendered.count(link) == len(summary.dynamics)


def test_riassunto_quote_or_dynamic_links_survive_split_and_truncation() -> None:
    quote_link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    dynamic_link = "**[06:31](https://discord.com/channels/1/2/223456789012345678)**"
    summary = SummaryResult(
        themes=[],
        moments=[],
        quotes=[SummaryQuote(ts="2026-03-19T05:28:00+00:00", text="placeholder", author_id="u1")],
        dynamics=[
            SummaryItem(
                ts="2026-03-19T05:31:00+00:00",
                text="Mario e Luca hanno coordinato il rilascio con " + ("dettagli utili " * 40),
                author_id="u1",
            )
        ],
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
        quote_primary={id(summary.quotes[0]): "123456789012345678"},
        dynamic_primary={id(summary.dynamics[0]): "223456789012345678"},
        impact_primary={},
        moment_display={},
        quote_display={id(summary.quotes[0]): "Mario"},
        dynamic_names={id(summary.dynamics[0]): ["Mario", "Luca"]},
        quote_texts={id(summary.quotes[0]): "Messaggio molto lungo " * 50},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="PRO MAX",
        tier_config={"sections": ["quotes", "dynamics"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=lambda **kwargs: f"{quote_link} — “{kwargs['text_override']}” — **Mario**",
        format_dynamic_line=lambda **kwargs: f"{dynamic_link} — {kwargs['dynamic'].text} — Coinvolti: **Mario**, **Luca**",
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={},
    )
    rendered = "\n".join(field.value for embed in embeds for field in embed.fields)
    assert quote_link in rendered
    assert dynamic_link in rendered


def test_riassunto_mod_impact_includes_aura_points_for_period() -> None:
    impact = SummaryImpact(
        author_id="u1",
        reason="Ha riportato calma nel momento più teso.",
        ts="2026-03-19T05:28:00+00:00",
        message_id="123456789012345678",
        aura_points_period=9,
        aura_total_points=12,
    )
    summary = SummaryResult(
        themes=[],
        moments=[],
        quotes=[],
        dynamics=[],
        degrade=[],
        invigorate=[impact],
        advice=[],
        metrics={},
        ai_status={},
    )
    embeds = build_summary_detail_embeds(
        profile="mod",
        summary=summary,
        include_names=False,
        include_date_in_time=False,
        guild_id=1,
        channel_id=2,
        name_map={"u1": "Mario"},
        moment_primary={},
        quote_primary={},
        dynamic_primary={},
        impact_primary={id(impact): "123456789012345678"},
        moment_display={},
        quote_display={},
        dynamic_names={},
        quote_texts={},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="MOD",
        tier_config={"sections": ["impact"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=_format_runtime_quote_line,
        format_dynamic_line=_format_runtime_dynamic_line,
        format_impact_line=lambda **kwargs: (
            f"**[06:28](https://discord.com/channels/1/2/123456789012345678)** — 🌿 **Mario** — {kwargs['impact'].reason}\n"
            "  Aura nel periodo: **+9** · Totale Aura finestra: **+12**"
        ),
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={},
    )
    rendered = "\n".join(field.value for embed in embeds for field in embed.fields)
    assert "Aura nel periodo: **+9**" in rendered
    assert "Totale Aura finestra: **+12**" in rendered


def test_riassunto_mod_impact_handles_missing_aura_data_gracefully() -> None:
    impact = SummaryImpact(
        author_id="u1",
        reason="Ha alzato la tensione con richiami diretti.",
        ts="2026-03-19T05:28:00+00:00",
        message_id="123456789012345678",
    )
    summary = SummaryResult(
        themes=[],
        moments=[],
        quotes=[],
        dynamics=[],
        degrade=[impact],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )
    embeds = build_summary_detail_embeds(
        profile="mod",
        summary=summary,
        include_names=False,
        include_date_in_time=False,
        guild_id=1,
        channel_id=2,
        name_map={"u1": "Mario"},
        moment_primary={},
        quote_primary={},
        dynamic_primary={},
        impact_primary={id(impact): "123456789012345678"},
        moment_display={},
        quote_display={},
        dynamic_names={},
        quote_texts={},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="MOD",
        tier_config={"sections": ["impact"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=_format_runtime_quote_line,
        format_dynamic_line=_format_runtime_dynamic_line,
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={},
    )
    rendered = "\n".join(field.value for embed in embeds for field in embed.fields)
    assert "Aura nel periodo" not in rendered


def test_riassunto_links_remain_valid_after_pagination() -> None:
    link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    summary = SummaryResult(
        themes=[],
        moments=[],
        quotes=[],
        dynamics=[
            SummaryItem(
                ts="2026-03-19T05:28:00+00:00",
                text=("Mario coordina il rilascio " + ("con molto contesto " * 40)).strip(),
                author_id="u1",
            )
            for _ in range(24)
        ],
        degrade=[],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )
    dynamic_primary = {id(item): "123456789012345678" for item in summary.dynamics}
    embeds = build_summary_detail_embeds(
        profile="role3",
        summary=summary,
        include_names=False,
        include_date_in_time=False,
        guild_id=1,
        channel_id=2,
        name_map={},
        moment_primary={},
        quote_primary={},
        dynamic_primary=dynamic_primary,
        impact_primary={},
        moment_display={},
        quote_display={},
        dynamic_names={},
        quote_texts={},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="PRO MAX",
        tier_config={"sections": ["dynamics"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=_format_runtime_quote_line,
        format_dynamic_line=lambda **kwargs: f"{link} — {kwargs['dynamic'].text}",
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={},
    )
    assert len(embeds) >= 2
    rendered = "\n".join(field.value for embed in embeds for field in embed.fields)
    assert link in rendered


def test_bold_masked_link_is_not_split_by_embed_limits() -> None:
    link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    line = f"• {link} — Mario coordina il rilascio {'utile ' * 24}".strip()
    chunks = split_markdown_lines_into_field_values([line], limit=90)

    assert len(chunks) >= 2
    assert chunks[0].startswith(f"• {link} —")
    assert all("**[06:28](https://discord.com/channels/1/2/123456789012345678)" not in chunk or link in chunk for chunk in chunks)


def test_truncate_line_preserve_md_link_keeps_closing_bold_markers() -> None:
    line = "**[06:28](https://discord.com/channels/1/2/123456789012345678)** extra"
    truncated = _truncate_line_preserve_md_link(line, len(line) - 2)

    assert truncated.startswith("**[06:28](https://discord.com/channels/1/2/123456789012345678)**")
    assert truncated.count("**") % 2 == 0
    assert not truncated.endswith(")")


def test_summary_link_prefix_regex_matches_moment_line_with_barcello_dot_and_score() -> None:
    line = "**[06:28](https://discord.com/channels/1/2/123456789012345678)** 🟢 **64** — Testo momento"
    match = _SUMMARY_LINK_PREFIX_RE.match(line)

    assert match is not None
    assert match.group('prefix') == "**[06:28](https://discord.com/channels/1/2/123456789012345678)** 🟢 **64** — "
    assert match.group('tail') == 'Testo momento'


def test_riassunto_moment_timestamp_survives_full_chunking_pipeline() -> None:
    link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    summary = SummaryResult(
        themes=[],
        moments=[
            SummaryItem(
                ts="2026-03-19T05:28:00+00:00",
                text=("Mario coordina il rilascio " + ("con molto contesto operativo " * 40)).strip(),
                author_id="u1",
            )
            for _ in range(10)
        ],
        quotes=[],
        dynamics=[],
        degrade=[],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )
    moment_primary = {id(item): "123456789012345678" for item in summary.moments}
    embeds = build_summary_detail_embeds(
        profile="role1",
        summary=summary,
        include_names=False,
        include_date_in_time=False,
        guild_id=1,
        channel_id=2,
        name_map={},
        moment_primary=moment_primary,
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
        extra_sections=None,
        tier_label="BASE",
        tier_config={"sections": ["moments"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=lambda **kwargs: f"{link} 🟢 **64** — {kwargs['moment'].text}",
        format_quote_line=_format_runtime_quote_line,
        format_dynamic_line=_format_runtime_dynamic_line,
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={},
    )
    normalized = normalize_embeds_for_discord(embeds, max_chars=4500)
    rendered = "\n".join(field.value for embed in normalized for field in embed.fields)

    assert link in rendered
    assert rendered.count(link) == len(summary.moments)


def test_riassunto_quote_timestamp_survives_truncation_when_bold_linked() -> None:
    quote_link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    summary = SummaryResult(
        themes=[],
        moments=[],
        quotes=[SummaryQuote(ts="2026-03-19T05:28:00+00:00", text="placeholder", author_id="u1")],
        dynamics=[],
        degrade=[],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )
    embeds = build_summary_detail_embeds(
        profile="role2",
        summary=summary,
        include_names=True,
        include_date_in_time=False,
        guild_id=1,
        channel_id=2,
        name_map={},
        moment_primary={},
        quote_primary={id(summary.quotes[0]): "123456789012345678"},
        dynamic_primary={},
        impact_primary={},
        moment_display={},
        quote_display={id(summary.quotes[0]): "Mario"},
        dynamic_names={},
        quote_texts={id(summary.quotes[0]): "Messaggio molto lungo " * 100},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="PRO",
        tier_config={"sections": ["quotes"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=lambda **kwargs: f"{quote_link} — “{kwargs['text_override']}” — **Mario**",
        format_dynamic_line=_format_runtime_dynamic_line,
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={},
    )
    rendered = "\n".join(field.value for embed in embeds for field in embed.fields)

    assert quote_link in rendered
    assert rendered.count(quote_link) == 1


def test_riassunto_dynamic_timestamp_survives_normalize_pipeline() -> None:
    link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    summary = SummaryResult(
        themes=[],
        moments=[],
        quotes=[],
        dynamics=[
            SummaryItem(
                ts="2026-03-19T05:28:00+00:00",
                text=("Mario coordina il rilascio " + ("con molto contesto " * 50)).strip(),
                author_id="u1",
            )
            for _ in range(12)
        ],
        degrade=[],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )
    dynamic_primary = {id(item): "123456789012345678" for item in summary.dynamics}
    embeds = build_summary_detail_embeds(
        profile="role3",
        summary=summary,
        include_names=False,
        include_date_in_time=False,
        guild_id=1,
        channel_id=2,
        name_map={},
        moment_primary={},
        quote_primary={},
        dynamic_primary=dynamic_primary,
        impact_primary={},
        moment_display={},
        quote_display={},
        dynamic_names={},
        quote_texts={},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="PRO MAX",
        tier_config={"sections": ["dynamics"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=_format_runtime_moment_line,
        format_quote_line=_format_runtime_quote_line,
        format_dynamic_line=lambda **kwargs: f"{link} — {kwargs['dynamic'].text}",
        format_impact_line=_format_runtime_impact_line,
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={},
    )
    normalized = normalize_embeds_for_discord(embeds, max_chars=4500)
    rendered = "\n".join(field.value for embed in normalized for field in embed.fields)

    assert rendered.count(link) == len(summary.dynamics)


def test_riassunto_impact_timestamp_survives_embed_limits_chunking() -> None:
    link = "**[06:28](https://discord.com/channels/1/2/123456789012345678)**"
    value = "\n".join(
        f"• {link} — 🔥 **Mario** — {'supporta il gruppo ' * 22}"
        for _ in range(3)
    )

    chunks = _split_field_chunks(value, 180)
    rendered = "\n".join(chunks)

    assert len(chunks) >= 2
    assert rendered.count(link) == 3


def test_extract_protected_summary_prefix_supports_date_call_and_score() -> None:
    line = "• **[19/03 06:28](https://discord.com/channels/1/2/123456789012345678)** 📞 🟢 **64** — Testo momento"
    protected = extract_protected_summary_prefix(line)

    assert protected is not None
    prefix, tail = protected
    assert prefix == "• **[19/03 06:28](https://discord.com/channels/1/2/123456789012345678)** 📞 🟢 **64** — "
    assert tail == "Testo momento"


def test_summary_chunks_keep_atomic_prefix_for_quote_dynamic_and_impact_lines() -> None:
    lines = [
        "• **[19/03 06:28](https://discord.com/channels/1/2/123456789012345678)** 📞 — “Messaggio molto lungo " + ("utile " * 20) + "”",
        "• **[19/03 06:28](https://discord.com/channels/1/2/123456789012345678)** — Coordinamento operativo " + ("chiaro " * 20),
        "• **[19/03 06:28](https://discord.com/channels/1/2/123456789012345678)** — 🔥 **Mario** — " + ("richiama il gruppo " * 20),
    ]

    chunks = split_markdown_lines_into_field_values(lines, limit=180)
    rendered = "\n".join(chunks)
    link = "**[19/03 06:28](https://discord.com/channels/1/2/123456789012345678)**"

    assert chunks[0].startswith(f"• {link}")
    assert rendered.count(link) == 3
    assert "123456789012345678)** — 🔥" in rendered
    assert "123456789012345678)** 📞 —" in rendered
    assert rendered.count("123456789012345678)**") == 3


def test_truncate_line_preserve_md_link_keeps_summary_prefix_when_limit_is_shorter_than_prefix() -> None:
    line = "• **[19/03 06:28](https://discord.com/channels/1/2/123456789012345678)** 📞 🟢 **64** — " + ("testo " * 20)
    protected_prefix, _ = extract_protected_summary_prefix(line) or ("", "")

    shared = truncate_line_preserve_links(line, 24)
    renderer = _truncate_line_preserve_md_link(line, 24)

    assert shared == renderer
    assert shared.startswith(protected_prefix)
    assert shared.endswith("…")
    assert shared.count("**") % 2 == 0


def test_full_summary_pipeline_preserves_all_clickable_timestamps_after_sanitize_and_normalize() -> None:
    link = "**[19/03 06:28](https://discord.com/channels/1/2/123456789012345678)**"
    summary = SummaryResult(
        themes=[],
        moments=[
            SummaryItem(ts="2026-03-19T05:28:00+00:00", text=("Momento " + ("contestuale " * 40)).strip(), author_id="u1"),
            SummaryItem(ts="2026-03-19T06:28:00+00:00", text=("Altro momento " + ("contestuale " * 40)).strip(), author_id="u2", in_call=True),
        ],
        quotes=[SummaryQuote(ts="2026-03-19T07:28:00+00:00", text=("Citazione " + ("memorabile " * 30)).strip(), author_id="u3")],
        dynamics=[SummaryItem(ts="2026-03-19T08:28:00+00:00", text=("Dinamica " + ("operativa " * 35)).strip(), author_id="u4")],
        degrade=[SummaryImpact(author_id="u5", reason=("Motivo " + ("concreto " * 20)).strip(), ts="2026-03-19T09:28:00+00:00", message_id="123456789012345678")],
        invigorate=[],
        advice=[],
        metrics={},
        ai_status={},
    )
    embeds = build_summary_detail_embeds(
        profile="mod",
        summary=summary,
        include_names=True,
        include_date_in_time=True,
        guild_id=1,
        channel_id=2,
        name_map={"u5": "Mario"},
        moment_primary={id(summary.moments[0]): "123456789012345678", id(summary.moments[1]): "123456789012345678"},
        quote_primary={id(summary.quotes[0]): "123456789012345678"},
        dynamic_primary={id(summary.dynamics[0]): "123456789012345678"},
        impact_primary={id(summary.degrade[0]): "123456789012345678"},
        moment_display={},
        quote_display={},
        dynamic_names={},
        quote_texts={},
        privacy_intervals=None,
        privacy_disclaimer_lines=None,
        metrics_report=None,
        extra_sections=None,
        tier_label="MOD",
        tier_config={"sections": ["moments", "quotes", "dynamics", "impact"]},
        details_color=0x5865F2,
        req_id="req",
        format_moment_line=lambda **kwargs: (
            f"**[19/03 06:28](https://discord.com/channels/1/2/123456789012345678)**"
            f"{' 📞' if kwargs['moment'].in_call else ''} 🟢 **64** — {kwargs['moment'].text}"
        ),
        format_quote_line=lambda **kwargs: f"{link} — “{kwargs['quote'].text}”",
        format_dynamic_line=lambda **kwargs: f"{link} — {kwargs['dynamic'].text}",
        format_impact_line=lambda **kwargs: f"{link} — 🔥 **Mario** — {kwargs['impact'].reason}",
        format_bullets=lambda lines: "\n".join(f"• {line}" for line in lines),
        moment_barcello={},
    )
    normalized = normalize_embeds_for_discord(embeds, max_chars=4500)
    final_values = [field.value for embed in normalized for field in embed.fields]

    assert count_summary_clickable_timestamps_in_values(final_values) == 5


def test_local_moments_describe_greeting_context_not_keyword_soup() -> None:
    service = SummaryService(database=_FakeDatabase())
    moments = service._extract_moments(
        [
            {"ts": "2026-03-19T07:00:00+00:00", "author_id": "u1", "content": "Buongiorno belle pollettine", "meta": {}, "message_id": "111111111111111111"},
            {"ts": "2026-03-19T07:01:00+00:00", "author_id": "u2", "content": "Ciao, come state stamattina?", "meta": {}, "message_id": "111111111111111112"},
        ],
        DEFAULT_SUMMARY_CONFIG,
        "role1",
        granularity_hint="hours",
    )

    assert moments
    assert "spunti su belle" not in moments[0].text.lower()
    assert "pollettine" not in moments[0].text.lower()
    assert "saluti" in moments[0].text.lower() or "si apre" in moments[0].text.lower()


def test_local_moments_describe_distress_context_not_token_echo() -> None:
    service = SummaryService(database=_FakeDatabase())
    moments = service._extract_moments(
        [
            {"ts": "2026-03-19T10:00:00+00:00", "author_id": "u1", "content": "Sembro esaurita, sto male davvero oggi", "meta": {}, "message_id": "222222222222222221"},
            {"ts": "2026-03-19T10:02:00+00:00", "author_id": "u2", "content": "Se vuoi racconta con calma cosa sta succedendo", "meta": {}, "message_id": "222222222222222222"},
        ],
        DEFAULT_SUMMARY_CONFIG,
        "role1",
        granularity_hint="hours",
    )

    assert moments
    assert "spunti su mio e sembro" not in moments[0].text.lower()
    assert "stanc" in moments[0].text.lower() or "difficoltà" in moments[0].text.lower() or "malessere" in moments[0].text.lower()


def test_local_moments_capture_music_and_spotify_context() -> None:
    service = SummaryService(database=_FakeDatabase())
    moments = service._extract_moments(
        [
            {"ts": "2026-03-19T12:00:00+00:00", "author_id": "u1", "content": "Sto finendo un brano nuovo e vorrei pubblicarlo su Spotify", "meta": {}, "message_id": "333333333333333331"},
            {"ts": "2026-03-19T12:03:00+00:00", "author_id": "u2", "content": "Secondo me ha senso distribuirlo come singolo prima dell'album", "meta": {}, "message_id": "333333333333333332"},
        ],
        DEFAULT_SUMMARY_CONFIG,
        "role1",
        granularity_hint="hours",
    )

    assert moments
    assert "musica" in moments[0].text.lower()
    assert "spotify" in moments[0].text.lower() or "brani" in moments[0].text.lower()


def test_local_moments_capture_ramadan_and_fasting_context() -> None:
    service = SummaryService(database=_FakeDatabase())
    moments = service._extract_moments(
        [
            {"ts": "2026-03-19T18:00:00+00:00", "author_id": "u1", "content": "Durante il Ramadan il digiuno vale anche se lavori tutto il giorno?", "meta": {}, "message_id": "444444444444444441"},
            {"ts": "2026-03-19T18:02:00+00:00", "author_id": "u2", "content": "Sì, ma ci sono eccezioni pratiche e il senso resta spirituale", "meta": {}, "message_id": "444444444444444442"},
        ],
        DEFAULT_SUMMARY_CONFIG,
        "role1",
        granularity_hint="hours",
    )

    assert moments
    assert "ramadan" in moments[0].text.lower() or "digiuno" in moments[0].text.lower()
    assert "spunti su" not in moments[0].text.lower()


def test_local_moment_keeps_primary_ref_even_when_summary_uses_bucket_context() -> None:
    service = SummaryService(database=_FakeDatabase())
    moments = service._extract_moments(
        [
            {"ts": "2026-03-19T07:00:00+00:00", "author_id": "u1", "content": "Buongiorno belle pollettine", "meta": {}, "message_id": "555555555555555551"},
            {"ts": "2026-03-19T07:02:00+00:00", "author_id": "u2", "content": "Raga oggi sono distrutta, non riesco a stare dietro a tutto", "meta": {}, "message_id": "555555555555555552"},
            {"ts": "2026-03-19T07:04:00+00:00", "author_id": "u3", "content": "Se vuoi ti diamo una mano a riorganizzare i task", "meta": {}, "message_id": "555555555555555553"},
        ],
        DEFAULT_SUMMARY_CONFIG,
        "role1",
        granularity_hint="hours",
    )

    assert moments
    assert moments[0].message_ids
    assert moments[0].message_ids[0] == "555555555555555552"
