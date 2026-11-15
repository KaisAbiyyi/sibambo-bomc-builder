"""Explicit LOCAL DEMO mode (master SIB-TWO-PHASE-001 v1.6): one process, loopback only, no IdP.

Runs the canonical service (owner REST + draft WebSocket) and one stdio-bridge listener per local
agent client against ONE ``ProjectHost``/``ProjectActor``. The owner is authenticated by a launch-time
secret that only the Editor BFF holds (``LocalVerifier``); agents never use HTTP ``/mcp`` here.

This is not a remote/production configuration: it never binds a non-loopback address, never accepts a
JWT, and is only reachable through ``python -m service.local_demo``. Per-slot discovery is written
under the run root's ``private/`` and deleted on stop. Optional redacted session recordings persist
on D:. Stable client registrations are owned by the launcher (WP11).
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import signal
import stat
import sys
import threading
import time
import uuid
from pathlib import Path

from service.app import ServiceConfig, create_app
from service.auth import JwtVerifier, Principal, principal_id
from service.bridge import BridgeServer
from service.tools import OwnerApi, ProjectHost, Tools
from service.agent_relay import AgentRelay
from service.recorder import Recorder

LOCAL_ISSUER = "http://127.0.0.1/sibambo-local-demo"   # the MCP SDK requires a URL-shaped issuer
LOCAL_TENANT = "local"
OWNER_SUB, OWNER_CLIENT = "local-owner", "sibambo-editor-local"
CLIENTS = {"claude-code": "local-claude-code", "codex": "local-codex", "other": "local-other"}
SERVER_NAME = "sibambo_local"
TOOLS = ("read_project", "inspect_module", "acquire_writer", "release_writer", "apply_operation",
         "operation_status", "validate_draft", "read_owner_requests")
ROOT = Path(__file__).resolve().parents[1]


def principal(sub: str, client: str) -> Principal:
    return Principal(principal_id(LOCAL_ISSUER, sub, client), LOCAL_TENANT, LOCAL_ISSUER, sub, client)


class LocalVerifier(JwtVerifier):
    """Accepts exactly one opaque bearer (the owner secret). Never a JWT; HTTP ``/mcp`` always answers 401."""

    def __init__(self, owner_secret: str, audience: str):
        if len(owner_secret) < 32:
            raise ValueError("owner secret must be at least 32 characters")
        super().__init__(issuer=LOCAL_ISSUER, audience=audience, key_resolver=lambda token: None)
        self._secret = owner_secret.encode("utf-8")
        self._owner = principal(OWNER_SUB, OWNER_CLIENT)

    def principal_of(self, token: str):
        if isinstance(token, str) and hmac.compare_digest(token.encode("utf-8"), self._secret):
            return self._owner
        return None

    async def verify_token(self, token: str):
        return None


def _secure_private_path(path: Path, *, directory: bool) -> None:
    """Restrict and read back credential ACLs before any secret is written.

    The run root is protected too: writable parents could otherwise replace a
    protected child directory. Reparse points/symlinks and foreign owners are
    rejected rather than followed. Uses the existing hash-locked pywin32 on NT.
    """
    info = os.lstat(path)
    expected_kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_kind(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        raise PermissionError('Credential storage must use plain owner-controlled paths')
    if os.name == 'nt':
        import win32api, win32security, ntsecuritycon
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
        try:
            owner = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            default_owner = win32security.GetTokenInformation(token, win32security.TokenOwner)
        finally:
            token.Close()
        flags = win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION
        before = win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT, flags)
        if before.GetSecurityDescriptorOwner() not in (owner, default_owner):
            raise PermissionError('Credential storage is owned by another principal')
        inheritance = win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE if directory else 0
        acl = win32security.ACL()
        acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, inheritance, ntsecuritycon.FILE_ALL_ACCESS, owner)
        win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
            flags | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            owner, None, acl, None)
        after = win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT, flags)
        actual = after.GetSecurityDescriptorDacl()
        if (after.GetSecurityDescriptorOwner() != owner or actual is None or actual.GetAceCount() != 1
                or not after.GetSecurityDescriptorControl()[0] & win32security.SE_DACL_PROTECTED
                or actual.GetAce(0) != ((win32security.ACCESS_ALLOWED_ACE_TYPE, inheritance), ntsecuritycon.FILE_ALL_ACCESS, owner)):
            raise PermissionError('Unable to verify private credential ACL')
    else:
        if info.st_uid != os.geteuid():
            raise PermissionError('Credential storage is owned by another principal')
        mode = 0o700 if directory else 0o600
        os.chmod(path, mode, follow_symlinks=False)
        after = os.lstat(path)
        if after.st_uid != os.geteuid() or stat.S_IMODE(after.st_mode) != mode:
            raise PermissionError('Unable to verify private credential permissions')


class LocalDemo:
    def __init__(self, *, project: str, port: int, owner_secret: str, editor_origins, clients=tuple(CLIENTS),
                 record_root=Path('D:/projects/sibambo/outputs/mcp-sessions'), no_record=False):
        unknown = [c for c in clients if c not in CLIENTS]
        if unknown:
            raise ValueError("unknown client " + unknown[0])
        self.project, self.port, self.clients = project, port, tuple(clients)
        self.host = ProjectHost()
        self.owner = principal(OWNER_SUB, OWNER_CLIENT)
        api = OwnerApi(self.host)
        api.open(self.owner, project)
        self.bridges: dict[str, BridgeServer] = {}
        self.relay = AgentRelay(None, Recorder(record_root, not no_record))
        self.relay.scope = (LOCAL_TENANT, project)
        self._discovery = []
        self.agents: dict[str, Principal] = {}
        for client in self.clients:
            agent = principal(CLIENTS[client], client)
            api.grant(self.owner, project, agent.id, client, ["read", "write"])
            self.host.drafts.identities[agent.id] = agent.subject
            self.agents[client] = agent
            self.bridges[client] = BridgeServer(Tools(self.host), agent, project, relay=self.relay, slot=client)
        audience = f"http://127.0.0.1:{port}/mcp"
        config = ServiceConfig(issuer=LOCAL_ISSUER, audience=audience,
                               allowed_hosts=(f"127.0.0.1:{port}", f"localhost:{port}"),
                               allowed_origins=tuple(editor_origins))
        self.app = create_app(config, verifier=LocalVerifier(owner_secret, audience), host=self.host, relay=self.relay)

    def start_bridges(self) -> None:
        for bridge in self.bridges.values():
            bridge.start()

    def stop(self) -> None:
        for bridge in self.bridges.values():
            bridge.stop()
        for path in self._discovery:
            try:
                # Do not delete a discovery file replaced by another service instance.
                info = json.loads(path.read_text(encoding='utf-8'))
                if info.get('secret') == self.bridges[info.get('slot')].secret:
                    path.unlink()
            except (OSError, ValueError, KeyError):
                pass

    def epoch(self) -> str:
        return self.host.drafts.channel(self.host.actor(LOCAL_TENANT, self.project)).epoch

    def write_client_files(self, run_root: Path) -> dict:
        """Atomic per-slot discovery only; stable registrations are owned by WP11."""
        _refuse_c_drive(run_root)
        run_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _secure_private_path(run_root, directory=True)
        private = run_root / "private"
        private.mkdir(mode=0o700, exist_ok=True)
        _secure_private_path(private, directory=True)
        (run_root / "tmp").mkdir(parents=True, exist_ok=True)
        python = Path(sys.executable).as_posix()
        for client, bridge in self.bridges.items():
            path = private / f'bridge-{client}.json'
            body = {'addr': f'{bridge.address[0]}:{bridge.address[1]}', 'secret': bridge.secret,
                    'project': self.project, 'epoch': self.epoch(), 'slot': client}
            if path.exists() or path.is_symlink():
                _secure_private_path(path, directory=False)
            temp = private / f'.bridge-{client}-{uuid.uuid4().hex}.tmp'
            try:
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
                    _secure_private_path(temp, directory=False)
                    json.dump(body, handle, separators=(',', ':'))
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
            if path not in self._discovery:
                self._discovery.append(path)
        return {"schemaVersion": 1, "mode": "local-demo", "project": self.project, "servicePort": self.port,
                "serverName": SERVER_NAME, "clients": list(self.clients), "epoch": self.epoch(), "pid": os.getpid(),
                "python": python, "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def _refuse_c_drive(path: Path) -> None:
    if os.name == "nt" and path.resolve().drive.upper() == "C:":
        raise SystemExit("run root must not be on C: (workspace storage rule)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m service.local_demo", description=__doc__.splitlines()[0])
    parser.add_argument("--project", default="local-demo")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--clients", default=",".join(CLIENTS))
    parser.add_argument('--record-root', type=Path, default=Path('D:/projects/sibambo/outputs/mcp-sessions'))
    parser.add_argument('--no-record', action='store_true')
    parser.add_argument("--editor-origin", action="append", default=None)
    args = parser.parse_args(argv)
    if args.bind != "127.0.0.1":
        print("local demo binds 127.0.0.1 only", file=sys.stderr)
        return 2
    secret = os.environ.get("SIBAMBO_LOCAL_OWNER_TOKEN", "")
    if len(secret) < 32:
        print("SIBAMBO_LOCAL_OWNER_TOKEN (>= 32 chars) is required", file=sys.stderr)
        return 2
    try:
        _refuse_c_drive(args.run_root)
        origins = args.editor_origin or ["http://localhost:5175", "http://127.0.0.1:5175"]
        demo = LocalDemo(project=args.project, port=args.port, owner_secret=secret, editor_origins=origins,
                         clients=tuple(c for c in args.clients.split(",") if c),
                         record_root=args.record_root, no_record=args.no_record)
    except (ValueError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(demo.app, host="127.0.0.1", port=args.port, log_level="warning",
                                           access_log=False, lifespan="on"))
    demo.start_bridges()
    ready = threading.Event()

    def announce():
        deadline = time.time() + 60
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        if server.started:
            try:
                manifest = demo.write_client_files(args.run_root)
                (args.run_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            except Exception:
                # Storage errors must not leave a service advertising unprotected
                # credentials. Do not log the credential-bearing object or error.
                print('Local discovery storage could not be secured; service stopping.', file=sys.stderr)
                server.should_exit = True
                return
            ready.set()
            print("LOCAL_DEMO_READY", flush=True)
        else:
            server.should_exit = True
    threading.Thread(target=announce, daemon=True).start()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: setattr(server, "should_exit", True))
        except (ValueError, OSError):
            pass
    try:
        server.run()
    finally:
        demo.stop()
    return 0 if ready.is_set() else 2


if __name__ == "__main__":                       # pragma: no cover
    sys.exit(main())
