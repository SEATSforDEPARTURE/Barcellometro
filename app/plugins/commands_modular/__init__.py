from __future__ import annotations

from importlib import import_module

__all__ = [
    "CommandContext",
    "add_group_once",
    "add_command_once",
    "describe_placeholders",
    "check_permission",
    "get_setting",
    "reset_setting",
    "set_setting",
    "register_admin",
    "register_database",
    "register_ai",
    "register_ask",
    "register_audio_notes",
    "register_attivita",
    "register_embed",
    "register_greetings",
    "register_aura",
    "register_barcello",
    "register_privacy",
    "register_resoconto",
    "register_riassunto",
    "register_roles",
    "register_messaggi",
    "register_inattivi",
    "register_moderazione_utenti",
    "register_status",
    "register_stt",
    "register_translate",
    "register_triggers",
    "register_voice_ingest",
]

_MODULE_BY_ATTR = {
    "CommandContext": "app.plugins.commands_modular.ctx",
    "add_group_once": "app.plugins.commands_modular.registration",
    "add_command_once": "app.plugins.commands_modular.registration",
    "describe_placeholders": "app.plugins.commands_modular.placeholders",
    "check_permission": "app.plugins.commands_modular.permissions",
    "get_setting": "app.plugins.commands_modular.settings",
    "reset_setting": "app.plugins.commands_modular.settings",
    "set_setting": "app.plugins.commands_modular.settings",
    "register_admin": "app.plugins.commands_modular.admin",
    "register_database": "app.plugins.commands_modular.admin",
    "register_ai": "app.plugins.commands_modular.admin",
    "register_ask": "app.plugins.commands_modular.ask",
    "register_audio_notes": "app.plugins.commands_modular.audio_notes",
    "register_attivita": "app.plugins.commands_modular.attivita",
    "register_embed": "app.plugins.commands_modular.embed",
    "register_greetings": "app.plugins.commands_modular.greetings",
    "register_aura": "app.plugins.commands_modular.aura",
    "register_barcello": "app.plugins.commands_modular.barcello",
    "register_privacy": "app.plugins.commands_modular.privacy",
    "register_resoconto": "app.plugins.commands_modular.resoconto",
    "register_riassunto": "app.plugins.commands_modular.riassunto",
    "register_roles": "app.plugins.commands_modular.roles",
    "register_messaggi": "app.plugins.commands_modular.messaggi",
    "register_inattivi": "app.plugins.commands_modular.inattivi",
    "register_moderazione_utenti": "app.plugins.commands_modular.moderazione_utenti",
    "register_status": "app.plugins.commands_modular.status",
    "register_stt": "app.plugins.commands_modular.stt",
    "register_translate": "app.plugins.commands_modular.translate",
    "register_triggers": "app.plugins.commands_modular.triggers",
    "register_voice_ingest": "app.plugins.commands_modular.voice_ingest",
}


def __getattr__(name: str):
    module_name = _MODULE_BY_ATTR.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name)
    return getattr(module, name)
