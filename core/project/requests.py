"""SE-03.C: volatile owner-to-agent request inbox (RAM only, no logs, no disk).

At most 50 requests of at most 4 KiB each per exact (tenant, project), 30 minute TTL,
oldest evicted first. It carries free text from the owner to the agent and grants no write
capability: the only reader is the read-only ``read_owner_requests`` MCP tool. Lookups use
the exact (tenant, project) pair, so a different tenant can never read another's inbox.
Request text is untrusted data for the agent; nothing here is ever logged or persisted.
"""
from __future__ import annotations

import threading
import time

MAX_ITEMS = 50
MAX_BYTES = 4096
TTL_SECONDS = 30 * 60


class RequestError(ValueError):
    """Rejected request text or lookup."""


class RequestStore:
    def __init__(self, *, clock=None, max_items: int = MAX_ITEMS, max_bytes: int = MAX_BYTES,
                 ttl: float = TTL_SECONDS):
        self._clock = clock or time.monotonic
        self._max_items, self._max_bytes, self._ttl = max_items, max_bytes, float(ttl)
        self._lock = threading.Lock()
        self._boxes: dict[tuple[str, str], list[tuple[int, float, str]]] = {}
        self._next: dict[tuple[str, str], int] = {}

    @staticmethod
    def _key(tenant: object, project: object) -> tuple[str, str]:
        if not (isinstance(tenant, str) and tenant and isinstance(project, str) and project):
            raise RequestError("tenant and project are required")
        return tenant, project

    def _expire(self, key: tuple[str, str], now: float) -> list[tuple[int, float, str]]:
        box = [item for item in self._boxes.get(key, []) if now - item[1] < self._ttl]
        if box:
            self._boxes[key] = box
        else:
            self._boxes.pop(key, None)
        return box

    def post(self, tenant: str, project: str, text: str) -> int:
        key = self._key(tenant, project)
        if not isinstance(text, str) or not text.strip():
            raise RequestError("request text must be a non-empty string")
        if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in text):
            raise RequestError("request text contains control characters")
        if len(text.encode("utf-8")) > self._max_bytes:
            raise RequestError(f"request text exceeds {self._max_bytes} bytes")
        with self._lock:
            now = self._clock()
            box = self._expire(key, now)
            rid = self._next.get(key, 0) + 1
            self._next[key] = rid
            box.append((rid, now, text))
            del box[:-self._max_items]               # bounded: oldest evicted
            self._boxes[key] = box
            return rid

    def read(self, tenant: str, project: str, since_id: int = 0) -> list[dict]:
        key = self._key(tenant, project)
        if type(since_id) is not int or since_id < 0:
            raise RequestError("sinceId must be a non-negative integer")
        with self._lock:
            now = self._clock()
            return [{"id": rid, "ageSeconds": int(now - at), "text": text}
                    for rid, at, text in self._expire(key, now) if rid > since_id]

    def clear(self, tenant: str, project: str) -> None:
        key = self._key(tenant, project)
        with self._lock:
            self._boxes.pop(key, None)
