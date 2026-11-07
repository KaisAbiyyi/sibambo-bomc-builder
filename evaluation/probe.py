"""Cold single-purpose process: compile one Module IR document and report what it measured about itself.

Run as `python -m evaluation.probe compile --input FILE [--output FILE]`. A fresh interpreter per call is
the point: no import cache, no warmed allocator, no state shared with the driver. It prints one JSON line.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from bomc.compiler.graph_to_bomc import CompileError, compile_document
from evaluation.metrics import peak_rss_self


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.probe")
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("compile")
    one.add_argument("--input", required=True, type=Path)
    one.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:      # a typed refusal, never a traceback
        print(json.dumps({"ok": False, "error": f"cannot read input: {type(exc).__name__}"}))
        return 2
    started = time.perf_counter()
    try:
        compiled = compile_document(document)
    except (CompileError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    elapsed_ms = (time.perf_counter() - started) * 1000
    if args.output:
        args.output.write_bytes(compiled.payload)
    print(json.dumps({"ok": True, "receipt": compiled.receipt(), "compileMs": round(elapsed_ms, 3),
                      "peakRssBytes": peak_rss_self()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
