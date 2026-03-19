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
    "register_ask",
    "register_audio_notes",
    "register_attivita",
    "register_aura",
    "register_barcello",
    "register_attivita_settings",
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
    "add_group_once": "app.plugins.commands_modular.command_helpers",
    "add_command_once": "app.plugins.commands_modular.command_helpers",
    "describe_placeholders": "app.plugins.commands_modular.command_helpers",
    "check_permission": "app.plugins.commands_modular.permissions",
    "get_setting": "app.plugins.commands_modular.settings",
    "reset_setting": "app.plugins.commands_modular.settings",
    "set_setting": "app.plugins.commands_modular.settings",
    "register_admin": "app.plugins.commands_modular.admin",
    "register_ask": "app.plugins.commands_modular.ask",
    "register_audio_notes": "app.plugins.commands_modular.audio_notes",
    "register_attivita": "app.plugins.commands_modular.attivita",
    "register_aura": "app.plugins.commands_modular.aura",
    "register_barcello": "app.features.barcello.commands.barcello",
    "register_attivita_settings": "app.plugins.commands_modular.barcellometro_attivita",
    "register_privacy": "app.plugins.commands_modular.privacy",
    "register_resoconto": "app.features.summary.commands.resoconto",
    "register_riassunto": "app.features.summary.commands.riassunto",
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
