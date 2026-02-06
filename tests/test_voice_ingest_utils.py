from app.plugins import voice_ingest


class _DummyPayload:
    def __init__(self, pcm: bytes | None = None) -> None:
        self.pcm = pcm


def test_extract_pcm_bytes_handles_bytes() -> None:
    payload = _DummyPayload(pcm=b"abc")
    assert voice_ingest._extract_pcm_bytes(payload) == b"abc"
    assert voice_ingest._extract_pcm_bytes(b"xyz") == b"xyz"
    assert voice_ingest._extract_pcm_bytes(None) is None


def test_install_opus_decode_guard_soft_fails_without_voice_recv() -> None:
    try:
        import discord.ext.voice_recv  # type: ignore  # noqa: F401
    except Exception:
        pass
    voice_ingest._install_opus_decode_guard()
