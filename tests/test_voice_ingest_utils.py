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


def test_opus_detail_warning_rate_limited_to_first_events() -> None:
    assert voice_ingest._should_log_corruption_event(1) is True
    assert voice_ingest._should_log_corruption_event(voice_ingest.OPUS_WARNING_LOG_FIRST) is True
    assert voice_ingest._should_log_corruption_event(voice_ingest.OPUS_WARNING_LOG_FIRST + 1) is False


def test_opus_periodic_summary_interval_helper() -> None:
    assert voice_ingest._should_emit_periodic_summary(31.0, 0.0, interval_sec=30) is True
    assert voice_ingest._should_emit_periodic_summary(29.9, 0.0, interval_sec=30) is False


def test_safe_average_handles_zero_count() -> None:
    assert voice_ingest._safe_average(10.0, 0) == 0.0
    assert voice_ingest._safe_average(9.0, 3) == 3.0


def test_evaluate_chunk_quality_discards_short_or_corrupted() -> None:
    ok, reason = voice_ingest._evaluate_chunk_quality(
        pcm_bytes=voice_ingest.MIN_PCM_BYTES,
        duration_sec=0.2,
        total_frames=50,
        corrupted_frames=0,
        non_silent_frames=10,
        avg_rms=500.0,
        rms_min=100.0,
        rms_max=1000.0,
    )
    assert ok is False
    assert reason.startswith("duration<")

    ok, reason = voice_ingest._evaluate_chunk_quality(
        pcm_bytes=voice_ingest.MIN_PCM_BYTES,
        duration_sec=2.0,
        total_frames=100,
        corrupted_frames=90,
        non_silent_frames=80,
        avg_rms=500.0,
        rms_min=100.0,
        rms_max=1000.0,
        max_corruption_ratio=0.45,
    )
    assert ok is False
    assert reason == "high_corruption"


