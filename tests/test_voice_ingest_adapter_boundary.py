from pathlib import Path


def test_voice_ingest_does_not_reference_packet_router_internals() -> None:
    source = Path("app/plugins/voice_ingest.py").read_text()
    assert "PacketRouter" not in source
    assert "_do_run" not in source
    assert "._target" not in source
    assert "._args" not in source
