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
    assert contributors == ["stt-model", "tr-model", "sum-model"]
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


def test_loading_embed_uses_standard_title_and_italic_description_without_leading_emoji(audio_notes_module) -> None:
    embed = audio_notes_module._build_audio_note_embed(
        audio_notes_module._audio_loading_description(),
        user_display_name="Mario",
    )
    assert embed.title == "🗣️ __**NOTA AUDIO**__"
    assert embed.description == "_Nota audio ricevuta, sto trascrivendo..._"
    assert not embed.description.startswith("*🎙️")
    assert "<@" not in embed.title


def test_final_embed_description_includes_bold_and_italic_user_and_ordinal_when_available(audio_notes_module) -> None:
    sections = audio_notes_module._build_audio_note_sections(
        transcript_text="testo trascritto",
        detected_lang="en",
        translation_text="testo tradotto",
        summary_text="riassunto breve",
    )
    embeds = audio_notes_module._build_audio_note_embeds_from_sections(
        sections,
        user_display_name="Criceto Mannaro",
        ordinal_label="secondo",
    )
    assert embeds
    first = embeds[0]
    assert first.description == "*Leggiamo cosa ci dice* ***Criceto Mannaro*** *in quest'audio...* *È il* ***secondo*** *di oggi.*"
    assert "***Criceto Mannaro***" in first.description
    assert "***secondo***" in first.description
    assert "**Criceto Mannaro**" not in first.description.replace("***Criceto Mannaro***", "")
    assert "Trascrizione audio elaborata" not in first.description
    assert "<@" not in first.description
    field_names = [field.name for field in first.fields]
    assert all("SEZIONE" not in name for name in field_names)
    assert all("1/2" not in name and "2/2" not in name for name in field_names)
    assert any("TRASCRIZIONE" in name for name in field_names)


def test_final_embed_description_fallback_without_ordinal_is_human_and_italic(audio_notes_module) -> None:
    sections = audio_notes_module._build_audio_note_sections(
        transcript_text="testo trascritto",
        detected_lang="it",
        translation_text=None,
        summary_text=None,
    )
    embeds = audio_notes_module._build_audio_note_embeds_from_sections(
        sections,
        user_display_name="Mario",
        ordinal_label=None,
    )
    assert embeds[0].description == "*Leggiamo cosa ci dice* ***Mario*** *in quest'audio...*"




def test_audio_note_title_and_description_clean_decorative_nickname_and_keep_markdown_valid(audio_notes_module) -> None:
    embed = audio_notes_module._build_audio_note_embed(
        audio_notes_module._audio_final_description(user_ref="🐹@🐭 CRICETO MANNARO**", ordinal_label="terzo"),
        user_display_name="🐹@🐭 CRICETO MANNARO",
    )

    assert embed.title == "🗣️ __**NOTA AUDIO**__"
    assert "🐹" not in embed.title and "🐭" not in embed.title
    assert embed.description.startswith("*") and embed.description.endswith("*")
    assert embed.description.count("*") % 2 == 0
    assert "\\*\\*" not in embed.description
    assert "***CRICETO MANNARO***" in embed.description


def test_audio_final_description_sanitizes_markdown_and_keeps_tripled_markdown_segments(audio_notes_module) -> None:
    rendered = audio_notes_module._audio_final_description(user_ref="Cr*ic_eto` ~~", ordinal_label="quinto")

    assert rendered.startswith("*Leggiamo cosa ci dice* ")
    assert "***Cric\\_eto***" in rendered
    assert "***quinto***" in rendered
    assert "~~" not in rendered
    assert "`" not in rendered
    assert "*Leggiamo cosa ci dice **" not in rendered

def test_audio_user_display_name_never_returns_mention_or_raw_id(audio_notes_module) -> None:
    user = SimpleNamespace(display_name="Mario_**<@123>", name="fallback", mention="<@123456789012345678>", id=123456789012345678)
    rendered = audio_notes_module._audio_user_display_name(user)

    assert rendered == "Mario\\_\\*\\*<@123>"
    assert rendered != user.mention
    assert "<@123456789012345678>" not in rendered


def test_audio_embeds_keep_single_message_payload_with_multiple_embeds(audio_notes_module) -> None:
    sections = []
    for index in range(30):
        sections.append((f"Trascrizione {index}", "✍️", f"contenuto {index}"))

    embeds = audio_notes_module._build_audio_note_embeds_from_sections(
        sections,
        user_display_name="Mario",
        ordinal_label="primo",
    )

    assert len(embeds) == 2
    assert sum(len(embed.fields) for embed in embeds) == 30
    assert all("<@" not in (embed.title or "") for embed in embeds)


def test_audio_embed_author_pagination_is_applied_in_author_not_in_section_titles(audio_notes_module) -> None:
    async def _run() -> None:
        sections = []
        for index in range(30):
            sections.append(("Trascrizione", "✍️", f"contenuto {index}"))

        embeds = audio_notes_module._build_audio_note_embeds_from_sections(
            sections,
            user_display_name="Mario",
            ordinal_label="primo",
        )
        assert len(embeds) == 2

        await audio_notes_module.finalize_embeds_rendering(
            embeds,
            footer_service=None,
            author_service=None,
            default_service_name="audio_notes",
        )

        assert embeds[0].author.name == "servizio AUDIO · (Pag. 1/2)"
        assert embeds[1].author.name == "servizio AUDIO · (Pag. 2/2)"
        assert embeds[0].footer.text == embeds[1].footer.text
        assert all("SEZIONE" not in field.name for embed in embeds for field in embed.fields)

    asyncio.run(_run())


def test_audio_ordinal_label_returns_expected_values(audio_notes_module) -> None:
    assert audio_notes_module._audio_ordinal_label(1) == "primo"
    assert audio_notes_module._audio_ordinal_label(2) == "secondo"
    assert audio_notes_module._audio_ordinal_label(6) == "6º"
    assert audio_notes_module._audio_ordinal_label(9) == "9º"
    assert audio_notes_module._audio_ordinal_label(None) is None
