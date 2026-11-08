"""BMB-029: OPTIONAL room-evidence adapter (feature-flagged; the core never imports this package).

A room detector's output ("rooms-evidence-v1", a PROPOSED interface defined here) is compared with the rooms the
Module IR intends (its floor slabs). The adapter only ever adds diagnostics; with the flag off the core validator's
own report is returned untouched and the evidence is not even read.

Importing this package has no side effects and imports nothing heavy; use `integration.rooms.check.validate_with_rooms`.
"""
from integration.rooms.flag import ENV_FLAG, enabled  # noqa: F401
