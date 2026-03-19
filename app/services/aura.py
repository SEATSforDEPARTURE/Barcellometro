import sys
from app.features.aura.services import aura_service as _impl

sys.modules[__name__] = _impl
