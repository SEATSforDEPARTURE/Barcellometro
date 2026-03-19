import sys
from app.features.activity.services import activity_insights as _impl

sys.modules[__name__] = _impl
