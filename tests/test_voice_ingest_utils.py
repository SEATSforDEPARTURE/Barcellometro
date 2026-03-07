from __future__ import annotations

import sys
import types

sys.modules.setdefault("aiosqlite", types.SimpleNamespace(IntegrityError=Exception))

from app.plugins import voice_ingest


class _DummyPayload:
    def __init__(self, pcm: bytes | None = None) -> None:
        self.pcm = pcm


def test_extract_pcm_bytes_handles_bytes() -> None:
    payload = _DummyPayload(pcm=b"abc")
    assert voice_ingest._extract_pcm_bytes(payload) == b"abc"
    assert voice_ingest._extract_pcm_bytes(b"xyz") == b"xyz"
    assert voice_ingest._extract_pcm_bytes(None) is None


def test_should_log_corruption_event_is_rate_limited() -> None:
    assert voice_ingest._should_log_corruption_event(1) is True
    assert voice_ingest._should_log_corruption_event(voice_ingest.OPUS_WARNING_LOG_FIRST) is True
    assert voice_ingest._should_log_corruption_event(voice_ingest.OPUS_WARNING_LOG_FIRST + 1) is False
    assert voice_ingest._should_log_corruption_event(voice_ingest.OPUS_WARNING_LOG_EVERY) is True


def test_evaluate_chunk_quality_discards_short_or_corrupted() -> None:
    ok, reason = voice_ingest._evaluate_chunk_quality(
        pcm_bytes=voice_ingest.MIN_PCM_BYTES,
        duration_sec=0.2,
        total_frames=50,
        corrupted_frames=0,
    )
    assert ok is False
    assert reason.startswith("duration<")

    ok, reason = voice_ingest._evaluate_chunk_quality(
        pcm_bytes=voice_ingest.MIN_PCM_BYTES,
        duration_sec=2.0,
        total_frames=100,
        corrupted_frames=90,
    )
    assert ok is False
    assert reason.startswith("corruption_ratio>")


def test_evaluate_chunk_quality_accepts_valid_chunk() -> None:
    ok, reason = voice_ingest._evaluate_chunk_quality(
        pcm_bytes=voice_ingest.MIN_PCM_BYTES + 1000,
        duration_sec=2.0,
        total_frames=100,
        corrupted_frames=2,
    )
    assert ok is True
    assert reason == "ok"


def test_install_opus_decode_guard_idempotent(monkeypatch) -> None:
    class DummyOpusError(Exception):
        pass

    class DummyDecoder:
        def _decode_packet(self, packet):
            return packet, b"ok"

    fake_voice_recv_opus = types.SimpleNamespace(OpusDecoder=DummyDecoder)
    monkeypatch.setitem(sys.modules, "discord.ext.voice_recv.opus", fake_voice_recv_opus)

    fake_discord_opus = types.SimpleNamespace(OpusError=DummyOpusError)
    monkeypatch.setitem(sys.modules, "discord.opus", fake_discord_opus)

    monkeypatch.setattr(voice_ingest, "_OPUS_GUARD_INSTALLED", False)

    voice_ingest._install_opus_decode_guard()
    first = DummyDecoder._decode_packet
    voice_ingest._install_opus_decode_guard()
    second = DummyDecoder._decode_packet
    assert first is second
