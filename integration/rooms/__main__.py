"""python -m integration.rooms check --assembly FILE --evidence FILE [--enable]

Exit 0: adapter off, or the comparison found no ERROR. Exit 1: room diagnostics with an ERROR (or a failing core report).
Exit 2: input that could not be read or must not be compared. Off by default: set BMB_ROOMS_ADAPTER=1 or pass --enable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.assembly import AssemblyError
from integration.rooms import flag
from integration.rooms.check import EnhancedReport, validate_with_rooms
from integration.rooms.evidence import MAX_BYTES, EvidenceError

MAX_ASSEMBLY_BYTES = 4 * 1024 * 1024


class InputError(ValueError):
    pass


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise InputError(f"duplicate JSON field {key!r}"[:120])
        out[key] = value
    return out


def _constant(name):
    raise InputError(f"non-finite JSON constant {name}")


def _load(path: Path, limit: int, what: str) -> object:
    try:
        with open(path, "rb") as handle:
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise InputError(f"cannot read {what}: {type(exc).__name__}") from exc
    if len(raw) > limit:
        raise InputError(f"{what} is larger than {limit} bytes")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise InputError(f"{what} is not valid JSON: {type(exc).__name__}") from exc


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m integration.rooms", description="BMB-029 optional room-evidence check")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="validate an assembly, optionally comparing it with room evidence")
    check.add_argument("--assembly", required=True, type=Path)
    check.add_argument("--evidence", required=True, type=Path)
    check.add_argument("--enable", action="store_true", help=f"turn the adapter on (else {flag.ENV_FLAG}=1)")
    args = parser.parse_args(argv)
    try:
        assembly = _load(args.assembly, MAX_ASSEMBLY_BYTES, "assembly")
        if not isinstance(assembly, dict) or not isinstance(assembly.get("modules"), list):
            raise InputError("assembly must be an object with a modules list")
        on = flag.enabled(True if args.enable else None)
        evidence = _load(args.evidence, MAX_BYTES, "evidence") if on else None      # off: the evidence is not even read
        report = validate_with_rooms(assembly["modules"], evidence, enabled=on)
        if isinstance(report, EnhancedReport):
            print(json.dumps(report.to_dict(), sort_keys=True))
        else:
            print(json.dumps({"ok": report.ok, "enabled": False, "core": report.to_dict()}, sort_keys=True))
        return 0 if report.ok else 1
    except (InputError, EvidenceError, AssemblyError) as exc:
        print(json.dumps({"verdict": "FAIL", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
