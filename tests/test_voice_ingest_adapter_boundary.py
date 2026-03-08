from pathlib import Path


def test_voice_ingest_does_not_reference_packet_router_internals() -> None:
    source = Path("app/plugins/voice_ingest.py").read_text()
    assert "PacketRouter" not in source
    assert "_do_run" not in source
    assert "._target" not in source
    assert "._args" not in source


def test_voice_ingest_decode_storm_recovery_is_single_flight() -> None:
    source = Path("app/plugins/voice_ingest.py").read_text()
    assert "decode_storm_recovery_task is None or decode_storm_recovery_task.done()" in source
    assert "decode storm recovery already scheduled" in source


def test_voice_ingest_decode_storm_recovery_resets_runtime_buffers() -> None:
    source = Path("app/plugins/voice_ingest.py").read_text()
    assert "_clear_voice_runtime_buffers(keep_counters=False)" in source
    assert "failed_decode_storm" in source


def test_voice_ingest_decode_storm_recovery_is_limited_to_one_attempt() -> None:
    source = Path("app/plugins/voice_ingest.py").read_text()
    assert "MAX_DECODE_STORM_RECOVERIES = 1" in source
    assert "failed_decode_storm_recovery_exhausted" in source
