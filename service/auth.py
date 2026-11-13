"""SE-03: OAuth 2.1 resource-server token validation and single-use owner tickets.

The service is only a *resource server*: an external managed authorization server issues
the tokens (PKCE S256 is enforced there; this module never mints an access token). A token
is accepted only if its signature verifies against the issuer's keys, ``alg`` is on a
strict allow-list (never ``none``/HMAC), ``iss`` and ``aud`` match exactly, ``exp`` is in
the future, and it carries ``sub`` and a tenant claim. Provider credentials are never
accepted, forwarded or stored; unverified ``clientInfo`` is display data only. The
signature-verified ``azp``/``client_id`` binds the OAuth application to the principal and
the MCP session id is never authentication (the transport mints none).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import hmac
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from mcp.server.auth.provider import AccessToken

ALGORITHMS = ("RS256", "ES256")
TENANT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
TICKET_MIN, TICKET_MAX, TICKET_MAX_TTL = 32, 512, 300


@dataclass(frozen=True)
class Principal:
    """Verified credential identity (issuer, sub, OAuth client), never an MCP display name."""
    id: str
    tenant: str
    issuer: str
    subject: str
    client: str          # signature-verified OAuth client; an explicit grant is still required


def principal_id(issuer: str, subject: str, client: str | None = None) -> str:
    # Legacy two-argument helpers retain their identity bytes; verified OAuth always supplies client.
    identity = f"{issuer}\n{subject}" if client is None else json.dumps([issuer, subject, client], ensure_ascii=False, separators=(',', ':'))
    return "p-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40]


class JwtVerifier:
    """``TokenVerifier`` for the MCP SDK. ``key_resolver(token) -> key`` is injected so tests use a
    static key set and production uses the issuer's JWKS (see ``jwks_resolver``)."""

    def __init__(self, *, issuer: str, audience: str, key_resolver, tenant_claim: str = "tenant",
                 algorithms=ALGORITHMS, leeway: int = 30):
        if not (issuer and audience and callable(key_resolver)):
            raise ValueError("issuer, audience and key_resolver are required")
        if set(algorithms) - set(ALGORITHMS):
            raise ValueError("only asymmetric RS256/ES256 are allowed")
        self.issuer, self.audience, self._resolve = issuer, audience, key_resolver
        self.tenant_claim, self.algorithms, self.leeway = tenant_claim, tuple(algorithms), int(leeway)

    def principal_of(self, token: str) -> Principal | None:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in self.algorithms:
                return None
            claims = jwt.decode(token, self._resolve(token), algorithms=list(self.algorithms),
                                audience=self.audience, issuer=self.issuer, leeway=self.leeway,
                                options={"require": ["exp", "iss", "aud", "sub"]})
        except Exception:                                    # any failure is one uniform 401
            return None
        sub, tenant = claims.get("sub"), claims.get(self.tenant_claim)
        if not (isinstance(sub, str) and sub and isinstance(tenant, str) and TENANT_RE.match(tenant)):
            return None
        client = claims.get("azp") or claims.get("client_id")
        if not isinstance(client, str) or not client or len(client) > 128:
            return None
        return Principal(principal_id(self.issuer, sub, client), tenant, self.issuer, sub, client)

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = await asyncio.to_thread(self.principal_of, token)   # JWKS fetch may block
        if principal is None:
            return None
        claims = jwt.decode(token, options={"verify_signature": False})  # already verified above
        scope = claims.get("scope", "")
        scopes = scope.split() if isinstance(scope, str) else [s for s in claims.get("scp", []) if isinstance(s, str)]
        return AccessToken(token=token, client_id=principal.client, scopes=scopes,
                           expires_at=int(claims["exp"]), resource=self.audience, subject=principal.subject,
                           claims={"iss": principal.issuer, "tenant": principal.tenant, "principal": principal.id})


def principal_from_access(access: AccessToken | None) -> Principal | None:
    if access is None or not access.claims:
        return None
    c = access.claims
    if not all(isinstance(c.get(k), str) for k in ("iss", "tenant", "principal")) or access.subject is None:
        return None
    return Principal(c["principal"], c["tenant"], c["iss"], access.subject, access.client_id)


def jwks_resolver(jwks_url: str):
    """Production resolver: the issuer's JWKS over HTTPS (cached by PyJWT). Not used in tests."""
    if not jwks_url.startswith("https://"):
        raise ValueError("JWKS URL must be https")
    client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300)
    return lambda token: client.get_signing_key_from_jwt(token).key


class TicketStore:
    """Single-use, short-lived tickets the owner BFF hands to the Editor for the SE-05 WebSocket.

    Shape: URL-safe token of 32..512 characters; expiry is a UTC instant in the future and at
    most 300 seconds away; only a SHA-256 of the ticket is kept; ``consume`` is atomic, burns
    the ticket on first sight (success or not) and returns one uniform ``None`` on any failure.
    """

    def __init__(self, *, ttl_seconds: int = 120, now=None, max_outstanding: int = 1024):
        if not (1 <= ttl_seconds <= TICKET_MAX_TTL):
            raise ValueError("ticket ttl must be 1..300 seconds")
        self._ttl, self._max = int(ttl_seconds), max_outstanding
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._live: dict[str, tuple[datetime, str, str, str]] = {}

    @staticmethod
    def _digest(ticket: str) -> str:
        return hashlib.sha256(ticket.encode("utf-8")).hexdigest()

    def issue(self, tenant: str, project: str, owner_principal: str) -> dict:
        ticket = secrets.token_urlsafe(48)                      # 64 characters
        assert TICKET_MIN <= len(ticket) <= TICKET_MAX
        with self._lock:
            now = self._now()
            for key in [k for k, v in self._live.items() if v[0] <= now]:
                del self._live[key]
            if len(self._live) >= self._max:
                raise OverflowError("too many outstanding tickets")
            expires = now + timedelta(seconds=self._ttl)
            self._live[self._digest(ticket)] = (expires, tenant, project, owner_principal)
        return {"ticket": ticket, "ttlSeconds": self._ttl,
                "expiresAt": expires.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def consume(self, ticket: object, tenant: str, project: str) -> str | None:
        if not (isinstance(ticket, str) and TICKET_MIN <= len(ticket) <= TICKET_MAX):
            return None
        with self._lock:
            entry = self._live.pop(self._digest(ticket), None)  # burned on first sight
            now = self._now()
        if entry is None or entry[0] <= now:
            return None
        ok = hmac.compare_digest(entry[1], tenant) & hmac.compare_digest(entry[2], project)
        return entry[3] if ok else None
