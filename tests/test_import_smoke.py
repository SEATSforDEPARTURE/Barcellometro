import importlib
import sys
import types


def test_import_smoke_scheduler_campaign_bot() -> None:
    sys.modules.setdefault("aiosqlite", types.ModuleType("aiosqlite"))

    openai_module = types.ModuleType("openai")
    openai_module.AsyncOpenAI = object
    sys.modules.setdefault("openai", openai_module)

    faster_whisper_module = types.ModuleType("faster_whisper")
    faster_whisper_module.WhisperModel = object
    sys.modules.setdefault("faster_whisper", faster_whisper_module)

    argos_module = types.ModuleType("argostranslate")
    argos_translate_module = types.ModuleType("argostranslate.translate")
    argos_module.translate = argos_translate_module
    sys.modules.setdefault("argostranslate", argos_module)
    sys.modules.setdefault("argostranslate.translate", argos_translate_module)

    importlib.import_module("app.services.message_scheduler")
    importlib.import_module("app.services.campaign_content_service")
    importlib.import_module("app.core.bot")
