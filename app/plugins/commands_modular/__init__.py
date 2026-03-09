from .admin import register_admin
from .ask import register_ask
from .audio_notes import register_audio_notes
from .attivita import register_attivita
from .aura import register_aura
from .barcello import register_barcello
from .barcellometro_attivita import register_attivita_settings
from .command_helpers import add_command_once, add_group_once, describe_placeholders
from .ctx import CommandContext
from .permissions import check_permission
from .privacy import register_privacy
from .resoconto import register_resoconto
from .riassunto import register_riassunto
from .roles import register_roles
from .messaggi import register_messaggi
from .inattivi import register_inattivi
from .settings import get_setting, set_setting
from .status import register_status
from .stt import register_stt
from .translate import register_translate
from .triggers import register_triggers
from .voice_ingest import register_voice_ingest

__all__ = [
    "CommandContext",
    "add_group_once",
    "add_command_once",
    "describe_placeholders",
    "check_permission",
    "get_setting",
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
    "register_status",
    "register_stt",
    "register_translate",
    "register_triggers",
    "register_voice_ingest",
]
