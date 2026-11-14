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
import sys
import threading
import time
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
        private = run_root / "private"
        private.mkdir(parents=True, exist_ok=True)
        (run_root / "tmp").mkdir(parents=True, exist_ok=True)
        python = Path(sys.executable).as_posix()
        for client, bridge in self.bridges.items():
            path = private / f'bridge-{client}.json'
            body = {'addr': f'{bridge.address[0]}:{bridge.address[1]}', 'secret': bridge.secret,
                    'project': self.project, 'epoch': self.epoch(), 'slot': client}
            temp = path.with_suffix('.json.tmp')
            try:
                temp.write_text(json.dumps(body, separators=(',', ':')), encoding='utf-8')
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

    def announce():
        deadline = time.time() + 60
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        if server.started:
            manifest = demo.write_client_files(args.run_root)
            (args.run_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
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
    return 0 if server.started else 2


if __name__ == "__main__":                       # pragma: no cover
    sys.exit(main())
