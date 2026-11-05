"""BMB-024: deterministic token estimator and byte-exact canonical JSON helpers.

`estimate_tokens` is a documented, provider-independent ESTIMATE (UTF-8 bytes of canonical
JSON divided by four, rounded up). It is not a provider-native token count; evidence built on it
must say so. It is monotonic and reproducible, which is what a hard budget needs.
"""
from __future__ import annotations

import hashlib
import json
import math

ESTIMATOR = "ceil(len(canonical-json-utf8) / 4)"


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def size_bytes(value: object) -> int:
    return len(canonical(value).encode("utf-8"))


def estimate_tokens(value: object) -> int:
    return math.ceil(size_bytes(value) / 4)


def digest(value: object, length: int = 64) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()[:length]
