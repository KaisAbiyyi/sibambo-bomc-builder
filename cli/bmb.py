"""BMB-022: machine-readable CLI over the existing Builder core.

The journal is the only persistent mutation engine; no alternate CLI state
or graph representation is maintained. Geometry validation and BOMC compilation
are explicitly downstream, not claimed by this interface.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.assembly import AssemblyError, assemble
from core.identity import IdempotencyConflictError, IdentityError, StaleDependencyError, StaleRevisionError
from core.storage import (
    ConcurrentWriteError, CorruptJournalError, DurabilityUncertainError,
    JournalStore, StorageError,
)

MAX_INPUT_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024


class CLIError(ValueError):
    """Invalid command-line option or bounded JSON request."""


class JSONParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CLIError(message)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for name, value in pairs:
        if name in result:
            raise CLIError(f"duplicate JSON field {name!r}")
        result[name] = value
    return result


def _reject_constant(value: str) -> None:
    raise CLIError(f"non-finite JSON constant {value!r}")


def _input_json(stream) -> dict:
    raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise CLIError("JSON input exceeds 1048576-byte limit")
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant,
                           object_pairs_hook=_unique_pairs)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise CLIError(f"invalid UTF-8 JSON input: {exc}") from exc
    if not isinstance(value, dict):
        raise CLIError("JSON input must be an object")
    return value


def _parser() -> JSONParser:
    p = JSONParser(prog="python -m cli.bmb", description="BOMC Builder headless journal and assembly CLI")
    p.add_argument("--root", help="absolute project root (required for journal commands)")
    sub = p.add_subparsers(dest="command", required=True, parser_class=JSONParser)

    create = sub.add_parser("create", help="create an empty persistent module")
    create.add_argument("--module-id", required=True)

    inspect = sub.add_parser("inspect", help="inspect one persisted module without loading others")
    inspect.add_argument("--module-id", required=True)
    inspect.add_argument("--blocks", action="store_true", help="include bounded block payloads")

    edit = sub.add_parser("edit", help="apply an atomic edit (JSON from standard input)")
    edit.add_argument("--module-id", required=True)
    edit.add_argument("--expected-revision", required=True, type=int)
    edit.add_argument("--key", required=True, help="idempotency key")

    rollback = sub.add_parser("rollback", help="commit a compensating historical revision")
    rollback.add_argument("--module-id", required=True)
    rollback.add_argument("--expected-revision", required=True, type=int)
    rollback.add_argument("--key", required=True)
    rollback.add_argument("--to-revision", required=True, type=int)

    validate = sub.add_parser("validate", help="check journal integrity OR supplied assembly IR")
    validate.add_argument("--module-id", help="validate just one persisted journal")
    validate.add_argument("--assembly-stdin", action="store_true",
                          help="instead validate a Module IR envelope read from standard input")
    return p


def _project_root(value: str | None, *, create: bool = False) -> Path:
    if not value:
        raise CLIError("--root is required for journal commands")
    path = Path(value)
    if not path.is_absolute():
        raise CLIError("--root must be an absolute directory")
    if not create and not path.is_dir():
        raise StorageError("project root does not exist")
    if create and path.exists() and not path.is_dir():
        raise StorageError("project root is not a directory")
    return path


def _journal(root: Path, modules: list[str] | None = None) -> JournalStore:
    return JournalStore.open(root, modules=modules)


def _run(args: argparse.Namespace, stream) -> dict:
    command = args.command
    if command == "validate" and args.assembly_stdin:
        if args.root is not None or args.module_id is not None:
            raise CLIError("assembly validation cannot combine --root or --module-id")
        payload = _input_json(stream)
        if set(payload) != {"modules"}:
            raise CLIError("assembly JSON must contain only 'modules'")
        graph = assemble(payload["modules"])
        return {
            "mode": "assembly",
            "moduleCount": len(graph.modules),
            "moduleIds": list(graph.modules),
            "order": list(graph.order),
            "seams": [
                {"seamId": s.seam_id, "ownerModuleId": s.owner, "participants": list(s.participants)}
                for s in graph.seams
            ],
        }

    root = _project_root(args.root, create=command == "create")
    if command == "create":
        store = _journal(root)
        revision = store.create_module(args.module_id)
        return {"moduleId": args.module_id, "revision": revision}

    if command == "inspect":
        store = _journal(root, [args.module_id])
        revision, blocks = store.snapshot(args.module_id)
        data = {
            "moduleId": args.module_id, "revision": revision,
            "blockCount": len(blocks), "blockIds": sorted(blocks),
            "journalHash": store.tail_hash(args.module_id),
        }
        if args.blocks:
            data["blocks"] = blocks
        return data

    if command == "edit":
        payload = _input_json(stream)
        if set(payload) - {"ops", "minRevisions"} or "ops" not in payload:
            raise CLIError("edit JSON must have 'ops' and optional 'minRevisions' only")
        mins = payload.get("minRevisions", {})
        if not isinstance(mins, dict):
            raise CLIError("minRevisions must be an object")
        store = _journal(root, sorted({args.module_id, *mins}))
        result = store.apply(args.module_id, args.expected_revision, args.key, payload["ops"], mins)
        return {"moduleId": result.module_id, "revision": result.revision, "replayed": result.replayed,
                "journalHash": store.tail_hash(args.module_id)}

    if command == "rollback":
        store = _journal(root, [args.module_id])
        result = store.rollback(args.module_id, args.expected_revision, args.key, args.to_revision)
        return {"moduleId": result.module_id, "revision": result.revision, "replayed": result.replayed,
                "journalHash": store.tail_hash(args.module_id)}

    if command == "validate":
        store = _journal(root, [args.module_id] if args.module_id else None)
        return {"mode": "journal", "moduleCount": len(store.modules()), "moduleIds": store.modules(),
                "revisions": {mid: store.revision(mid) for mid in store.modules()}}
    raise CLIError("unrecognized command")


def _error(exc: Exception) -> tuple[str, int]:
    if isinstance(exc, StaleRevisionError):
        return "STALE_REVISION", 3
    if isinstance(exc, StaleDependencyError):
        return "STALE_DEPENDENCY", 3
    if isinstance(exc, IdempotencyConflictError):
        return "IDEMPOTENCY_CONFLICT", 3
    if isinstance(exc, DurabilityUncertainError):
        return "DURABILITY_UNCERTAIN", 4
    if isinstance(exc, CorruptJournalError):
        return "CORRUPT_JOURNAL", 4
    if isinstance(exc, ConcurrentWriteError):
        return "CONCURRENT_WRITE", 4
    if isinstance(exc, StorageError):
        return "STORAGE_ERROR", 4
    if isinstance(exc, AssemblyError):
        return "INVALID_ASSEMBLY", 2
    if isinstance(exc, IdentityError):
        return "INVALID_OPERATION", 2
    if isinstance(exc, CLIError):
        return "INVALID_ARGUMENT", 2
    if isinstance(exc, OSError):
        return "IO_ERROR", 4
    return "INTERNAL_ERROR", 1


def main(argv: list[str] | None = None, stream=None) -> int:
    command = None
    try:
        args = _parser().parse_args(argv)
        command = args.command
        value = {"ok": True, "command": command, "result": _run(args, stream or sys.stdin.buffer)}
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise CLIError("JSON output exceeds 1048576-byte limit")
        print(encoded)
        return 0
    except (CLIError, IdentityError, StorageError, AssemblyError, OSError) as exc:
        code, exit_code = _error(exc)
        print(json.dumps({"ok": False, "command": command,
                          "error": {"code": code, "message": str(exc)}}, sort_keys=True))
        return exit_code
    except Exception:
        # Never expose a traceback or internal path in the machine-readable interface.
        print(json.dumps({"ok": False, "command": command,
                          "error": {"code": "INTERNAL_ERROR", "message": "internal CLI failure"}},
                         sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
