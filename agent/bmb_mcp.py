"""BMB-023: bounded, modern (2026-07-28) stdio MCP adapter.

Only the trusted launcher chooses the project root and mutation grant. Tools
reuse BMB-022's dispatcher and BMB-008/010/011 core; untrusted tool arguments
are never used as paths or commands. This is not an OS sandbox.
"""
from __future__ import annotations

import argparse
from collections import deque
import io
import json
import multiprocessing as mp
import os
from pathlib import Path
import re
import stat
import sys
import time
from types import SimpleNamespace

from cli.bmb import _error as cli_error, _run as cli_run
from core.identity.store import BLOCK_ID_PATTERN, KEY_PATTERN, MODULE_ID_PATTERN

VERSION = "2026-07-28"
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPS = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO = {"name": "sibambo-bomc-builder", "version": "0.23.0"}
MAX_FRAME = 256 * 1024
MAX_RESPONSE = 256 * 1024
MAX_DEPTH = 32
MAX_MODULES = 1024  # existing core cap, stricter than BMB-004 design ceiling
MAX_FILES = 32_768
MAX_DISK_BYTES = 1024 * 1024 * 1024
TIMEOUT = 30
WRITE_TOOLS = frozenset({"bmb_create_module", "bmb_edit_module", "bmb_rollback_module"})


def prop(kind, **extra):
    return {"type": kind, **extra}


