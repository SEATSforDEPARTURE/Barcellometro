from app.plugins import voice_ingest


class _DummyPayload:
    def __init__(self, pcm: bytes | None = None) -> None:
        self.pcm = pcm


def test_extract_pcm_bytes_handles_bytes() -> None:
    payload = _DummyPayload(pcm=b"abc")
    assert voice_ingest._extract_pcm_bytes(payload) == b"abc"
    assert voice_ingest._extract_pcm_bytes(b"xyz") == b"xyz"
    assert voice_ingest._extract_pcm_bytes(None) is None
