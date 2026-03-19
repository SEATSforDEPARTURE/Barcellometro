import sys
from app.features.activity.services import daily_activity_report as _impl

sys.modules[__name__] = _impl
