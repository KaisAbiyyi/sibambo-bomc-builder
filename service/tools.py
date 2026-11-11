"""SE-03: transport-neutral tool dispatcher over the SE-02 project actor.

HTTP (``mcp_http``), the owner REST surface (``app``) and the authenticated local bridge
(``bridge``) all call the same ``Tools`` methods, so there is exactly one behaviour. Tools
call the actor directly: no CLI, no child process, no stdin, no journal, no disk. The service
never saves or exports anything.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from core.project import state as S
from core.project.actor import ActorRegistry, ProjectActor
from core.project.requests import RequestError, RequestStore
from core.project.state import ActorError, Grant, Lease
from service import errors
from service.auth import Principal, TicketStore
from service.guide.tool_descriptions import GUIDE_SHA256, GUIDE_VERSION

MAX_INSPECT_FACES = 200
MAX_DIAGNOSTICS = 50


class ToolFailure(Exception):
    """A tool call that failed with a catalogue code. State is never partially changed."""

    def __init__(self, code: str, message: str, **details):
        super().__init__(f"{code}: {message}")
        self.body = errors.error_body(code, message, **details)
        self.code = self.body["code"]


def _from_actor(exc: ActorError) -> ToolFailure:
    return ToolFailure(exc.code, exc.message, **exc.detail)


@dataclass
class ViewerCheck:
    """Writes need an active viewer. SE-05 replaces ``check`` with the real Editor channel ack."""
    check: object = None        # callable(actor, status) -> "ok" | "none" | "timeout"; default: owner heartbeat

    def __call__(self, actor: ProjectActor, status: dict) -> str:
        if self.check is not None:
            return self.check(actor, status)
        return "ok" if status["ownerAlive"] else "none"


class ProjectHost:
    """Owns the actor registry and the per-(tenant, project) service state. Exact lookups only."""

    def __init__(self, *, registry: ActorRegistry | None = None, requests: RequestStore | None = None,
                 tickets: TicketStore | None = None, viewer: ViewerCheck | None = None, **actor_defaults):
        self.registry = registry or ActorRegistry(**actor_defaults)
        self.requests = requests or RequestStore()
        self.tickets = tickets or TicketStore()
        self.viewer = viewer or ViewerCheck()
        self._lock = threading.Lock()
        self._epochs: dict[tuple[str, str], int] = {}
        self._write_gates: dict[tuple[str, str], threading.Lock] = {}

    def open_project(self, tenant: str, project: str, owner: Principal) -> ProjectActor:
        if owner.tenant != tenant:
            raise ToolFailure("FORBIDDEN", "principal is not in this tenant")
        with self._lock:
            try:
                actor = self.registry.open_epoch(tenant, project, owner.id)
            except ActorError as exc:
                raise _from_actor(exc) from exc
            self._epochs[(tenant, project)] = actor.epoch
            self._write_gates.setdefault((tenant, project), threading.Lock())
            return actor

    def actor(self, tenant: str, project: str) -> ProjectActor:
        """One answer for unknown and for someone else's project."""
        epoch = self._epochs.get((tenant, project)) if isinstance(tenant, str) and isinstance(project, str) else None
        if epoch is None:
            raise ToolFailure("NOT_FOUND", "no such project")
        try:
            return self.registry.get(tenant, project, epoch)
        except ActorError as exc:
            raise _from_actor(exc) from exc

    def gate(self, tenant: str, project: str) -> threading.Lock:
        return self._write_gates[(tenant, project)]


def _bounds(positions: list) -> list:
    if not positions:
        return [0.0] * 6
    lo = [min(p[i] for p in positions) for i in range(3)]
    hi = [max(p[i] for p in positions) for i in range(3)]
    return [round(v, 6) for v in lo + hi]


