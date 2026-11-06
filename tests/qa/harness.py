"""BMB-030 adversarial harness: seeded structure-aware mutation, bounded execution, typed-error policy.

Everything is deterministic (fixed seeds) and synthetic. A target passes when, for every hostile input, it
either succeeds or raises ONE OF ITS DOCUMENTED TYPED ERRORS (a ValueError subclass), within the time and
memory budget. TypeError, KeyError, AttributeError, IndexError, OverflowError, ZeroDivisionError,
RecursionError, MemoryError and timeouts are defects: they mean hostile input reached code that did not
expect it, and under a host that catches only the typed errors they become crashes or hangs.
"""
from __future__ import annotations

import copy
import math
import os
import random
import time
import tracemalloc
from contextlib import contextmanager

ITERATIONS = int(os.environ.get("BMB_FUZZ_ITERS", "400"))


class BudgetExceeded(AssertionError):
    pass


@contextmanager
def budget(seconds: float = 5.0, peak_mb: float | None = None):
    """Fail if the block takes longer than `seconds` of wall time or, when `peak_mb` is given, allocates more than
    that many MiB at once. Memory tracing slows code down a lot, so it is opt-in for the explicit resource tests."""
    tracing = peak_mb is not None
    already = tracemalloc.is_tracing()
    if tracing:
        if not already:
            tracemalloc.start()
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        peak = 0
        if tracing:
            peak = tracemalloc.get_traced_memory()[1] - base
            if not already:
                tracemalloc.stop()
    if elapsed > seconds:
        raise BudgetExceeded(f"took {elapsed:.2f}s (limit {seconds}s)")
    if tracing and peak > peak_mb * 1024 * 1024:
        raise BudgetExceeded(f"peaked at {peak / 1048576:.1f} MiB (limit {peak_mb} MiB)")


def deep_list(n: int):
    """A list nested n levels deep, built iteratively (no recursion on our side)."""
    out: list = []
    for _ in range(n):
        out = [out]
    return out


def deep_dict(n: int):
    out: dict = {}
    for _ in range(n):
        out = {"a": out}
    return out


def deep_json(n: int) -> str:
    return "[" * n + "]" * n


JUNK = (
    None, True, False, 0, -1, 1, 2 ** 31, 2 ** 63, 10 ** 400, -10 ** 400, 0.0, -0.0, 1e308, -1e308, 1e-320,
    math.nan, math.inf, -math.inf, "", "x", "../../etc/passwd", "a/b", "\x00", "\ud800", "é" * 70, "x" * 100_000,
    [], {}, [[]], {"a": []}, [1, 2, 3], [None], [[0, 0], [1, 1]], (1, 2), {1, 2}, b"bytes", object(),
)


def paths(node, trail=()):
    """Every (container-or-leaf) path in a JSON-like value, depth-first, in a stable order."""
    yield trail
    if isinstance(node, dict):
        for k in sorted(node, key=str):
            yield from paths(node[k], trail + (k,))
    elif isinstance(node, list):
        for i in range(len(node)):
            yield from paths(node[i], trail + (i,))


def _get(doc, trail):
    for k in trail:
        doc = doc[k]
    return doc


def mutate(doc, rng: random.Random):
    """Return a deep copy of `doc` with one structure-aware hostile edit applied."""
    out = copy.deepcopy(doc)
    all_paths = [p for p in paths(out) if p]
    if not all_paths:
        return out
    trail = rng.choice(all_paths)
    parent, key = _get(out, trail[:-1]), trail[-1]
    kind = rng.randrange(9)
    if kind <= 3:
        parent[key] = rng.choice(JUNK)
    elif kind == 4:
        parent[key] = deep_list(rng.choice((50, 500, 5000))) if rng.random() < 0.5 else deep_dict(rng.choice((50, 500, 5000)))
    elif kind == 5 and isinstance(parent, dict):
        del parent[key]
    elif kind == 6 and isinstance(parent, list):
        parent.append(copy.deepcopy(parent[key]))
        if rng.random() < 0.3:
            parent.extend(copy.deepcopy(parent) * rng.choice((2, 20, 200)))
    elif kind == 7 and isinstance(parent, (list, dict)):
        keys = list(parent) if isinstance(parent, dict) else list(range(len(parent)))
        other = rng.choice(keys)
        parent[key], parent[other] = parent[other], parent[key]
    else:
        value = parent[key]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parent[key] = rng.choice((value * -1, value * 1e9, value / 1e9 if value else 1e-9, value + 1, 0))
        elif isinstance(value, str):
            parent[key] = value + rng.choice(("/..", "\x00", " ", "é", "x" * 300))
        else:
            parent[key] = rng.choice(JUNK)
    return out


def run(target, doc, rng, iterations: int, allowed: tuple, *, seconds=5.0, peak_mb=None):
    """Hammer `target(doc')` with mutated documents; return a list of (iteration, exception) that are defects."""
    defects = []
    for i in range(iterations):
        hostile = mutate(doc, rng)
        try:
            with budget(seconds, peak_mb):
                target(hostile)
        except allowed:
            pass
        except BudgetExceeded as exc:
            defects.append((i, exc))
        except BaseException as exc:  # noqa: BLE001 - everything else is a defect to report
            defects.append((i, exc))
    return defects


def describe(defects, limit=5):
    seen = {}
    for i, exc in defects:
        seen.setdefault(type(exc).__name__ + ": " + str(exc)[:80], i)
    return [f"iter {i}: {k}" for k, i in list(seen.items())[:limit]]
