import sys
from app.features.aura.services import aura as _impl

sys.modules[__name__] = _impl
