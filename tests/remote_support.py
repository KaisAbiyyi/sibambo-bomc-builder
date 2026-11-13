"""Shared harness for the SE-03 remote-MCP tests: a synthetic identity provider (RSA keys, no
network), a self-signed TLS certificate for 127.0.0.1 and a real uvicorn server in a thread.
Everything is wholly synthetic and local; no credential, tunnel or external service is used.
"""
from __future__ import annotations

import datetime
import socket
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import jwt
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from service.app import ServiceConfig, create_app
from service.auth import JwtVerifier, principal_id
from service.tools import ProjectHost

ISSUER = "https://idp.sibambo.test/"
TENANT = "acme"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def self_signed(directory: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1")),
                                                        x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return cert_path, key_path


class Env:
    """One TLS server + one synthetic IdP key set."""

    def __init__(self, *, host: ProjectHost | None = None, allowed_origins=("https://editor.sibambo.test",),
                 tls: bool = True, port: int | None = None):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.port = port or _free_port()
        self.scheme = "https" if tls else "http"
        self.base = f"{self.scheme}://127.0.0.1:{self.port}"
        self.audience = f"{self.base}/mcp"
        self.host = host or ProjectHost()
        config = ServiceConfig(issuer=ISSUER, audience=self.audience,
                               allowed_hosts=(f"127.0.0.1:{self.port}",), allowed_origins=tuple(allowed_origins))
        pub = self.key.public_key()
        verifier = JwtVerifier(issuer=ISSUER, audience=self.audience, key_resolver=lambda token: pub)
        self.app = create_app(config, verifier=verifier, host=self.host)
        kw = {}
        self.verify: str | bool = False
        if tls:
            cert, key = self_signed(self.dir)
            kw = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
            self.verify = str(cert)
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                                    log_level="critical", lifespan="on", **kw))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> "Env":
        self.thread.start()
        deadline = time.time() + 20
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("test server did not start")
            time.sleep(0.05)
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.tmp.cleanup()

    # ---- identities -----------------------------------------------------------
    def mint(self, sub: str, *, tenant: str | None = TENANT, aud: str | None = None, iss: str = ISSUER,
             expires_in: int = 300, key=None, alg: str = "RS256", client: str = "Test Client", **extra) -> str:
        now = int(time.time())
        claims = {"iss": iss, "aud": aud or self.audience, "sub": sub, "iat": now, "exp": now + expires_in,
                  "azp": client, "scope": "mcp", **extra}
        if tenant is not None:
            claims["tenant"] = tenant
        return jwt.encode(claims, key or self.key, algorithm=alg)

    @staticmethod
    def pid(sub: str) -> str:
        return principal_id(ISSUER, sub)

    # ---- http -----------------------------------------------------------------
    def http(self, token: str | None = None, **kw) -> httpx2.AsyncClient:
        headers = dict(kw.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return httpx2.AsyncClient(verify=self.verify, headers=headers, timeout=kw.pop("timeout", 20), **kw)

    @asynccontextmanager
    async def client(self, token: str, project: str, *, mode: str = "auto"):
        async with self.http(token) as http:
            transport = streamable_http_client(f"{self.audience}?project={project}", http_client=http)
            async with Client(transport, mode=mode) as client:
                yield client

    async def owner_post(self, owner_token: str, project: str, action: str, body: dict | None = None):
        async with self.http(owner_token) as http:
            return await http.post(f"{self.base}/owner/v1/projects/{project}/{action}", json=body or {})

    async def setup_project(self, project: str = "home", owner: str = "owner-1", agents=(("agent-1", ("read", "write")),)):
        token = self.mint(owner)
        for response in [await self.owner_post(token, project, "open")]:
            assert response.status_code == 200, response.text
        for sub, scopes in agents:
            r = await self.owner_post(token, project, "grants", {"sub": sub, "client": "Test Client", "scopes": list(scopes)})
            assert r.status_code == 200, r.text
        r = await self.owner_post(token, project, "heartbeat")
        assert r.status_code == 200, r.text
        return token
