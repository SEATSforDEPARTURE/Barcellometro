import sys
from app.features.activity.renderers import daily_report as _impl

sys.modules[__name__] = _impl
