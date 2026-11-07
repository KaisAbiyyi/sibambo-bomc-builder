"""Measurement primitives: statistics, peak memory, environment, and a transparent MCP observer."""
from __future__ import annotations

import contextlib
import json
import math
import os
import platform
import subprocess
import sys
import time

from agentctx.budget import ESTIMATOR, estimate_tokens

_REAL_RUN = subprocess.run          # captured before any observer replaces it


# ---- statistics ------------------------------------------------------------------------------

def median(values: list) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("no values")
    mid = n // 2
    return float(ordered[mid]) if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def percentile(values: list, q: float) -> float:
    """Nearest-rank percentile (deterministic, no interpolation). With few trials it is descriptive only."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("no values")
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return float(ordered[rank - 1])


def describe(values: list) -> dict:
    return {"n": len(values), "min": float(min(values)), "median": median(values),
            "p95": percentile(values, 95), "max": float(max(values))}


# ---- memory ----------------------------------------------------------------------------------

def _windows_peak_working_set() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return None
        return int(counters.PeakWorkingSetSize)
    except Exception:  # noqa: BLE001 - a missing API is "not measured", never a failure
        return None


def peak_rss_self() -> int | None:
    """Peak resident set of THIS process in bytes, or None when the platform offers no stdlib way."""
    if os.name == "nt":
        return _windows_peak_working_set()
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)    # Linux reports KiB, macOS bytes
    except Exception:  # noqa: BLE001
        return None


def peak_rss_children() -> int | None:
    """Peak resident set of the LARGEST waited-for descendant, POSIX only (None on Windows)."""
    if os.name == "nt":
        return None
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)
    except Exception:  # noqa: BLE001
        return None


def environment() -> dict:
    return {"platform": platform.platform(), "system": platform.system(), "machine": platform.machine(),
            "python": platform.python_version(), "implementation": platform.python_implementation(),
            "cpuCount": os.cpu_count(), "network": "none required or used", "llm": "none"}


# ---- observing the MCP transport without changing it ------------------------------------------

class McpObserver:
    """Wrap `subprocess.run` for the duration of a scripted run and record every JSON-RPC exchange.

    It only watches: the command, input and result are passed through untouched. Per request it keeps the
    tool name, a bounded argument summary, the typed error code (if any), and the estimated tokens the model
    would WRITE (the request) and READ (the response), using the documented provider-independent estimator.
    """

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.batch_ms: list[float] = []      # one MCP process per batch: the only latency actually measured
        self.process_ms = 0.0
        self.request_bytes = 0
        self.response_bytes = 0
        self._patch = None

    def __enter__(self) -> "McpObserver":
        observer = self

        def run(command, *args, **kwargs):
            started = time.perf_counter()
            result = _REAL_RUN(command, *args, **kwargs)
            elapsed = (time.perf_counter() - started) * 1000
            if isinstance(command, list) and "agent.bmb_mcp" in command:
                observer._record(kwargs.get("input") or b"", result.stdout or b"", elapsed)
            return result

        self._patch = subprocess.run
        subprocess.run = run
        return self

    def __exit__(self, *exc) -> None:
        subprocess.run = self._patch

    def _record(self, payload: bytes, stdout: bytes, elapsed_ms: float) -> None:
        sent = [json.loads(line) for line in payload.splitlines() if line.strip()]
        received = {r.get("id"): r for r in (json.loads(line) for line in stdout.splitlines() if line.strip())}
        self.process_ms += elapsed_ms
        self.batch_ms.append(elapsed_ms)
        self.request_bytes += len(payload)
        self.response_bytes += len(stdout)
        for request in sent:
            response = received.get(request.get("id"), {})
            result = response.get("result") or {}
            error = (response.get("error") or {}).get("code") if "error" in response else (
                ((result.get("structuredContent") or {}).get("error") or {}).get("code"))
            params = request.get("params", {})
            arguments = params.get("arguments") or {}
            self.requests.append({
                "method": request.get("method"), "tool": params.get("name"),
                "moduleId": arguments.get("moduleId") if isinstance(arguments, dict) else None,
                "error": error if isinstance(error, (str, int)) else None,
                "ok": "error" not in response and result.get("isError") is False,
                "tokensOut": estimate_tokens(request), "tokensIn": estimate_tokens(response) if response else 0})

    def summary(self) -> dict:
        tool_calls = [r for r in self.requests if r["method"] == "tools/call"]
        rejected = [r for r in tool_calls if not r["ok"]]
        # A retry is a call repeated for the same tool and module after a RECOVERABLE rejection (stale
        # revision) that then succeeded; a terminal rejection (denied, invalid) is never retried.
        retries, pending = 0, set()
        for r in tool_calls:
            key = (r["tool"], r["moduleId"])
            if not r["ok"] and r["error"] == "REVISION_CONFLICT":
                pending.add(key)
            elif r["ok"] and key in pending:
                pending.discard(key)
                retries += 1
        return {
            "requests": len(self.requests), "toolCalls": len(tool_calls),
            "rejectedToolCalls": len(rejected), "retries": retries,
            "rejectionCodes": sorted({str(r["error"]) for r in rejected}),
            "estimatedInputTokens": sum(r["tokensIn"] for r in self.requests),
            "estimatedOutputTokens": sum(r["tokensOut"] for r in self.requests),
            "tokenEstimator": ESTIMATOR, "providerTokens": None,
            "providerTokensNote": "no live model was used; provider-native usage does not exist for this run",
            "requestBytes": self.request_bytes, "responseBytes": self.response_bytes,
            "mcpProcessMs": round(self.process_ms, 3),
            "mcpBatches": len(self.batch_ms), "slowestBatchMs": round(max(self.batch_ms, default=0.0), 3),
        }


@contextlib.contextmanager
def stopwatch():
    box = {}
    started = time.perf_counter()
    try:
        yield box
    finally:
        box["ms"] = (time.perf_counter() - started) * 1000
