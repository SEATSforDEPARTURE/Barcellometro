import sys
from app.features.activity.renderers import user_activity as _impl

sys.modules[__name__] = _impl