SCHEMAS = {
    "bmb_create_module": (["moduleId"], {"moduleId": prop("string", pattern=r"^[a-z][a-z0-9-]*(/[a-z][a-z0-9-]*)+$")}),
    "bmb_inspect_module": (["moduleId"], {
        "moduleId": prop("string", pattern=r"^[a-z][a-z0-9-]*(/[a-z][a-z0-9-]*)+$"),
        "includeBlocks": prop("boolean"),
    }),
    "bmb_edit_module": (["moduleId", "expectedRevision", "idempotencyKey", "ops"], {
        "moduleId": prop("string", pattern=r"^[a-z][a-z0-9-]*(/[a-z][a-z0-9-]*)+$"),
        "expectedRevision": prop("integer", minimum=0),
        "idempotencyKey": prop("string", pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
        "ops": prop("array", minItems=1, maxItems=256, items={
            "oneOf": [
                {"type": "object", "additionalProperties": False,
                 "properties": {
                     "op": prop("string", const=kind),
                     "id": prop("string", pattern=r"^[a-z][a-z0-9-]{0,79}$"),
                     **({"data": prop("object")} if kind != "remove" else {}),
                 },
                 "required": ["op", "id"] + (["data"] if kind != "remove" else [])}
                for kind in ("add", "replace", "remove")
            ],
        }),
        "minRevisions": prop("object", maxProperties=256, additionalProperties=prop("integer", minimum=0)),
    }),
    "bmb_rollback_module": (["moduleId", "expectedRevision", "idempotencyKey", "toRevision"], {
        "moduleId": prop("string", pattern=r"^[a-z][a-z0-9-]*(/[a-z][a-z0-9-]*)+$"),
        "expectedRevision": prop("integer", minimum=0),
        "idempotencyKey": prop("string", pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
        "toRevision": prop("integer", minimum=0),
    }),
    "bmb_validate_journals": ([], {"moduleId": prop("string", pattern=r"^[a-z][a-z0-9-]*(/[a-z][a-z0-9-]*)+$")}),
    "bmb_validate_assembly": (["document"], {"document": {
        "type": "object", "additionalProperties": False,
        "required": ["modules"],
        "properties": {
            "schemaVersion": prop("string", const="1.0.0"),
            "modules": prop("array", maxItems=MAX_MODULES),
        },
    }}),
}
DESCRIPTIONS = {
    "bmb_create_module": "Create a new empty module in the launch-scoped journal.",
    "bmb_inspect_module": "Read one journal module; includeBlocks may exceed the bounded response limit.",
    "bmb_edit_module": "CAS/idempotent atomic edit through the shared journal core; 1..256 operations.",
    "bmb_rollback_module": "Commit a compensating revision using an idempotency key.",
    "bmb_validate_journals": "Validate journal integrity for one module or the bounded project.",
    "bmb_validate_assembly": "Validate a supplied versioned Module IR graph; not geometry/BOMC compilation.",
}


class ToolFailure(Exception):
    def __init__(self, code, message="Request rejected"):
        super().__init__(message)
        self.code = code


def _limited(value):
    """Bound materialized JSON before recursion or core allocation."""
    stack = [(value, 1)]
    count = 0
    while stack:
        obj, depth = stack.pop()
        count += 1
        if count > 100_000:
            raise ToolFailure("LIMIT_EXCEEDED")
        if depth > MAX_DEPTH:
            raise ToolFailure("DEPTH_LIMIT")
        if isinstance(obj, dict):
            stack.extend((v, depth + 1) for v in obj.values())
        elif isinstance(obj, list):
            stack.extend((v, depth + 1) for v in obj)


def _unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ToolFailure("INVALID_ARGUMENT", "Duplicate JSON key")
        result[k] = v
    return result


def _nonfinite(_):
    raise ToolFailure("INVALID_ARGUMENT", "Non-finite JSON value")


def _decode(raw):
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                         parse_constant=_nonfinite)
        _limited(obj)
        return obj
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ToolFailure("INVALID_ARGUMENT", "Invalid UTF-8 JSON") from exc


def _safe_part(path: Path, directory: bool):
    try:
        st = path.lstat()
    except OSError as exc:
        raise ToolFailure("PATH_OUTSIDE_ROOT", "Unsafe or missing project path") from exc
    reparse = getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(st.st_mode) or reparse or (path.is_junction() if hasattr(path, "is_junction") else False):
        raise ToolFailure("PATH_OUTSIDE_ROOT", "Filesystem link forbidden")
    if directory and not stat.S_ISDIR(st.st_mode):
        raise ToolFailure("PATH_OUTSIDE_ROOT", "Not a directory")
    if not directory and (not stat.S_ISREG(st.st_mode) or st.st_nlink > 1):
        raise ToolFailure("PATH_OUTSIDE_ROOT", "Unsafe file type or hardlink")
    return st


def _guard_root(root: Path):
    if not root.is_absolute() or ".." in root.parts:
        raise ToolFailure("PATH_OUTSIDE_ROOT", "Absolute normalized root required")
    for ancestor in reversed((root, *root.parents)):
        _safe_part(ancestor, True)
    base = root / "modules"
    if not os.path.lexists(base):
        return
    _safe_part(base, True)
    total, count, modules = 0, 0, 0
    try:
        folders = list(base.iterdir())
    except OSError as exc:
        raise ToolFailure("PATH_OUTSIDE_ROOT") from exc
    if len(folders) > MAX_MODULES:
        raise ToolFailure("LIMIT_EXCEEDED", "Module count limit")
    for folder in folders:
        _safe_part(folder, True)
        modules += 1
        if not re.fullmatch(r"[a-z][a-z0-9-]*(__[a-z][a-z0-9-]*)+", folder.name):
            raise ToolFailure("PATH_OUTSIDE_ROOT", "Invalid module directory")
        for item in folder.iterdir():
            st = _safe_part(item, False)
            count += 1
            total += st.st_size
            if count > MAX_FILES or total > MAX_DISK_BYTES:
                raise ToolFailure("LIMIT_EXCEEDED", "Project file or byte budget")
    if modules > MAX_MODULES:
        raise ToolFailure("LIMIT_EXCEEDED", "Module count limit")


def _validate_args(name, args):
    if name not in SCHEMAS:
        raise ToolFailure("UNKNOWN_TOOL", "Tool not found")
    required, props = SCHEMAS[name]
    if not isinstance(args, dict) or set(args) - set(props) or any(k not in args for k in required):
        raise ToolFailure("INVALID_ARGUMENT", "Unexpected or missing tool argument")
    for k, value in args.items():
        schema = props[k]
        typ = schema["type"]
        if typ == "string":
            if not isinstance(value, str) or ("pattern" in schema and not re.fullmatch(schema["pattern"], value)):
                raise ToolFailure("INVALID_ARGUMENT", "Invalid string argument")
        elif typ == "integer":
            if type(value) is not int or value < 0:
                raise ToolFailure("INVALID_ARGUMENT", "Invalid revision")
        elif typ == "boolean":
            if type(value) is not bool:
                raise ToolFailure("INVALID_ARGUMENT", "Invalid boolean")
        elif typ == "object":
            if not isinstance(value, dict):
                raise ToolFailure("INVALID_ARGUMENT", "Object required")
        elif typ == "array":
            if not isinstance(value, list):
                raise ToolFailure("INVALID_ARGUMENT", "Array required")
    if "minRevisions" in args:
        mins = args["minRevisions"]
        if len(mins) > 256 or any(not MODULE_ID_PATTERN.fullmatch(k) or type(v) is not int or v < 0
                                  for k, v in mins.items()):
            raise ToolFailure("INVALID_ARGUMENT", "Invalid dependency minimums")
    if "ops" in args:
        ops = args["ops"]
        if not 1 <= len(ops) <= 256:
            raise ToolFailure("LIMIT_EXCEEDED", "Operation count limit")
        for op in ops:
            if (not isinstance(op, dict) or set(op) - {"op", "id", "data"}
                    or op.get("op") not in ("add", "replace", "remove")
                    or not isinstance(op.get("id"), str)
                    or not BLOCK_ID_PATTERN.fullmatch(op["id"])):
                raise ToolFailure("INVALID_ARGUMENT", "Invalid operation")
            if op["op"] == "remove":
                if "data" in op:
                    raise ToolFailure("INVALID_ARGUMENT", "Remove takes no data")
            elif not isinstance(op.get("data"), dict):
                raise ToolFailure("INVALID_ARGUMENT", "Add/replace requires object data")
    if "document" in args:
        doc = args["document"]
        if set(doc) - {"schemaVersion", "modules"} or "modules" not in doc:
            raise ToolFailure("INVALID_ARGUMENT", "Invalid assembly envelope")
        if doc.get("schemaVersion", "1.0.0") != "1.0.0" or not isinstance(doc["modules"], list):
            raise ToolFailure("INVALID_ARGUMENT", "Invalid assembly schema or modules")
        if len(doc["modules"]) > MAX_MODULES:
            raise ToolFailure("LIMIT_EXCEEDED", "Assembly module count limit")


def _command(name, args, root):
    if name == "bmb_create_module":
        return SimpleNamespace(root=root, command="create", module_id=args["moduleId"]), b""
    if name == "bmb_inspect_module":
        return SimpleNamespace(root=root, command="inspect", module_id=args["moduleId"],
                               blocks=args.get("includeBlocks", False)), b""
    if name == "bmb_edit_module":
        payload = {"ops": args["ops"]}
        if "minRevisions" in args:
            payload["minRevisions"] = args["minRevisions"]
        return SimpleNamespace(root=root, command="edit", module_id=args["moduleId"],
                               expected_revision=args["expectedRevision"],
                               key=args["idempotencyKey"]), json.dumps(payload, allow_nan=False).encode()
    if name == "bmb_rollback_module":
        return SimpleNamespace(root=root, command="rollback", module_id=args["moduleId"],
                               expected_revision=args["expectedRevision"],
                               key=args["idempotencyKey"], to_revision=args["toRevision"]), b""
    if name == "bmb_validate_journals":
        return SimpleNamespace(root=root, command="validate", assembly_stdin=False,
                               module_id=args.get("moduleId")), b""
    if name == "bmb_validate_assembly":
        return SimpleNamespace(root=None, command="validate", assembly_stdin=True,
                               module_id=None), json.dumps(args["document"], allow_nan=False).encode()
    raise ToolFailure("UNKNOWN_TOOL")


def _worker(conn, root, name, args):
    try:
        os.umask(0o077)
        if os.name == "posix":
            import resource
            soft, hard = resource.getrlimit(resource.RLIMIT_AS)
            cap = 512 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (min(soft, cap) if soft > 0 else cap, hard))
        _guard_root(Path(root))
        command, payload = _command(name, args, root)
        result = cli_run(command, io.BytesIO(payload))
        _guard_root(Path(root))
        response = {"ok": True, "data": result}
        if len(json.dumps(response, allow_nan=False).encode("utf-8")) > MAX_RESPONSE // 2:
            raise ToolFailure("LIMIT_EXCEEDED", "Tool output budget")
        conn.send(response)
    except ToolFailure as exc:
        conn.send({"ok": False, "error": {"code": exc.code, "message": str(exc)[:128]}})
    except Exception as exc:
        code, _ = cli_error(exc)
        remap = {"STALE_REVISION": "REVISION_CONFLICT", "STALE_DEPENDENCY": "REVISION_CONFLICT",
                 "INVALID_ASSEMBLY": "INVALID_ARGUMENT", "INVALID_OPERATION": "INVALID_ARGUMENT",
                 "CORRUPT_JOURNAL": "CORRUPT_INPUT", "CONCURRENT_WRITE": "BUSY"}
        code = remap.get(code, code)
        # No exception text, absolute host path, environment, or traceback can escape.
        conn.send({"ok": False, "error": {"code": code, "message": "Core operation rejected"}})
    finally:
        conn.close()


