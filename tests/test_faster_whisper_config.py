from __future__ import annotations

import importlib
import inspect
import sys
import types


def _load_module_with_fake_whisper(signature: str):
    class FakeWhisperModel:
        def __init__(self, model: str, compute_type: str) -> None:
            self.model = model
            self.compute_type = compute_type

    namespace: dict[str, object] = {}
    exec(f"def transcribe(self, audio_path, {signature}):\n    return [], types.SimpleNamespace(language='it')", {"types": types}, namespace)
    FakeWhisperModel.transcribe = namespace["transcribe"]  # type: ignore[assignment]

    fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
    sys.modules["faster_whisper"] = fake_module

    mod_name = "app.services.stt.faster_whisper"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return importlib.import_module(mod_name)


class _DummyDB:
    async def get_setting(self, key: str):
        return None


def test_build_kwargs_uses_only_supported_params(monkeypatch) -> None:
    module = _load_module_with_fake_whisper("beam_size=1, language=None")
    service = module.FasterWhisperSttService(_DummyDB())
    config = module._SttConfig(model="small", compute_type="int8", beam_size=1, language_hint="auto")
    model = module.WhisperModel("small", compute_type="int8")

    kwargs = service._build_transcribe_kwargs(model, config, language="it")

    assert kwargs == {"beam_size": 1, "language": "it"}


def test_build_kwargs_adds_conservative_options_when_supported(monkeypatch) -> None:
    module = _load_module_with_fake_whisper(
        "beam_size=1, language=None, condition_on_previous_text=True, vad_filter=False, temperature=0.0, no_speech_threshold=0.6"
    )
    monkeypatch.setenv("STT_LOCAL_VAD_FILTER", "true")
    service = module.FasterWhisperSttService(_DummyDB())
    config = module._SttConfig(model="small", compute_type="int8", beam_size=1, language_hint="auto")
    model = module.WhisperModel("small", compute_type="int8")

    kwargs = service._build_transcribe_kwargs(model, config, language=None)

    assert kwargs["beam_size"] == 1
    assert kwargs["language"] is None
    assert kwargs["condition_on_previous_text"] is False
    assert kwargs["vad_filter"] is True
    assert kwargs["temperature"] == 0.0
    assert kwargs["no_speech_threshold"] == 0.65

    supported = set(inspect.signature(model.transcribe).parameters)
    assert set(kwargs).issubset(supported)
