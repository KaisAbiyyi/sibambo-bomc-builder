"""SE-03: ASGI application: remote MCP at ``POST /mcp?project=<id>``, the owner REST surface under
``/owner/v1`` and ``/healthz``. Run behind TLS with ``python -m service.app`` (loopback by default).

Configuration is environment only and carries no secret: ``SIBAMBO_ISSUER``, ``SIBAMBO_AUDIENCE``
(this resource's URL), ``SIBAMBO_JWKS_URL`` (https), ``SIBAMBO_TENANT_CLAIM``,
``SIBAMBO_ALLOWED_HOSTS`` and ``SIBAMBO_ALLOWED_ORIGINS`` (comma separated). Nothing is persisted.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from starlette.requests import Request
from starlette.responses import JSONResponse

from service import errors
from service.auth import JwtVerifier, Principal, jwks_resolver
from service.mcp_http import EdgeGuard, build_server, security_settings
from service.tools import OwnerApi, ProjectHost, ToolFailure, Tools

MAX_OWNER_BODY = 16 * 1024


@dataclass(frozen=True)
class ServiceConfig:
    issuer: str
    audience: str
    jwks_url: str = ""
    tenant_claim: str = "tenant"
    allowed_hosts: tuple = ("127.0.0.1:*", "localhost:*")
    allowed_origins: tuple = ()
    required_scopes: tuple = ()

    @staticmethod
    def from_env(env=os.environ) -> "ServiceConfig":
        def csv(name, default=""):
            return tuple(x.strip() for x in env.get(name, default).split(",") if x.strip())
        return ServiceConfig(env["SIBAMBO_ISSUER"], env["SIBAMBO_AUDIENCE"], env.get("SIBAMBO_JWKS_URL", ""),
                             env.get("SIBAMBO_TENANT_CLAIM", "tenant"),
                             csv("SIBAMBO_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*"), csv("SIBAMBO_ALLOWED_ORIGINS"),
                             csv("SIBAMBO_REQUIRED_SCOPES"))


def _fail(project: str | None, failure: ToolFailure) -> JSONResponse:
    body = {"error": failure.body}
    if project is not None:
        body["projectId"] = project
    return JSONResponse(body, status_code=errors.http_status(failure.code), headers={"X-Accel-Buffering": "no"})


def create_app(config: ServiceConfig, *, verifier: JwtVerifier | None = None, host: ProjectHost | None = None):
    host = host or ProjectHost()
    verifier = verifier or JwtVerifier(issuer=config.issuer, audience=config.audience,
                                       key_resolver=jwks_resolver(config.jwks_url), tenant_claim=config.tenant_claim)
    server = build_server(Tools(host), verifier, resource_url=config.audience, required_scopes=config.required_scopes)
    owner = OwnerApi(host)

    async def authed(request: Request) -> tuple[Principal | None, JSONResponse | None]:
        import asyncio
        auth = request.headers.get("authorization", "")
        principal = None
        if auth[:7].lower() == "bearer ":
            principal = await asyncio.to_thread(verifier.principal_of, auth[7:].strip())
        if principal is None:
            body = {"error": errors.error_body("UNAUTHENTICATED", "a valid bearer token is required")}
            return None, JSONResponse(body, status_code=401, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})
        return principal, None

    async def read_json(request: Request) -> dict:
        raw = await request.body()
        if len(raw) > MAX_OWNER_BODY:
            raise ToolFailure("INVALID_REQUEST", "body exceeds 16 KiB")
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise ToolFailure("INVALID_REQUEST", "body is not UTF-8 JSON") from None
        if not isinstance(data, dict):
            raise ToolFailure("INVALID_REQUEST", "body must be a JSON object")
        return data

    def route(path: str, methods: list[str], fn):
        @server.custom_route(path, methods=methods)
        async def handler(request: Request):
            principal, denied = await authed(request)
            if denied is not None:
                return denied
            project = request.path_params.get("project")
            try:
                body = await read_json(request) if request.method == "POST" else {}
                return JSONResponse(fn(principal, project, body), headers={"X-Accel-Buffering": "no"})
            except ToolFailure as failure:
                return _fail(project, failure)
        return handler

    base = "/owner/v1/projects/{project}"
    route(base + "/open", ["POST"], lambda p, j, b: owner.open(p, j, b.get("newEpoch") is True))
    route(base, ["GET"], lambda p, j, b: owner.status(p, j))
    route(base + "/heartbeat", ["POST"], lambda p, j, b: owner.heartbeat(p, j))
    route(base + "/pause", ["POST"], lambda p, j, b: owner.pause(p, j))
    route(base + "/resume", ["POST"], lambda p, j, b: owner.resume(p, j))
    route(base + "/ticket", ["POST"], lambda p, j, b: owner.ticket(p, j))

    def grant(p, j, b):
        sub, client, scopes = b.get("sub"), b.get("client"), b.get("scopes")
        if not (isinstance(sub, str) and sub and isinstance(client, str) and isinstance(scopes, list)):
            raise ToolFailure("INVALID_REQUEST", "sub, client and scopes[] are required")
        from service.auth import principal_id
        subject = principal_id(p.issuer, sub, client)
        result = owner.grant(p, j, subject, client, scopes)
        with host.drafts.lock:
            host.drafts.identities[subject] = sub
        return result

    def revoke(p, j, b):
        sub = b.get("sub")
        if not isinstance(sub, str) or not sub:
            raise ToolFailure("INVALID_REQUEST", "sub is required")
        from service.auth import principal_id
        actor = owner._own(p, j)
        targets = [gid for gid in actor._grants if host.drafts.identities.get(gid) == sub]
        revoked = [owner.revoke(p, j, gid)['revoked'] for gid in targets]
        return {'projectId': j, 'revoked': any(revoked)}

    route(base + "/grants", ["POST"], grant)
    route(base + "/revoke", ["POST"], revoke)
    route(base + "/requests", ["POST"], lambda p, j, b: owner.post_request(p, j, b.get("text")))

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request):
        return JSONResponse({"ok": True})

    inner = server.streamable_http_app(
        stateless_http=True,
        transport_security=security_settings(config.allowed_hosts, config.allowed_origins),
        max_request_body_size=256 * 1024)
    app = EdgeGuard(inner, verifier, host)
    from service.owner_mcp import OwnerMcp
    from service.draft_ws import DraftSocket
    app = DraftSocket(OwnerMcp(app, host, verifier), host.drafts, config.allowed_origins, config.allowed_hosts)
    app.host_state = host                      # test/ops handle; the app holds no other global state
    app.inner = inner
    return app


def main() -> None:                            # pragma: no cover - process entry point
    import uvicorn
    config = ServiceConfig.from_env()
    uvicorn.run(create_app(config), host=os.environ.get("SIBAMBO_BIND", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8765")), log_level="warning", proxy_headers=True,
                forwarded_allow_ips=os.environ.get("SIBAMBO_FORWARDED_ALLOW_IPS", "127.0.0.1"))


if __name__ == "__main__":                     # pragma: no cover
    main()
