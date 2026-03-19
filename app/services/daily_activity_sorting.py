import sys
from app.features.activity.services import daily_activity_sorting as _impl

sys.modules[__name__] = _impl