def _perform(root, name, args):
    parent, child = mp.get_context("spawn").Pipe(duplex=False)
    process = mp.get_context("spawn").Process(target=_worker, args=(child, str(root), name, args))
    try:
        process.start()
        child.close()
        if not parent.poll(TIMEOUT):
            return {"ok": False, "error": {"code": "TIMEOUT", "message": "Deadline exceeded; commit outcome unknown"}}
        try:
            return parent.recv()
        except EOFError:
            return {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "Worker exited without receipt"}}
    except Exception:
        return {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "Worker failure"}}
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join()
        parent.close()
        child.close()


def _rpc_error(ident, code, message, data=None):
    obj = {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}
    if data is not None:
        obj["error"]["data"] = data
    return obj


def _success(ident, result):
    result.setdefault("_meta", {})["io.modelcontextprotocol/serverInfo"] = SERVER_INFO
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def _tool_response(result):
    text = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {"resultType": "complete", "content": [{"type": "text", "text": text}],
            "structuredContent": result, "isError": not result["ok"]}


class Server:
    def __init__(self, root, writes=False):
        self.root = Path(root)
        _guard_root(self.root)
        root_stat = self.root.stat()
        if (self.root == Path(self.root.anchor)
                or (os.name == "posix" and (root_stat.st_uid != os.getuid()
                    or (stat.S_IMODE(root_stat.st_mode) & 0o077)))):
            raise ToolFailure("PERMISSION_DENIED", "Private owned project directory required")
        self.writes = writes
        self.calls_min = deque()
        self.calls_hour = deque()

    def _rate(self):
        now = time.monotonic()
        while self.calls_min and self.calls_min[0] <= now - 60:
            self.calls_min.popleft()
        while self.calls_hour and self.calls_hour[0] <= now - 3600:
            self.calls_hour.popleft()
        if len(self.calls_min) >= 60 or len(self.calls_hour) >= 600:
            raise ToolFailure("LIMIT_EXCEEDED", "Request rate limit")
        self.calls_min.append(now)
        self.calls_hour.append(now)

    def handle(self, packet):
        if not isinstance(packet, dict) or packet.get("jsonrpc") != "2.0" or not isinstance(packet.get("method"), str):
            return _rpc_error(None, -32600, "Invalid request")
        if "id" not in packet:  # notification; no response
            return None
        ident = packet["id"]
        if isinstance(ident, bool) or not isinstance(ident, (str, int)):
            return _rpc_error(None, -32600, "Invalid request id")
        params = packet.get("params", {})
        if not isinstance(params, dict) or not isinstance(params.get("_meta"), dict):
            return _rpc_error(ident, -32602, "Required metadata missing")
        meta = params["_meta"]
        if META_VERSION not in meta or META_CAPS not in meta or not isinstance(meta[META_CAPS], dict):
            return _rpc_error(ident, -32602, "Required metadata missing")
        if meta[META_VERSION] != VERSION:
            return _rpc_error(ident, -32022, "Unsupported protocol version",
                              {"supported": [VERSION], "requested": meta[META_VERSION]})
        method = packet["method"]
        if method == "server/discover":
            if set(params) != {"_meta"}:
                return _rpc_error(ident, -32602, "Invalid discovery arguments")
            return _success(ident, {"resultType": "complete", "ttlMs": 0, "cacheScope": "private",
                                    "supportedVersions": [VERSION],
                                    "capabilities": {"tools": {}},
                                    "instructions": "Single root; writes require launcher grant. No arbitrary paths, shell or network."})
        if method == "tools/list":
            if set(params) != {"_meta"}:
                return _rpc_error(ident, -32602, "Invalid list arguments")
            return _success(ident, {"resultType": "complete", "ttlMs": 0, "cacheScope": "private", "tools": [
                {"name": name, "description": DESCRIPTIONS[name],
                 "inputSchema": {"type": "object", "additionalProperties": False,
                                 "properties": props, "required": required}}
                for name, (required, props) in SCHEMAS.items()
                if self.writes or name not in WRITE_TOOLS]})
        if method != "tools/call":
            return _rpc_error(ident, -32601, "Method not found")
        if (set(params) - {"_meta", "name", "arguments"}
                or not isinstance(params.get("name"), str)
                or not isinstance(params.get("arguments", {}), dict)):
            return _rpc_error(ident, -32602, "Invalid tool call")
        name, args = params["name"], params.get("arguments", {})
        try:
            self._rate()
            if name not in SCHEMAS:
                # Tool lookup errors are protocol errors, not tool execution failures.
                return _rpc_error(ident, -32602, "Unknown tool")
            _limited(args)
            _validate_args(name, args)
            if name in WRITE_TOOLS and not self.writes:
                raise ToolFailure("PERMISSION_DENIED", "Mutating tool not granted by launcher")
            result = _perform(self.root, name, args)
        except ToolFailure as exc:
            result = {"ok": False, "error": {"code": exc.code, "message": str(exc)[:128]}}
        output = _success(ident, _tool_response(result))
        if len(json.dumps(output, separators=(",", ":"), allow_nan=False).encode("utf-8")) > MAX_RESPONSE:
            output = _success(ident, _tool_response({"ok": False, "error": {
                "code": "LIMIT_EXCEEDED", "message": "Response byte budget"}}))
        return output


