"""S11: fail unless every requirement in a pip lock file is an exact pin with sha256 hashes.

Usage: python scripts/check_hash_lock.py service/requirements.lock
CI also installs with ``pip install --require-hashes`` so pip itself refuses anything unhashed.
"""
from __future__ import annotations

import re
import sys

PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[A-Za-z0-9,._-]+\])?==([A-Za-z0-9.!+_-]+)\s*(;[^\\]*)?(\\)?\s*$")
HASH = re.compile(r"^\s*--hash=sha256:[0-9a-f]{64}\s*(\\)?\s*$")


def check(text: str) -> list[str]:
    problems: list[str] = []
    entries: list[tuple[str, int]] = []
    current: str | None = None
    hashes = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")):
            if HASH.match(line):
                hashes += 1
            else:
                problems.append(f"line {number}: unexpected continuation {line.strip()[:60]!r}")
            continue
        if current is not None:
            entries.append((current, hashes))
        match = PIN.match(line)
        if not match:
            problems.append(f"line {number}: not an exact '==' pin: {line[:60]!r}")
            current, hashes = None, 0
            continue
        current, hashes = f"{match.group(1)}=={match.group(3)}", 0
    if current is not None:
        entries.append((current, hashes))
    if not entries:
        problems.append("lock file has no requirements")
    problems += [f"{name}: no sha256 hashes" for name, count in entries if count == 0]
    return problems


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "service/requirements.lock"
    problems = check(open(path, encoding="utf-8").read())
    for problem in problems:
        print("FAIL:", problem, file=sys.stderr)
    print("HASH_LOCK=" + ("FAIL" if problems else "PASS"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
