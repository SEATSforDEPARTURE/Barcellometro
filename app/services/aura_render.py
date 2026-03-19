import sys
from app.renderers import aura_renderer as _impl

sys.modules[__name__] = _impl
