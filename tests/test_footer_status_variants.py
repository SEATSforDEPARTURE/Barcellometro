import sys
import types
from pathlib import Path

if "aiosqlite" not in sys.modules:
    sys.modules["aiosqlite"] = types.SimpleNamespace(Connection=object)
if "httpx" not in sys.modules:
    httpx_stub = types.ModuleType("httpx")

    class _AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def get(self, *args, **kwargs):
            raise RuntimeError("httpx stub: network call not configured in this test")

    httpx_stub.AsyncClient = _AsyncClient
    sys.modules["httpx"] = httpx_stub

from app.shared.discord.embed_status_helpers import _chunk_status_blocks, _service_section, _split_long_text


def test_footer_status_groups_campaign_sections_separately() -> None:
    assert _service_section("campagne_notizie") == 1
    assert _service_section("campagne_meteo") == 1
    assert _service_section("campagne_oroscopo") == 1
    assert _service_section("campagne_prompt") == 2
    assert _service_section("campagne_timer") == 3
    assert _service_section("audio_notes") == 0


def test_footer_status_source_uses_variants_and_excludes_legacy_campagne() -> None:
    source = Path("app/plugins/commands_modular/embed.py").read_text()
    assert "get_all_service_footer_variants" in source
    assert "Editorial campaigns" in source
    assert "Prompt campaigns" in source
    assert "Timer campaigns" in source
    assert 'service_name="campagne"' not in source


def test_message_scheduler_uses_prompt_vs_timer_footer_service() -> None:
    source = Path("app/services/message_scheduler.py").read_text()
    assert "def _campaign_footer_service_name" in source
    assert 'return "campagne_prompt" if str(campaign_type or "").upper() == "AI_PROMPT" else "campagne_timer"' in source


def test_split_long_text_handles_very_long_line() -> None:
    text = "a" * 4500
    parts = _split_long_text(text, max_len=1900)
    assert len(parts) == 3
    assert all(len(part) <= 1900 for part in parts)


def test_chunk_status_blocks_handles_big_block_and_long_line() -> None:
    blocks = [
        "blocco breve",
        "riga1\n" + ("x" * 2200) + "\n" + ("y" * 2100),
        "blocco finale",
    ]
    chunks = _chunk_status_blocks(blocks, max_len=1900)
    assert chunks
    assert all(0 < len(chunk) <= 1900 for chunk in chunks)


def test_chunk_status_blocks_scales_with_many_services() -> None:
    blocks = [f"**service_{idx}**\nvariante: local | model\n→ footer" for idx in range(200)]
    chunks = _chunk_status_blocks(blocks, max_len=1900)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 1900 for chunk in chunks)
