import importlib.util
import asyncio
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

imageio_ffmpeg_stub = types.ModuleType("imageio_ffmpeg")
imageio_ffmpeg_stub.get_ffmpeg_exe = lambda: ""
sys.modules.setdefault("imageio_ffmpeg", imageio_ffmpeg_stub)

footer_stub = types.ModuleType("app.services.footer")
footer_stub.attach_footer_meta = lambda embed, **kwargs: embed
sys.modules["app.services.footer"] = footer_stub

module_path = Path(__file__).resolve().parents[1] / "app" / "plugins" / "audio_notes_transcribe.py"
spec = importlib.util.spec_from_file_location("audio_notes_transcribe_module_for_tests", module_path)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_should_not_generate_summary_if_threshold_not_exceeded() -> None:
    assert not mod._should_generate_audio_summary("testo abbastanza lungo", 100)


def test_build_audio_note_summary_and_output_when_threshold_exceeded() -> None:
    async def _run() -> None:
        responses = SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(output_text="Riassunto breve.")))
        client = SimpleNamespace(responses=responses)
        ai_service = SimpleNamespace(
            is_enabled=lambda: True,
            client=lambda: client,
            get_model=lambda task: "gpt-4o-mini" if task in {"summary", "audio_summary"} else None,
        )

        summary_text, summary_model = await mod._build_audio_note_summary(ai_service, "x" * 80)

        assert summary_text == "Riassunto breve."
        assert summary_model == "gpt-4o-mini"

        output = mod._build_audio_note_output(
            transcript_text="trascrizione originale",
            detected_lang="en",
            translation_text="traduzione italiana",
            summary_text=summary_text,
        )
        assert "⏲️ **Riassunto:**" in output
        assert output.index("**🇮🇹 Traduzione:**") < output.index("⏲️ **Riassunto:**")

    asyncio.run(_run())


def test_build_audio_note_summary_failure_does_not_break_flow() -> None:
    async def _run() -> None:
        responses = SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom")))
        client = SimpleNamespace(responses=responses)
        ai_service = SimpleNamespace(
            is_enabled=lambda: True,
            client=lambda: client,
            get_model=lambda task: "gpt-4o-mini" if task in {"summary", "audio_summary"} else None,
        )

        summary_text, summary_model = await mod._build_audio_note_summary(ai_service, "x" * 80)

        assert summary_text is None
        assert summary_model is None

        output = mod._build_audio_note_output(
            transcript_text="trascrizione originale",
            detected_lang="en",
            translation_text="traduzione italiana",
            summary_text=summary_text,
        )
        assert "**✍️ Trascrizione:**" in output
        assert "**🇮🇹 Traduzione:**" in output
        assert "⏲️ **Riassunto:**" not in output

    asyncio.run(_run())


def test_footer_includes_summary_model_only_when_present() -> None:
    contributors, used_local = mod._build_audio_footer_contributors(
        stt_backend_used="ai",
        stt_model="stt-model",
        translate_backend_used="ai",
        translation_model="tr-model",
        has_translation_text=True,
        summary_model="sum-model",
    )
    assert contributors == ["stt-model", "tr-model", "sum-model"]
    assert not used_local

    contributors_no_summary, used_local_no_summary = mod._build_audio_footer_contributors(
        stt_backend_used="local",
        stt_model="stt-model",
        translate_backend_used="ai",
        translation_model="tr-model",
        has_translation_text=False,
        summary_model=None,
    )
    assert contributors_no_summary == ["stt-model"]
    assert used_local_no_summary


def test_parse_chars_summary_limit_non_positive_disables_feature() -> None:
    assert mod._parse_chars_summary_limit("") == 0
    assert mod._parse_chars_summary_limit("0") == 0
    assert mod._parse_chars_summary_limit("-10") == 0
    assert mod._parse_chars_summary_limit("1200") == 1200


def test_build_audio_note_summary_prefers_audio_summary_model() -> None:
    async def _run() -> None:
        responses = SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(output_text="Riassunto audio.")))
        client = SimpleNamespace(responses=responses)
        ai_service = SimpleNamespace(
            is_enabled=lambda: True,
            client=lambda: client,
            get_model=lambda task: {"audio_summary": "gpt-4.1-mini", "summary": "gpt-4o-mini"}.get(task),
        )

        summary_text, summary_model = await mod._build_audio_note_summary(ai_service, "x" * 120)

        assert summary_text == "Riassunto audio."
        assert summary_model == "gpt-4.1-mini"
        responses.create.assert_awaited_once()
        assert responses.create.await_args.kwargs["model"] == "gpt-4.1-mini"

    asyncio.run(_run())


def test_build_audio_note_summary_fallbacks_to_summary_then_default() -> None:
    async def _run_summary_fallback() -> None:
        responses = SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(output_text="Riassunto fallback.")))
        client = SimpleNamespace(responses=responses)
        ai_service = SimpleNamespace(
            is_enabled=lambda: True,
            client=lambda: client,
            get_model=lambda task: "gpt-4o-mini" if task == "summary" else None,
        )

        _, summary_model = await mod._build_audio_note_summary(ai_service, "x" * 120)
        assert summary_model == "gpt-4o-mini"
        assert responses.create.await_args.kwargs["model"] == "gpt-4o-mini"

    async def _run_default_fallback() -> None:
        responses = SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(output_text="Riassunto fallback default.")))
        client = SimpleNamespace(responses=responses)
        ai_service = SimpleNamespace(
            is_enabled=lambda: True,
            client=lambda: client,
            get_model=lambda task: None,
        )

        _, summary_model = await mod._build_audio_note_summary(ai_service, "x" * 120)
        assert summary_model == "gpt-4o-mini"
        assert responses.create.await_args.kwargs["model"] == "gpt-4o-mini"

    asyncio.run(_run_summary_fallback())
    asyncio.run(_run_default_fallback())
