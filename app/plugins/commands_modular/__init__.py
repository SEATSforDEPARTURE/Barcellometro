from .admin import register_admin
from .audio_notes import register_audio_notes
from .barcello import register_barcello
from .ctx import CommandContext
from .permissions import check_permission, ensure_admin
from .privacy import register_privacy
from .riassunto import register_riassunto
from .roles import register_roles
from .settings import get_setting, set_setting
from .status import register_status
from .stt import register_stt
from .translate import register_translate
from .voice_ingest import register_voice_ingest

__all__ = [
    "CommandContext",
    "check_permission",
    "ensure_admin",
    "get_setting",
    "set_setting",
    "register_admin",
    "register_audio_notes",
    "register_barcello",
    "register_privacy",
    "register_riassunto",
    "register_roles",
    "register_status",
    "register_stt",
    "register_translate",
    "register_voice_ingest",
]
