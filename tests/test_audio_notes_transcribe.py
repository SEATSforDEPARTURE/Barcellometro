import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def audio_notes_module(monkeypatch):
    imageio_ffmpeg_stub = types.ModuleType("imageio_ffmpeg")
    imageio_ffmpeg_stub.get_ffmpeg_exe = lambda: ""
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", imageio_ffmpeg_stub)

    footer_stub = types.ModuleType("app.services.footer")
    footer_stub.attach_footer_meta = lambda embed, **kwargs: embed
    monkeypatch.setitem(sys.modules, "app.services.footer", footer_stub)

    service_registry_stub = types.ModuleType("app.core.service_registry")
    service_registry_stub.ServiceRegistry = object
    monkeypatch.setitem(sys.modules, "app.core.service_registry", service_registry_stub)

    module_path = Path(__file__).resolve().parents[1] / "app" / "plugins" / "audio_notes_transcribe.py"
    spec = importlib.util.spec_from_file_location("audio_notes_transcribe_module_for_tests", module_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_should_not_generate_summary_if_threshold_not_exceeded(audio_notes_module) -> None:
    assert not audio_notes_module._should_generate_audio_summary("testo abbastanza lungo", 100)


def test_sanitize_transcript_for_summary_replaces_offensive_terms(audio_notes_module) -> None:
    original = "Sei una stronza e rompi il cazzo, vaffanculo. Che merda."
    sanitized = audio_notes_module._sanitize_transcript_for_summary(original)

    assert "stronza" not in sanitized.lower()
    assert "rompi il cazzo" not in sanitized.lower()
    assert "vaffanculo" not in sanitized.lower()
    assert "merda" not in sanitized.lower()
    assert "[insulto]" in sanitized
    assert "[espressione volgare]" in sanitized
    assert "[offesa]" in sanitized
    assert "[volgarità]" in sanitized
    assert sanitized.strip()


def test_looks_like_summary_refusal_detects_refusal_phrases(audio_notes_module) -> None:
    refusal = "Non posso fornire un riassunto che contiene parole offensive. Posso aiutarti con qualcos'altro?"
    normal_summary = "Una persona racconta un episodio in modo agitato e usa toni accesi."

    assert audio_notes_module._looks_like_summary_refusal(refusal)
    assert not audio_notes_module._looks_like_summary_refusal(normal_summary)


def test_build_audio_note_summary_and_output_when_threshold_exceeded(audio_notes_module) -> None:
    async def _run() -> None:
        ai_service = SimpleNamespace(
            is_enabled=lambda: True,
            ask_for_task=AsyncMock(return_value="Riassunto breve."),
            get_model_display_name=lambda task: "gpt-4o-mini" if task == "audio_summary" else None,
        )

        summary_text, summary_model = await audio_notes_module._build_audio_note_summary(ai_service, "x" * 80)

        assert summary_text == "Riassunto breve."
        assert summary_model == "gpt-4o-mini"

        output = audio_notes_module._build_audio_note_output(
            transcript_text="trascrizione originale",
            detected_lang="en",
            translation_text="traduzione italiana",
            summary_text=summary_text,
        )
        assert "⏲️ **Riassunto:**" in output
        assert output.index("**🇮🇹 Traduzione:**") < output.index("⏲️ **Riassunto:**")

    asyncio.run(_run())


def test_build_audio_note_summary_failure_does_not_break_flow(audio_notes_module) -> None:
    async def _run() -> None:
        ai_service = SimpleNamespace(
            is_enabled=lambda: True,
            ask_for_task=AsyncMock(side_effect=RuntimeError("boom")),
            get_model_display_name=lambda task: "gpt-4o-mini" if task == "audio_summary" else None,
        )

        summary_text, summary_model = await audio_notes_module._build_audio_note_summary(ai_service, "x" * 80)

        assert summary_text is None
        assert summary_model is None

        output = audio_notes_module._build_audio_note_output(
            transcript_text="trascrizione originale",
            detected_lang="en",
            translation_text="traduzione italiana",
            summary_text=summary_text,
        )
        assert "**✍️ Trascrizione:**" in output
        assert "**🇮🇹 Traduzione:**" in output
        assert "⏲️ **Riassunto:**" not in output

    asyncio.run(_run())


def test_build_audio_note_summary_skips_refusal_output(audio_notes_module) -> None:
    async def _run() -> None:
        ai_service = SimpleNamespace(
            is_enabled=lambda: True,
            ask_for_task=AsyncMock(
                side_effect=[
                    "Non posso fornire un riassunto che contiene linguaggio offensivo.",
                    "Mi dispiace, non posso aiutarti con questo contenuto offensivo.",
                ]
            ),
            get_model_display_name=lambda task: "gpt-4o-mini" if task == "audio_summary" else None,
        )

        summary_text, summary_model = await audio_notes_module._build_audio_note_summary(ai_service, "x" * 120)

        assert summary_text is None
        assert summary_model is None

    asyncio.run(_run())


def test_build_audio_note_summary_retries_after_refusal_and_returns_second_valid_summary(audio_notes_module) -> None:
    async def _run() -> None:
        valid_summary = "Una persona racconta in modo volgare una versione ironica di Cenerentola e del suo desiderio di essere mantenuta."
        ai_service = SimpleNamespace(
            is_enabled=lambda: True,
            ask_for_task=AsyncMock(
                side_effect=[
                    "Non posso riassumere contenuto offensivo. Posso aiutarti con qualcos'altro?",
                    valid_summary,
                ]
            ),
            get_model_display_name=lambda task: "gpt-4o-mini" if task == "audio_summary" else None,
        )

        summary_text, summary_model = await audio_notes_module._build_audio_note_summary(ai_service, "x" * 120)

        assert summary_text == valid_summary
        assert summary_model == "gpt-4o-mini"

    asyncio.run(_run())


def test_build_audio_note_output_does_not_include_summary_section_when_summary_is_none(audio_notes_module) -> None:
    output = audio_notes_module._build_audio_note_output(
        transcript_text="trascrizione originale",
        detected_lang="en",
        translation_text="traduzione italiana",
        summary_text=None,
    )
    assert "⏲️ **Riassunto:**" not in output


def test_footer_includes_summary_model_only_when_present(audio_notes_module) -> None:
    contributors, used_local = audio_notes_module._build_audio_footer_contributors(
        stt_backend_used="ai",
        stt_model="stt-model",
        translate_backend_used="ai",
        translation_model="tr-model",
        has_translation_text=True,
        summary_model="sum-model",
    )
    assert contributors == ["sum-model"]
    assert not used_local

    contributors_no_summary, used_local_no_summary = audio_notes_module._build_audio_footer_contributors(
        stt_backend_used="local",
        stt_model="stt-model",
        translate_backend_used="ai",
        translation_model="tr-model",
        has_translation_text=False,
        summary_model=None,
    )
    assert contributors_no_summary == ["stt-model"]
    assert used_local_no_summary


def test_parse_chars_summary_limit_non_positive_disables_feature(audio_notes_module) -> None:
    assert audio_notes_module._parse_chars_summary_limit("") == 0
    assert audio_notes_module._parse_chars_summary_limit("0") == 0
    assert audio_notes_module._parse_chars_summary_limit("-10") == 0
    assert audio_notes_module._parse_chars_summary_limit("1200") == 1200