def test_evaluate_chunk_quality_accepts_valid_chunk() -> None:
    ok, reason = voice_ingest._evaluate_chunk_quality(
        pcm_bytes=voice_ingest.MIN_PCM_BYTES + 1000,
        duration_sec=2.0,
        total_frames=100,
        corrupted_frames=2,
        non_silent_frames=60,
        avg_rms=700.0,
        rms_min=120.0,
        rms_max=2200.0,
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


def test_known_corrupted_opus_error_tokens() -> None:
    assert voice_ingest._is_known_corrupted_opus_error(Exception("invalid argument")) is True
    assert voice_ingest._is_known_corrupted_opus_error(Exception("corrupted stream")) is True
    assert voice_ingest._is_known_corrupted_opus_error(Exception("buffer too small")) is True
    assert voice_ingest._is_known_corrupted_opus_error(Exception("decode failed")) is True


def test_install_opus_decode_guard_swallows_repeated_invalid_argument(monkeypatch) -> None:
    class DummyOpusError(Exception):
        pass

    class DummyDecoder:
        def _decode_packet(self, packet):
            raise DummyOpusError("invalid argument")

    fake_voice_recv = types.ModuleType("discord.ext.voice_recv")
    fake_voice_recv.opus = types.SimpleNamespace(OpusDecoder=DummyDecoder)
    monkeypatch.setitem(sys.modules, "discord.ext.voice_recv", fake_voice_recv)
    monkeypatch.setitem(sys.modules, "discord.ext.voice_recv.opus", fake_voice_recv.opus)

    fake_discord_opus = types.ModuleType("discord.opus")
    fake_discord_opus.OpusError = DummyOpusError
    monkeypatch.setitem(sys.modules, "discord.opus", fake_discord_opus)

    monkeypatch.setattr(voice_ingest, "_OPUS_GUARD_INSTALLED", False)
    monkeypatch.setattr(voice_ingest, "_OPUS_GUARD_CORRUPTED_COUNT", 0)

    voice_ingest._install_opus_decode_guard()
    decoder = DummyDecoder()
    packet = object()

    for _ in range(10):
        returned_packet, decoded = decoder._decode_packet(packet)
        assert returned_packet is packet
        assert decoded == b""

    assert voice_ingest._OPUS_GUARD_CORRUPTED_COUNT == 10


def test_configurable_max_corruption_ratio_env(monkeypatch) -> None:
    monkeypatch.setenv(voice_ingest.VOICE_INGEST_MAX_CORRUPTION_RATIO_ENV, "0.52")
    assert voice_ingest._get_configured_max_corruption_ratio() == 0.52
    monkeypatch.setenv(voice_ingest.VOICE_INGEST_MAX_CORRUPTION_RATIO_ENV, "bad")
    assert voice_ingest._get_configured_max_corruption_ratio() == voice_ingest.MAX_CORRUPTION_RATIO


def test_count_error_matches_for_summary() -> None:
    counts = {
        "opuserror('corrupted stream')": 3,
        "invalid argument": 2,
        "something else": 4,
    }
    assert voice_ingest._count_error_matches(counts, "corrupted stream") == 3
    assert voice_ingest._count_error_matches(counts, "invalid argument") == 2


def test_hallucination_filter_blocks_amara_boilerplate_variants() -> None:
    blocked, reason = voice_ingest._is_likely_hallucinated_text("Sottotitoli creati dalla comunità Amara.org")
    assert blocked is True
    assert reason == "boilerplate"

    blocked, reason = voice_ingest._is_likely_hallucinated_text("  sottotitoli   creati dalla comunita amara org!!! ")
    assert blocked is True
    assert reason == "boilerplate"


def test_normalize_text_for_match_is_case_and_punctuation_insensitive() -> None:
    assert (
        voice_ingest._normalize_text_for_match("SOTTOTITOLI, creati dalla comunità Amara.org!!!")
        == "sottotitoli creati dalla comunita amara org"
    )


def test_evaluate_chunk_quality_rejects_low_speech_or_noise_only() -> None:
    ok, reason = voice_ingest._evaluate_chunk_quality(
        pcm_bytes=voice_ingest.MIN_PCM_BYTES + 1024,
        duration_sec=2.0,
        total_frames=100,
        corrupted_frames=0,
        non_silent_frames=5,
        avg_rms=500.0,
        rms_min=490.0,
        rms_max=520.0,
    )
    assert ok is False
    assert reason in {"low_speech", "likely_noise_only"}


def test_repeated_text_guard_rejects_duplicate_burst() -> None:
    cache: dict[int, dict[str, list[float]]] = {}
    assert (
        voice_ingest._should_reject_repeated_text(
            cache=cache,
            user_id=123,
            normalized_text="hello world",
            now_ts=1.0,
            window_sec=120,
            max_repeats=3,
        )
        is False
    )
    assert (
        voice_ingest._should_reject_repeated_text(
            cache=cache,
            user_id=123,
            normalized_text="hello world",
            now_ts=2.0,
            window_sec=120,
            max_repeats=3,
        )
        is False
    )
    assert (
        voice_ingest._should_reject_repeated_text(
            cache=cache,
            user_id=123,
            normalized_text="hello world",
            now_ts=3.0,
            window_sec=120,
            max_repeats=3,
        )
        is False
    )
    assert (
        voice_ingest._should_reject_repeated_text(
            cache=cache,
            user_id=123,
            normalized_text="hello world",
            now_ts=4.0,
            window_sec=120,
            max_repeats=3,
        )
        is True
    )


def test_known_boilerplate_regex_blocks_variants() -> None:
    assert voice_ingest._is_known_boilerplate_text("Sottotitoli -- creati, dalla comunita: Amara org") is True
    assert voice_ingest._is_known_boilerplate_text("testo normale") is False


def test_session_summary_is_coherent() -> None:
    summary = voice_ingest._build_session_summary(
        chunks_processed=10,
        chunks_dropped=3,
        chunks_enqueued=2,
        chunks_sent_to_stt=5,
        chunks_saved_to_db=7,
        stt_success_count=1,
        stt_empty_count=1,
        stt_hallucinated_chunks=1,
        stt_rejected_boilerplate=1,
        chunks_dropped_high_corruption=2,
        chunks_dropped_low_speech=1,
        chunks_dropped_low_rms=0,
        opus_corrupted_total=9,
        avg_corruption_ratio=0.5,
    )
    assert summary["chunks_sent_to_stt"] == 2
    assert summary["chunks_saved_to_db"] == 2


def test_safe_increment_does_not_raise() -> None:
    voice_ingest._safe_increment("bad_metric", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