class Tools:
    def __init__(self, host: ProjectHost):
        self.host = host

    # ------------------------------------------------------------------ plumbing
    def _actor(self, principal: Principal, project: str) -> ProjectActor:
        return self.host.actor(principal.tenant, project)

    def _guard(self, project: str, args: dict) -> None:
        pid = args.get("projectId")
        if pid is not None and pid != project:
            raise ToolFailure("INVALID_REQUEST", "projectId must equal the project in the URL")

    def call(self, principal: Principal, project: str, name: str, args: dict | None = None) -> dict:
        args = dict(args or {})
        fn = getattr(self, "tool_" + name, None)
        if name not in TOOL_NAMES or fn is None:
            raise ToolFailure("INVALID_REQUEST", f"unknown tool {name!r}")
        self._guard(project, args)
        try:
            out = fn(principal, project, args)
        except ActorError as exc:
            raise _from_actor(exc) from exc
        except RequestError as exc:
            raise ToolFailure("INVALID_REQUEST", str(exc)) from exc
        out["projectId"] = project                 # exact requested projectId on every response
        return out

    # ------------------------------------------------------------------ reads
    def tool_read_project(self, principal, project, args):
        actor = self._actor(principal, project)
        view = actor.view(principal.id)
        status = actor.status(principal.id)
        modules = []
        for m in view["projection"]["modules"]:
            modules.append({"moduleId": m["moduleId"], "revision": m["revision"],
                            "faces": len(m["faces"]), "triangles": sum(len(f["triangles"]) for f in m["faces"]),
                            "bounds": _bounds(m["positions"])})
        return {"guideVersion": GUIDE_VERSION, "guideSha256": GUIDE_SHA256, "epoch": status["epoch"],
                "projectRevision": status["projectRevision"], "modules": modules,
                "removedModules": status["removedModules"], "canonicalIrSha256": view["canonicalIrSha256"],
                "projectionSha256": view["projectionSha256"], "writer": status["writer"],
                "fence": status["fence"], "paused": status["paused"], "ownerAlive": status["ownerAlive"]}

    def tool_inspect_module(self, principal, project, args):
        mid = args.get("moduleId")
        if not isinstance(mid, str):
            raise ToolFailure("INVALID_REQUEST", "moduleId is required")
        view = self._actor(principal, project).view(principal.id)
        module = next((m for m in view["projection"]["modules"] if m["moduleId"] == mid), None)
        if module is None:
            raise ToolFailure("NOT_FOUND", "no such module")
        faces = [{"faceId": f["faceId"], "role": f["role"], "label": f["label"], "triangles": len(f["triangles"])}
                 for f in module["faces"][:MAX_INSPECT_FACES]]
        return {"moduleId": mid, "revision": module["revision"], "bounds": _bounds(module["positions"]),
                "materials": [m["materialId"] for m in module["materials"]], "faceCount": len(module["faces"]),
                "facesTruncated": len(module["faces"]) > MAX_INSPECT_FACES, "faces": faces}

    def tool_operation_status(self, principal, project, args):
        st = self._actor(principal, project).status(principal.id)
        st = {k: v for k, v in st.items() if k not in ("tenant", "project")}
        st["writer"] = "you" if st["writer"] == principal.id else ("another" if st["writer"] else None)
        return st

    def tool_validate_draft(self, principal, project, args):
        actor = self._actor(principal, project)
        actor.view(principal.id)                                # authorizes read
        from bomc.compiler.graph_to_bomc import CompileError, compile_document
        from core.validator.validation import validate_assembly
        document = actor._state.project.document()              # read-only peek; SE-02 exposes no IR accessor yet
        modules = document["modules"]
        if not any(m["operations"] for m in modules):
            return {"valid": True, "diagnostics": [], "faceCount": 0, "triangleCount": 0, "note": "draft has no geometry yet"}
        report = validate_assembly(modules)
        diags = [d.to_dict() for d in report.diagnostics][:MAX_DIAGNOSTICS]
        out = {"valid": report.ok, "diagnostics": diags, "diagnosticsTruncated": len(report.diagnostics) > MAX_DIAGNOSTICS}
        try:
            compiled = compile_document(document)
            out.update(compiled=True, bomcSha256=compiled.sha256, faceCount=compiled.geometry_info["faceCount"],
                       triangleCount=compiled.geometry_info["triangleCount"])
        except CompileError as exc:
            out.update(valid=False, compiled=False, compileError=str(exc)[:300])
        return out

    def tool_read_owner_requests(self, principal, project, args):
        self._actor(principal, project).view(principal.id)      # needs a read grant
        since = args.get("sinceId", 0)
        items = self.host.requests.read(principal.tenant, project, since)
        return {"requests": items, "untrusted": True}

    # ------------------------------------------------------------------ writer lease and writes
    def tool_acquire_writer(self, principal, project, args):
        actor = self._actor(principal, project)
        self._preflight(actor, principal, write=False)
        lease = actor.acquire_lease(principal.id)
        return {"fence": lease.fence, "ttlSeconds": int(actor._lease_ttl)}

    def tool_release_writer(self, principal, project, args):
        fence = args.get("fence")
        if type(fence) is not int:
            raise ToolFailure("INVALID_REQUEST", "fence must be an integer")
        released = self._actor(principal, project).release_lease(principal.id, Lease(principal.id, fence, 0.0))
        return {"released": bool(released)}

    def _preflight(self, actor: ProjectActor, principal: Principal, *, write: bool) -> None:
        st = actor.status(principal.id)                         # also proves a read grant exists
        if st["paused"]:
            raise ToolFailure("PAUSED_BY_OWNER", "the owner paused agent writes")
        verdict = self.host.viewer(actor, st)
        if verdict == "none":
            raise ToolFailure("NO_ACTIVE_VIEWER", "no viewer has the project open")
        if verdict == "timeout":
            raise ToolFailure("RENDER_ACK_TIMEOUT", "the viewer did not acknowledge in time")

    def tool_apply_operation(self, principal, project, args):
        txn, fence = args.get("transaction"), args.get("fence")
        if not isinstance(txn, dict) or type(fence) is not int:
            raise ToolFailure("INVALID_REQUEST", "transaction (object) and fence (integer) are required")
        actor = self._actor(principal, project)
        self._preflight(actor, principal, write=True)
        gate = self.host.gate(principal.tenant, project)
        if not gate.acquire(blocking=False):                    # one write at a time per project
            raise ToolFailure("BUSY", "a write is already in flight for this project")
        try:
            return actor.submit(principal.id, Lease(principal.id, fence, 0.0), txn)
        finally:
            gate.release()


