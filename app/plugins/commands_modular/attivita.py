import sys
from app.features.activity.commands import attivita as _impl

sys.modules[__name__] = _impl
