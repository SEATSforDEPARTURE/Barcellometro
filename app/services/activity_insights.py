import sys
from app.features.activity.services import activity_insights_service as _impl

sys.modules[__name__] = _impl