def _exclusive_lock(root):
    lockpath = root / ".bmb-mcp.lock"
    if os.path.lexists(lockpath):
        _safe_part(lockpath, False)
    fd = os.open(lockpath, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


def run(root, writes=False, reader=None, writer=None):
    os.umask(0o077)
    server = Server(root, writes)
    lock = _exclusive_lock(server.root)
    reader = reader or sys.stdin.buffer
    writer = writer or sys.stdout.buffer
    try:
        while True:
            raw = reader.readline(MAX_FRAME + 2)
            if not raw:
                break
            if len(raw) > MAX_FRAME or not raw.endswith(b"\n"):
                response = _rpc_error(None, -32600, "Request frame too large")
                # Do not parse a partial frame as another message.
                writer.write(json.dumps(response).encode() + b"\n")
                writer.flush()
                break
            try:
                packet = _decode(raw)
                response = server.handle(packet)
            except ToolFailure as exc:
                response = _rpc_error(None, -32700 if exc.code == "INVALID_ARGUMENT" else -32600,
                                      "Malformed or excessive JSON")
            if response is not None:
                data = json.dumps(response, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
                writer.write(data + b"\n")
                writer.flush()
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description="BMB-023 stdio MCP, trusted single project launcher")
    parser.add_argument("--root", required=True, help="absolute pre-created private project directory")
    parser.add_argument("--allow-writes", action="store_true", help="grant mutating tools")
    args = parser.parse_args()
    try:
        run(args.root, args.allow_writes)
        return 0
    except (ToolFailure, OSError):
        print("MCP launch rejected: unsafe root, lock, or filesystem access", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
