"""SE-03 (D16 S2): authenticated local bridge between a stdio MCP client and the one canonical actor.

The stdio process must never own a draft of its own: it forwards every tool call to this
bridge, which runs it through the same ``Tools`` (and so the same ``ProjectActor``) as the
HTTP service. The trusted launcher decides the principal and project; the local client only
holds a per-launch random secret.

Transport: loopback TCP bound to 127.0.0.1 on an ephemeral port, newline-delimited JSON frames
(max 1 MiB). Every frame carries the secret, compared in constant time; a frame without it (or
with a wrong one) is dropped and the connection closed with no detail. Not a remote channel and
not an OS sandbox: another process of the same OS user that learns the secret can use it, which
is why the secret lives only in the launcher's environment and is never logged.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import socketserver
import threading
from pathlib import Path

from service import errors
from service.auth import Principal
from service.tools import ToolFailure, Tools

MAX_FRAME = 1024 * 1024
HOST = "127.0.0.1"
ENV_ADDR, ENV_SECRET, ENV_PROJECT = "SIBAMBO_BRIDGE_ADDR", "SIBAMBO_BRIDGE_SECRET", "SIBAMBO_BRIDGE_PROJECT"
ENV_SECRET_FILE = "SIBAMBO_BRIDGE_SECRET_FILE"


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        server: BridgeServer = self.server.owner                # type: ignore[attr-defined]
        for _ in range(1000):                                    # bounded frames per connection
            line = self.rfile.readline(MAX_FRAME + 1)
            if not line or len(line) > MAX_FRAME:
                return
            try:
                frame = json.loads(line.decode("utf-8"))
                supplied = frame.get("secret")
            except (UnicodeError, ValueError, AttributeError):
                return
            if not (isinstance(supplied, str) and hmac.compare_digest(supplied.encode(), server.secret.encode())):
                return                                           # refuse silently: no oracle, no detail
            reply = server.dispatch(frame)
            raw = (json.dumps(reply, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if frame.get('api') == 'addon-1' and len(raw) > 4 * MAX_FRAME:
                raw = (json.dumps({'id': frame.get('id'), 'ok': False,
                    'error': errors.error_body('BUDGET_EXCEEDED', 'Add-on result exceeds 4 MiB')}) + '\n').encode('utf-8')
            self.wfile.write(raw)
            self.wfile.flush()


class _TCP(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True
    request_queue_size = 8


class BridgeServer:
    def __init__(self, tools: Tools, principal: Principal, project: str, *, secret: str | None = None, relay=None, slot=None):
        self.tools, self.principal, self.project = tools, principal, project
        self.relay, self.slot = relay, slot
        self.secret = secret or secrets.token_hex(32)           # 64 hex chars, per launch
        self._srv = _TCP((HOST, 0), _Handler)                   # loopback only, ephemeral port
        self._srv.owner = self
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def address(self) -> tuple[str, int]:
        return self._srv.server_address[:2]

    def start(self) -> "BridgeServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._thread.is_alive():              # shutdown() would block forever on a never-started server
            self._srv.shutdown()
            self._thread.join(timeout=5)
        self._srv.server_close()

    def env(self) -> dict:
        """Environment for the stdio child: address, project and the secret (never printed)."""
        return {ENV_ADDR: f"{self.address[0]}:{self.address[1]}", ENV_SECRET: self.secret, ENV_PROJECT: self.project}

    def dispatch(self, frame: dict) -> dict:
        rid, tool, args = frame.get("id"), frame.get("tool"), frame.get("args") or {}
        if frame.get('api') == 'addon-1':
            args = frame.get('args')
        if not isinstance(tool, str) or not isinstance(args, dict):
            return {"id": rid, "ok": False, "error": errors.error_body("INVALID_REQUEST", "tool and args are required")}
        if frame.get('api') == 'addon-1':
            if self.relay is None:
                return {'id': rid, 'ok': False, 'error': errors.error_body('INVALID_REQUEST', 'Add-on relay is not configured')}
            return {'id': rid, **self.relay.call_sync(self.slot, frame.get('session'), tool, args)}
        try:
            return {"id": rid, "ok": True, "result": self.tools.call(self.principal, self.project, tool, args)}
        except ToolFailure as failure:
            return {"id": rid, "ok": False, "error": failure.body}


def bridge_call(tool: str, args: dict, *, env=os.environ, timeout: float = 30.0) -> dict:
    """Client side (used by the stdio process). Returns {"ok", "result"|"error"}."""
    try:
        host, port = env[ENV_ADDR].rsplit(":", 1)
        secret = env.get(ENV_SECRET)
        if secret is None:                       # launcher-provided private file keeps the secret out of client argv/env
            with open(env[ENV_SECRET_FILE], "r", encoding="utf-8") as handle:
                secret = handle.read(257).strip()
            if not secret or len(secret) > 256:
                raise ValueError("bad secret file")
    except (KeyError, ValueError, OSError):
        return {"ok": False, "error": errors.error_body("UNAUTHENTICATED", "bridge address/secret are not configured")}
    if host != HOST:
        return {"ok": False, "error": errors.error_body("UNAUTHENTICATED", "bridge must be on 127.0.0.1")}
    frame = json.dumps({"secret": secret, "id": 1, "tool": tool, "args": args}, separators=(",", ":")) + "\n"
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.sendall(frame.encode("utf-8"))
            reply = sock.makefile("rb").readline(MAX_FRAME + 1)
    except OSError:
        return {"ok": False, "error": errors.error_body("UNAUTHENTICATED", "bridge unreachable")}
    if not reply:
        return {"ok": False, "error": errors.error_body("UNAUTHENTICATED", "bridge refused the request")}
    return json.loads(reply.decode("utf-8"))


def bridge_call_addon(tool, args, run_root, slot, session):
    """Re-read atomic discovery on every call; never accept a non-loopback address."""
    from service.recorder import SLOT
    message = 'Sibambo local service is not running. Ask the owner to run: node tooling/local-demo/launch.mjs'
    def offline():
        return {'ok': False, 'error': errors.error_body('SERVICE_OFFLINE', message)}
    try:
        if not isinstance(slot, str) or not SLOT.fullmatch(slot):
            return offline()
        with (Path(run_root) / 'private' / f'bridge-{slot}.json').open('rb') as handle:
            raw = handle.read(4097)
        if len(raw) > 4096:
            return offline()
        info = json.loads(raw)
        if not isinstance(info, dict) or set(info) != {'addr', 'secret', 'project', 'epoch', 'slot'}:
            return offline()
        if info['slot'] != slot or not all(isinstance(info[k], str) and info[k] for k in info):
            return offline()
        host, port = info['addr'].rsplit(':', 1)
        if host != HOST or not 1 <= int(port) <= 65535 or len(info['secret']) != 64:
            return offline()
        frame = json.dumps({'secret': info['secret'], 'id': 1, 'api': 'addon-1', 'session': session,
                            'tool': tool, 'args': args}, allow_nan=False, separators=(',', ':')).encode('utf-8') + b'\n'
        if len(frame) > 256 * 1024:
            return {'ok': False, 'error': errors.error_body('BUDGET_EXCEEDED', 'Add-on request exceeds 256 KiB')}
        with socket.create_connection((host, int(port)), timeout=130) as sock:
            sock.sendall(frame)
            reply = sock.makefile('rb').readline(4 * MAX_FRAME + 1)
        if not reply or len(reply) > 4 * MAX_FRAME:
            return offline()
        parsed = json.loads(reply)
        if not isinstance(parsed, dict) or parsed.get('id') != 1 or type(parsed.get('ok')) is not bool:
            return offline()
        return parsed
    except TimeoutError:
        return {'ok': False, 'error': errors.error_body('EDITOR_TIMEOUT',
            'The Editor may still finish; call describe_scene before retrying')}
    except (KeyError, ValueError, TypeError, AttributeError, OSError, RecursionError):
        return offline()
