import sys
from app.features.activity.renderers import activity_dm as _impl

sys.modules[__name__] = _impl
