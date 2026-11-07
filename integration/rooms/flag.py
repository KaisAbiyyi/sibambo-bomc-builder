"""The one switch. Off by default; anything that is not an explicit "on" is off (fail safe)."""
from __future__ import annotations

import os

ENV_FLAG = "BMB_ROOMS_ADAPTER"
_ON = frozenset({"1", "true", "yes", "on"})


def enabled(override: object = None) -> bool:
    """`override` wins when given, but only the real boolean True turns the adapter on (never a truthy string)."""
    if override is not None:
        return override is True
    return os.environ.get(ENV_FLAG, "").strip().lower() in _ON
