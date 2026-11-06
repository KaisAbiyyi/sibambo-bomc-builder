"""Bounded rendering of untrusted values for error messages (BMB-030).

``f"invalid id {value!r}"`` is evaluated *before* the check it reports on, so a
hostile, deeply nested value makes ``repr`` itself raise ``RecursionError``
(where exactly depends on the platform's C stack, hence "passes on Linux, fails
on Windows"), and a 100 kB string would be copied into every message.  ``show``
renders scalars exactly like ``repr`` (long strings are cut) and everything
else as its type name, so building a message can never fail or grow.
"""

from __future__ import annotations

LIMIT = 64


def show(value: object, limit: int = LIMIT) -> str:
    if isinstance(value, str):
        text = repr(value[:limit])
        return text if len(value) <= limit else text[:-1] + "..." + text[-1]
    if value is None or isinstance(value, (bool, float)):
        return repr(value)
    if isinstance(value, int):
        return repr(value) if value.bit_length() <= 64 else "<int>"
    return f"<{type(value).__name__}>"
