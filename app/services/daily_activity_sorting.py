import sys
from app.features.activity.services import activity_sorting_service as _impl

sys.modules[__name__] = _impl
