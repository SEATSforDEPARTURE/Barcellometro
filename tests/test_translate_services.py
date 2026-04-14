import sys
from types import SimpleNamespace

from app.services.translate.argos import ArgosTranslateService
from app.services.translate.opus_mt import OpusMtTranslateService
from app.services.translate.service import TranslationService


class _ArgosStub(ArgosTranslateService):
    async def translate(self, text, target_lang, *, source_lang=None, backend=None):
        _ = (source_lang, backend)
        return SimpleNamespace(text=f"argos:{text}", source_lang="en", target_lang=target_lang, backend="local", model="argos")


def test_opus_mt_lazy_loads_pipeline_once(monkeypatch) -> None:
    init_calls = {"count": 0}

    def _fake_pipeline(_task: str, model: str):
        init_calls["count"] += 1

        def _runner(text: str):
            return [{"translation_text": f"it::{text}::{model}"}]

        return _runner

    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(pipeline=_fake_pipeline))
    OpusMtTranslateService._pipeline = None
    OpusMtTranslateService._load_error = None
    svc = OpusMtTranslateService()

    async def _run() -> None:
        first = await svc.translate("hello", "it", source_lang="en")
        second = await svc.translate("world", "it", source_lang="en")
        assert first.text.startswith("it::hello")
        assert second.text.startswith("it::world")

    import asyncio

    asyncio.run(_run())
    assert init_calls["count"] == 1


def test_translation_service_routes_to_opus_backend(monkeypatch) -> None:
    class _OpusStub:
        async def translate(self, text, target_lang, *, source_lang=None, backend=None):
            _ = (target_lang, source_lang, backend)
            return SimpleNamespace(text=f"opus:{text}", source_lang="en", target_lang="it", backend="local", model="opus")

    service = TranslationService(argos=_ArgosStub(), ai=None, opus_mt=_OpusStub())

    async def _run() -> None:
        translated = await service.translate("hello", "it", source_lang="en", backend="opusmt")
        local = await service.translate("hello", "it", source_lang="en", backend="local")
        assert translated.text == "opus:hello"
        assert local.text == "argos:hello"

    import asyncio

    asyncio.run(_run())
