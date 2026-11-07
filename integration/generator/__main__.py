"""python -m integration.generator {lower,submit} --input FILE [--root DIR]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentguide.controller import ControllerError
from integration.generator.brief import MAX_BYTES, BriefError, lower, to_brief
from integration.generator.handoff import prepare_root, submit


def _load(path: Path) -> object:
    with open(path, "rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise BriefError(f"input is larger than {MAX_BYTES} bytes")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise BriefError(f"invalid JSON input: {exc}") from exc


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m integration.generator",
                                     description="BMB-032 survey/form/room-brief handoff (no LLM, no network)")
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("lower", help="print the Module IR a brief lowers to")
    one.add_argument("--input", required=True, type=Path)
    two = sub.add_parser("submit", help="submit through the stdio MCP server into a project root")
    two.add_argument("--input", required=True, type=Path)
    two.add_argument("--root", required=True, type=Path, help="absolute private project root (created if missing)")
    args = parser.parse_args(argv)
    try:
        source = _load(args.input)
        if args.command == "lower":
            print(json.dumps(lower(to_brief(source)), sort_keys=True))
        else:
            print(json.dumps(submit(prepare_root(args.root), source), sort_keys=True))
        return 0
    except (BriefError, ControllerError, OSError) as exc:
        print(json.dumps({"verdict": "FAIL", "error": str(exc)}), file=sys.stdout)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