TOOL_NAMES = ("read_project", "inspect_module", "acquire_writer", "release_writer", "apply_operation",
              "operation_status", "validate_draft", "read_owner_requests")


class OwnerApi:
    """What the owner's BFF may do. Every response carries the exact requested projectId."""

    def __init__(self, host: ProjectHost):
        self.host = host

    def _own(self, principal: Principal, project: str) -> ProjectActor:
        actor = self.host.actor(principal.tenant, project)
        if actor.owner != principal.id:
            raise ToolFailure("FORBIDDEN", "only the project owner may do this")
        return actor

    def _wrap(self, project: str, body: dict) -> dict:
        return {"projectId": project, **body}

    def open(self, principal: Principal, project: str, new_epoch: bool = False) -> dict:
        """Idempotent: re-opening never discards an unsaved draft. Only an explicit ``newEpoch`` starts a
        fresh, empty epoch (the owner's restore decision, SE-08)."""
        if not new_epoch:
            try:
                existing = self.host.actor(principal.tenant, project)
            except ToolFailure:
                existing = None
            if existing is not None:
                if existing.owner != principal.id:
                    raise ToolFailure("FORBIDDEN", "only the project owner may do this")
                return self._wrap(project, {"epoch": existing.epoch, "created": False})
        actor = self.host.open_project(principal.tenant, project, principal)
        return self._wrap(project, {"epoch": actor.epoch, "created": True})

    def status(self, principal, project):
        actor = self._own(principal, project)
        return self._wrap(project, actor.status(principal.id))

    def heartbeat(self, principal, project):
        self._own(principal, project).owner_heartbeat(principal.id)
        return self._wrap(project, {"ok": True})

    def grant(self, principal, project, subject: str, client: str, scopes: list):
        actor = self._own(principal, project)
        try:
            actor.grant(principal.id, Grant(principal.tenant, project, subject, client, frozenset(scopes)))
        except ActorError as exc:
            raise _from_actor(exc) from exc
        return self._wrap(project, {"granted": subject, "scopes": sorted(scopes)})

    def revoke(self, principal, project, subject: str):
        existed = self._own(principal, project).revoke(principal.id, subject)
        return self._wrap(project, {"revoked": bool(existed)})

    def pause(self, principal, project):
        self._own(principal, project).pause(principal.id)
        return self._wrap(project, {"paused": True})

    def resume(self, principal, project):
        self._own(principal, project).resume(principal.id)
        return self._wrap(project, {"paused": False})

    def ticket(self, principal, project):
        self._own(principal, project)
        try:
            issued = self.host.tickets.issue(principal.tenant, project, principal.id)
        except OverflowError:
            raise ToolFailure("BUSY", "too many outstanding tickets") from None
        return self._wrap(project, issued)

    def post_request(self, principal, project, text: str):
        self._own(principal, project)
        try:
            rid = self.host.requests.post(principal.tenant, project, text)
        except RequestError as exc:
            raise ToolFailure("INVALID_REQUEST", str(exc)) from exc
        return self._wrap(project, {"requestId": rid})
