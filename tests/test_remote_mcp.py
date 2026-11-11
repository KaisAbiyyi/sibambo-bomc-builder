"""SE-03 gates: authenticated remote Streamable HTTP MCP adapter over the SE-02 actor.

A real MCP SDK client (mcp==2.3.0) talks to a real uvicorn server over TLS (self-signed cert for
127.0.0.1, synthetic RSA identity provider). Wholly synthetic and local. It does NOT exercise a
managed Auth0 tenant, a public tunnel, the real Claude Code / Codex clients, the Editor or the
WebSocket (SE-04/05/11 and the owner S5 probe own those).
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jwt  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402
from mcp import Client, StdioServerParameters  # noqa: E402

from core.identity import store as identity_store  # noqa: E402
from core.project.actor import ActorRegistry  # noqa: E402
from core.project.requests import RequestError, RequestStore  # noqa: E402
from examples import bmb026_house as house  # noqa: E402
from service import errors  # noqa: E402
from service.auth import JwtVerifier, Principal, TicketStore  # noqa: E402
from service.bridge import BridgeServer, bridge_call  # noqa: E402
from service.guide.tool_descriptions import GUIDE_SHA256, GUIDE_VERSION, TOOLS  # noqa: E402
from service.tools import OwnerApi, ProjectHost, ToolFailure, Tools, ViewerCheck, _from_actor  # noqa: E402
from tests.remote_support import ISSUER, TENANT, Env  # noqa: E402

ENV: Env | None = None


def setUpModule():
    global ENV
    ENV = Env().start()


def tearDownModule():
    ENV.stop()


def txn(base, changes, key):
    return {"schemaVersion": "draft-operation-v1", "transactionId": key, "idempotencyKey": key,
            "baseProjectRevision": base, "changes": changes}


def room_pair():
    modules = {n: house._room(n, False) for n in ("living", "bedroom-a")}
    before = {n: copy.deepcopy(m) for n, m in modules.items()}
    house._connect(modules, "living", "bedroom-a", "east", "living-a", opening_offset=1.0)
    for m in modules.values():
        m["revision"] = 2
    return before, modules


def create(m):
    return {"op": "replace_module", "moduleId": m["moduleId"], "expectedModuleRevision": None, "module": m}


def swap(m, expected):
    return {"op": "replace_module", "moduleId": m["moduleId"], "expectedModuleRevision": expected, "module": m}


# ============================================================================ real client over TLS
class RemoteClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.project = f"p{id(self) % 100000}"
        self.owner = await ENV.setup_project(self.project, agents=(("agent-1", ("read", "write")),
                                                                  ("agent-2", ("read", "write")),
                                                                  ("reader-1", ("read",))))

    async def test_typed_write_validation_read_and_stale_retry_over_tls(self):
        before, after = room_pair()
        a1, a2 = ENV.mint("agent-1"), ENV.mint("agent-2")
        actor = ENV.host.actor(TENANT, self.project)
        async with ENV.client(a1, self.project) as c1, ENV.client(a2, self.project) as c2:
            names = {t.name for t in (await c1.list_tools()).tools}
            self.assertEqual(names, set(TOOLS))
            first = (await c1.call_tool("read_project", {})).structured_content
            self.assertEqual((first["projectRevision"], first["guideSha256"], first["guideVersion"]),
                             (0, GUIDE_SHA256, GUIDE_VERSION))
            fence = (await c1.call_tool("acquire_writer", {})).structured_content["fence"]
            # agent-2 cannot write while agent-1 holds the lease
            held = await c2.call_tool("acquire_writer", {})
            self.assertTrue(held.is_error)
            self.assertEqual(held.structured_content["error"]["code"], "LEASE_HELD")
            self.assertTrue(held.structured_content["error"]["retryable"])

            create_txn = txn(0, [create(m) for m in before.values()], "k-create")
            done = await c1.call_tool("apply_operation", {"transaction": create_txn, "fence": fence})
            self.assertFalse(done.is_error, done.structured_content)
            self.assertEqual(done.structured_content["projectRevision"], 1)
            self.assertEqual(done.structured_content["projectId"], self.project)

            digest = actor.state_digest()
            stale = await c1.call_tool("apply_operation", {"transaction": txn(0, [swap(m, 1) for m in after.values()], "k-stale"),
                                                           "fence": fence})
            self.assertTrue(stale.is_error)
            err = stale.structured_content["error"]
            self.assertEqual((err["code"], err["retryable"]), ("REVISION_CONFLICT", True))
            self.assertIn("read_project", err["nextAction"])
            self.assertEqual(actor.state_digest(), digest)          # a rejected write changes nothing

            one_sided = await c1.call_tool("apply_operation", {"transaction": txn(1, [swap(after["living"], 1)], "k-half"),
                                                               "fence": fence})
            self.assertEqual(one_sided.structured_content["error"]["code"], "INVALID_OPERATION")
            self.assertEqual(actor.state_digest(), digest)

            joined = await c1.call_tool("apply_operation", {"transaction": txn(1, [swap(m, 1) for m in after.values()], "k-join"),
                                                            "fence": fence})
            self.assertEqual(joined.structured_content["projectRevision"], 2)
            replay = await c1.call_tool("apply_operation", {"transaction": txn(1, [swap(m, 1) for m in after.values()], "k-join"),
                                                            "fence": fence})
            self.assertTrue(replay.structured_content["replayed"])
            valid = (await c1.call_tool("validate_draft", {})).structured_content
            self.assertTrue(valid["valid"] and valid["compiled"], valid)
            read = (await c2.call_tool("read_project", {})).structured_content
            self.assertEqual(read["projectRevision"], 2)
            self.assertEqual({m["moduleId"] for m in read["modules"]}, {m["moduleId"] for m in after.values()})
            status = (await c2.call_tool("operation_status", {})).structured_content
            self.assertEqual(status["writer"], "another")
            self.assertEqual((await c1.call_tool("operation_status", {})).structured_content["writer"], "you")
            self.assertTrue((await c1.call_tool("release_writer", {"fence": fence})).structured_content["released"])

    async def test_negotiated_protocol_versions(self):
        token = ENV.mint("agent-1")
        async with ENV.client(token, self.project) as client:
            self.assertEqual(client.protocol_version, "2026-07-28")
        async with ENV.client(token, self.project, mode="legacy") as client:
            self.assertEqual(client.protocol_version, "2025-11-25")
            self.assertFalse((await client.call_tool("read_project", {})).is_error)

    async def test_unsupported_protocol_version_is_an_explicit_error(self):
        token = ENV.mint("agent-1")
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        async with ENV.http(token) as http:
            r = await http.post(f"{ENV.audience}?project={self.project}", json=body, headers={
                "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "1999-01-01"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("rotocol", r.text)

    async def test_read_only_grant_cannot_write_and_project_echo_is_exact(self):
        async with ENV.client(ENV.mint("reader-1"), self.project) as client:
            read = (await client.call_tool("read_project", {})).structured_content
            self.assertEqual(read["projectId"], self.project)
            wrong = await client.call_tool("read_project", {"projectId": "someone-else"})
            self.assertEqual(wrong.structured_content["error"]["code"], "INVALID_REQUEST")
            acquire = await client.call_tool("acquire_writer", {})
            self.assertTrue(acquire.is_error)
            self.assertEqual(acquire.structured_content["error"]["code"], "GRANT_DENIED")

    async def test_compact_read_project_stays_small_and_inspect_has_detail(self):
        doc = house.build_house()
        a1 = ENV.mint("agent-1")
        async with ENV.client(a1, self.project) as c:
            fence = (await c.call_tool("acquire_writer", {})).structured_content["fence"]
            done = await c.call_tool("apply_operation", {"transaction": txn(0, [create(m) for m in doc["modules"]], "k-house"),
                                                         "fence": fence})
            self.assertFalse(done.is_error, done.structured_content)
            read = await c.call_tool("read_project", {})
            self.assertLessEqual(len(read.content[0].text.encode("utf-8")), 4096)
            self.assertEqual(len(read.structured_content["modules"]), 5)
            detail = (await c.call_tool("inspect_module", {"moduleId": house.ROOM_IDS["living"]})).structured_content
            self.assertGreater(detail["faceCount"], 20)
            self.assertTrue(all("faceId" in f for f in detail["faces"]))
            missing = await c.call_tool("inspect_module", {"moduleId": "house/level/nope"})
            self.assertEqual(missing.structured_content["error"]["code"], "NOT_FOUND")


# ============================================================================ auth: 401 / 403
class AuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.project = f"a{id(self) % 100000}"
        self.owner = await ENV.setup_project(self.project)
        self.url = f"{ENV.audience}?project={self.project}"
        self.body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}}}
        self.headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28",
                        "Mcp-Method": "tools/list"}

    async def post(self, token=None, **kw):
        async with ENV.http(token) as http:
            return await http.post(kw.pop("url", self.url), json=self.body, headers={**self.headers, **kw.pop("headers", {})})

    async def test_missing_expired_wrong_audience_issuer_signature_and_alg_are_401(self):
        pub = ENV.key.public_key()
        from cryptography.hazmat.primitives import serialization
        pem = pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        cases = {
            "no token": None,
            "expired": ENV.mint("agent-1", expires_in=-3600),
            "wrong audience": ENV.mint("agent-1", aud="https://elsewhere.example/mcp"),
            "wrong issuer": ENV.mint("agent-1", iss="https://evil.example/"),
            "wrong signature": ENV.mint("agent-1", key=ENV.other_key),
            "no tenant claim": ENV.mint("agent-1", tenant=None),
            "alg none": jwt.encode({"iss": ISSUER, "aud": ENV.audience, "sub": "agent-1", "tenant": TENANT,
                                    "exp": 4102444800}, None, algorithm="none"),
            "hs256 with public key material": jwt.encode(
                {"iss": ISSUER, "aud": ENV.audience, "sub": "agent-1", "tenant": TENANT, "exp": 4102444800},
                b"".join(pem.splitlines()[1:-1]), algorithm="HS256"),
            "garbage": "not.a.jwt",
        }
        for label, token in cases.items():
            r = await self.post(token)
            self.assertEqual(r.status_code, 401, label)
            self.assertIn("resource_metadata", r.headers.get("www-authenticate", ""), label)

    async def test_session_id_is_not_authentication(self):
        r = await self.post(None, headers={"Mcp-Session-Id": "any-session-id"})
        self.assertEqual(r.status_code, 401)
        good = await self.post(ENV.mint("agent-1"), headers={"Mcp-Session-Id": "forged"})
        self.assertEqual(good.status_code, 200, good.text)       # a real token works; the session id is ignored
        self.assertNotIn("mcp-session-id", {k.lower() for k in good.headers})
        stranger = await self.post(ENV.mint("stranger-1"), headers={"Mcp-Session-Id": "forged"})
        self.assertEqual(stranger.status_code, 403)

    async def test_missing_project_capability_is_403_and_other_tenants_get_404(self):
        stranger = await self.post(ENV.mint("stranger-1"))
        self.assertEqual(stranger.status_code, 403)
        self.assertEqual(stranger.json()["error"]["code"], "FORBIDDEN")
        self.assertEqual(stranger.json()["projectId"], self.project)
        other_tenant = await self.post(ENV.mint("agent-1", tenant="globex"))
        unknown = await self.post(ENV.mint("agent-1"), url=f"{ENV.audience}?project=does-not-exist")
        self.assertEqual((other_tenant.status_code, unknown.status_code), (404, 404))
        self.assertEqual(other_tenant.json()["error"]["code"], unknown.json()["error"]["code"])
        self.assertEqual((await self.post(ENV.mint("agent-1"), url=ENV.audience)).status_code, 400)

    async def test_protected_resource_metadata_and_no_authorization_server_here(self):
        async with ENV.http() as http:
            meta = await http.get(f"{ENV.base}/.well-known/oauth-protected-resource/mcp")
            self.assertEqual(meta.status_code, 200)
            self.assertEqual(meta.json()["resource"], ENV.audience)
            self.assertTrue(meta.json()["authorization_servers"][0].startswith("https://idp.sibambo.test"))
            for path in ("/authorize", "/token", "/register", "/.well-known/oauth-authorization-server"):
                self.assertEqual((await http.get(f"{ENV.base}{path}")).status_code, 404, path)

    async def test_bearer_token_is_never_echoed_back(self):
        token = ENV.mint("agent-1")
        for r in (await self.post(token), await self.post(token, url=f"{ENV.audience}?project=nope")):
            self.assertNotIn(token, r.text)
            self.assertNotIn(token, json.dumps(dict(r.headers)))


# ============================================================================ S3 transport conformance
class TransportConformanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.project = f"t{id(self) % 100000}"
        await ENV.setup_project(self.project)
        self.token = ENV.mint("agent-1")
        self.url = f"{ENV.audience}?project={self.project}"
        self.call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "read_project", "arguments": {}, "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {}}}}
        self.good = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28",
                     "Mcp-Method": "tools/call", "Mcp-Name": "read_project"}

    async def post(self, headers=None, body=None):
        async with ENV.http(self.token) as http:
            return await http.post(self.url, json=body or self.call, headers={**self.good, **(headers or {})})

    async def test_valid_request_baseline_has_no_session_and_disables_proxy_buffering(self):
        r = await self.post()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers.get("x-accel-buffering"), "no")
        self.assertNotIn("mcp-session-id", {k.lower() for k in r.headers})

    async def test_invalid_origin_is_403_and_allowed_origin_passes(self):
        self.assertEqual((await self.post({"Origin": "https://evil.example"})).status_code, 403)
        self.assertEqual((await self.post({"Origin": "https://editor.sibambo.test"})).status_code, 200)

    async def test_header_body_disagreement_is_400_header_mismatch_minus_32020(self):
        for header in ({"Mcp-Method": "tools/list"}, {"Mcp-Name": "inspect_module"}):
            r = await self.post(header)
            self.assertEqual(r.status_code, 400, header)
            self.assertEqual(r.json()["error"]["code"], -32020, header)
        body = copy.deepcopy(self.call)
        body["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "2025-11-25"
        r = await self.post(body=body)
        self.assertEqual(r.status_code, 400)

    async def test_get_and_delete_are_405_and_no_resumption(self):
        async with ENV.http(self.token) as http:
            for method in ("GET", "DELETE", "PUT", "PATCH"):
                r = await http.request(method, self.url, headers={"Last-Event-ID": "5", "Mcp-Session-Id": "x"})
                self.assertEqual(r.status_code, 405, method)
                self.assertEqual(r.headers.get("allow"), "POST" if method != "DELETE" else r.headers.get("allow"))
        r = await self.post({"Last-Event-ID": "7"})
        self.assertEqual(r.status_code, 200)                       # the header is simply ignored on POST

    async def test_oversized_body_is_rejected(self):
        body = copy.deepcopy(self.call)
        body["params"]["arguments"] = {"junk": "x" * (300 * 1024)}
        r = await self.post(body=body)
        self.assertIn(r.status_code, (400, 413))


# ============================================================================ errors, state unchanged
class Rig:
    """In-process Tools over a real actor with a fake clock (no HTTP)."""

    def __init__(self, **defaults):
        self.t = [0.0]
        self.host = ProjectHost(clock=lambda: self.t[0], **defaults)
        self.tools, self.owner_api = Tools(self.host), OwnerApi(self.host)
        mk = lambda sub: Principal(f"p-{sub}", TENANT, ISSUER, sub, "t")
        self.owner, self.agent, self.agent2, self.reader, self.stranger = (
            mk("owner"), mk("agent"), mk("agent2"), mk("reader"), mk("stranger"))
        self.owner_api.open(self.owner, "home")
        for p, scopes in ((self.agent, {"read", "write"}), (self.agent2, {"read", "write"}), (self.reader, {"read"})):
            self.owner_api.grant(self.owner, "home", p.id, "t", sorted(scopes))
        self.owner_api.heartbeat(self.owner, "home")
        self.actor = self.host.actor(TENANT, "home")

    def call(self, who, name, **args):
        return self.tools.call(who, "home", name, args)

    def digest(self):
        return (self.actor.state_digest(), self.call(self.owner, "read_project")["projectRevision"])

    def fail(self, test, code, who, name, **args):
        before = self.digest()
        with test.assertRaises(ToolFailure) as caught:
            self.call(who, name, **args)
        test.assertEqual(caught.exception.code, code, caught.exception.body)
        test.assertEqual(self.digest(), before, f"{code}: state changed")
        return caught.exception.body


class ErrorCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(max_pending=4)

    def fence(self, who=None):
        return self.rig.call(who or self.rig.agent, "acquire_writer")["fence"]

    def test_every_catalogue_entry_has_retryable_nextaction_and_validates_against_the_schema(self):
        schema = Draft202012Validator(json.loads((ROOT / "schemas/draft-errors-v1.schema.json").read_text()))
        self.assertEqual(set(errors.NEW_IN_SE03), {"UNAUTHENTICATED", "FORBIDDEN", "BUSY", "RENDER_ACK_TIMEOUT",
                                                   "NO_ACTIVE_VIEWER", "PAUSED_BY_OWNER"})
        for code, (retryable, action, status) in errors.CATALOG.items():
            body = errors.error_body(code, "message")
            schema.validate({"error": body})
            self.assertIsInstance(body["retryable"], bool)
            self.assertTrue(action and 100 <= status < 600)
        self.assertEqual({k for k in errors.CATALOG} - set(errors.SERVICE_NAME), {k for k in errors.CATALOG if k not in errors.SERVICE_NAME})
        for actor_code, service_code in errors.SERVICE_NAME.items():
            self.assertIn(service_code, errors.CATALOG)
            self.assertEqual(errors.error_body(actor_code, "x")["code"], service_code)
        self.assertTrue(schema.is_valid({"error": errors.error_body("BUSY", "x")}))
        self.assertFalse(schema.is_valid({"error": {"code": "NOT_A_CODE", "message": "x", "retryable": True, "nextAction": "y"}}))
        doc = (ROOT / "docs/two-phase/ERROR-CATALOG.md").read_text()
        for code in errors.CATALOG:
            self.assertIn(f"`{code}`", doc, f"{code} missing from ERROR-CATALOG.md")

    def test_codes_reachable_through_the_service_leave_state_unchanged(self):
        r, t = self.rig, self
        before, after = room_pair()
        fence = self.fence()
        ok = r.call(r.agent, "apply_operation", fence=fence, transaction=txn(0, [create(m) for m in before.values()], "c1"))
        self.assertEqual(ok["projectRevision"], 1)

        body = r.fail(t, "REVISION_CONFLICT", r.agent, "apply_operation", fence=fence,
                      transaction=txn(0, [swap(m, 1) for m in after.values()], "c2"))
        self.assertTrue(body["retryable"] and "read_project" in body["nextAction"])
        r.fail(t, "IDEMPOTENCY_CONFLICT", r.agent, "apply_operation", fence=fence,
               transaction=txn(1, [swap(after["living"], 1), swap(after["bedroom-a"], 1)], "c1"))
        r.fail(t, "FENCE_STALE", r.agent, "apply_operation", fence=fence + 9,
               transaction=txn(1, [swap(m, 1) for m in after.values()], "c3"))
        body = r.fail(t, "LEASE_HELD", r.agent2, "acquire_writer")
        self.assertEqual(body["retryAfterMs"], errors.RETRY_AFTER_MS["LEASE_HELD"])
        r.fail(t, "INVALID_OPERATION", r.agent, "apply_operation", fence=fence,
               transaction=txn(1, [swap(after["living"], 1)], "c4"))
        r.fail(t, "INVALID_REQUEST", r.agent, "apply_operation", fence=fence, transaction={"schemaVersion": "nope"})
        r.fail(t, "INVALID_REQUEST", r.agent, "apply_operation", fence="3", transaction={})
        r.fail(t, "INVALID_REQUEST", r.agent, "read_project", projectId="other")
        r.fail(t, "INVALID_REQUEST", r.agent, "no_such_tool")
        r.fail(t, "GRANT_DENIED", r.reader, "apply_operation", fence=fence, transaction=txn(1, [], "x"))
        r.fail(t, "GRANT_DENIED", r.stranger, "read_project")
        r.fail(t, "GRANT_DENIED", r.reader, "acquire_writer")
        needy = copy.deepcopy(before["living"])
        needy["moduleId"], needy["dependencies"] = "house/level/needy", [{"moduleId": before["living"]["moduleId"], "minRevision": 9}]
        needy["ports"], needy["ownedSeams"] = [], []
        r.fail(t, "DEPENDENCY_STALE", r.agent, "apply_operation", fence=fence, transaction=txn(1, [create(needy)], "c5"))
        gone = {"op": "remove_module", "moduleId": "house/level/needy2", "expectedModuleRevision": 1}
        r.fail(t, "INVALID_OPERATION", r.agent, "apply_operation", fence=fence, transaction=txn(1, [gone], "c6"))

        body = r.fail(t, "NOT_FOUND", r.agent, "inspect_module", moduleId="house/level/nope")
        self.assertFalse(body["retryable"])
        with t.assertRaises(ToolFailure) as caught:
            r.tools.call(r.agent, "no-such-project", "read_project", {})
        t.assertEqual(caught.exception.code, "NOT_FOUND")

        joined = r.call(r.agent, "apply_operation", fence=fence, transaction=txn(1, [swap(m, 1) for m in after.values()], "c7"))
        t.assertEqual(joined["projectRevision"], 2)
        # a removal, then reusing the id is TOMBSTONED
        living = after["living"]["moduleId"]
        rm = txn(2, [{"op": "remove_module", "moduleId": "house/level/ghost", "expectedModuleRevision": 1}], "c8")
        r.fail(t, "INVALID_OPERATION", r.agent, "apply_operation", fence=fence, transaction=rm)
        solo = copy.deepcopy(house._room("bath", False))
        solo["moduleId"] = "house/level/solo"
        r.call(r.agent, "apply_operation", fence=fence, transaction=txn(2, [create(solo)], "c9"))
        r.call(r.agent, "apply_operation", fence=fence, transaction=txn(3, [
            {"op": "remove_module", "moduleId": "house/level/solo", "expectedModuleRevision": 1}], "c10"))
        r.fail(t, "TOMBSTONED", r.agent, "apply_operation", fence=fence, transaction=txn(4, [create(solo)], "c11"))
        self.assertIn(living, [m["moduleId"] for m in r.call(r.owner, "read_project")["modules"]])

    def test_pause_busy_viewer_render_and_lease_expiry_codes(self):
        r, t = self.rig, self
        fence = self.fence()
        before, _ = room_pair()
        txn1 = txn(0, [create(m) for m in before.values()], "d1")
        # BUSY: another write for this project is in flight at the service gate
        gate = r.host.gate(TENANT, "home")
        gate.acquire()
        try:
            body = r.fail(t, "BUSY", r.agent, "apply_operation", fence=fence, transaction=txn1)
            self.assertEqual(body["retryAfterMs"], errors.RETRY_AFTER_MS["BUSY"])
        finally:
            gate.release()
        # RENDER_ACK_TIMEOUT / NO_ACTIVE_VIEWER come from the viewer check (SE-05 supplies the real one)
        r.host.viewer = ViewerCheck(lambda actor, st: "timeout")
        r.fail(t, "RENDER_ACK_TIMEOUT", r.agent, "apply_operation", fence=fence, transaction=txn1)
        r.host.viewer = ViewerCheck(lambda actor, st: "none")
        r.fail(t, "NO_ACTIVE_VIEWER", r.agent, "apply_operation", fence=fence, transaction=txn1)
        r.host.viewer = ViewerCheck()
        # owner pause -> PAUSED_BY_OWNER (the actor's own PAUSED is translated, nextAction present)
        r.owner_api.pause(r.owner, "home")
        body = r.fail(t, "PAUSED_BY_OWNER", r.agent, "apply_operation", fence=fence, transaction=txn1)
        self.assertTrue(body["nextAction"])
        r.fail(t, "PAUSED_BY_OWNER", r.agent, "acquire_writer")
        r.owner_api.resume(r.owner, "home")
        fence = self.fence()
        # the owner's heartbeat lapses -> no active viewer (writes are rejected)
        r.t[0] += 31
        r.fail(t, "NO_ACTIVE_VIEWER", r.agent, "apply_operation", fence=fence, transaction=txn1)
        r.owner_api.heartbeat(r.owner, "home")
        r.t[0] += 31                                              # lease ttl is 60s; heartbeat keeps the viewer alive
        r.owner_api.heartbeat(r.owner, "home")
        r.fail(t, "LEASE_EXPIRED", r.agent, "apply_operation", fence=fence, transaction=txn1)

    def test_actor_level_codes_map_and_hold_state(self):
        r = self.rig
        old = r.actor
        before = r.digest()
        r.owner_api.open(r.owner, "home", new_epoch=True)       # a new epoch retires the old actor
        failure = None
        try:
            old.view(r.owner.id)
        except Exception as exc:
            failure = _from_actor(exc)
        self.assertEqual(failure.code, "EPOCH_CLOSED")
        self.assertFalse(failure.body["retryable"])
        self.assertEqual(errors.error_body("QUEUE_FULL", "x")["code"], "BUSY")
        self.assertEqual(errors.error_body("OWNER_ABSENT", "x")["code"], "NO_ACTIVE_VIEWER")
        self.assertEqual(errors.error_body("PAUSED", "x")["code"], "PAUSED_BY_OWNER")
        self.assertEqual(before[1], 0)

    def test_budget_and_internal_error_hold_state(self):
        with mock.patch.object(identity_store, "MAX_KEYS_PER_MODULE", 2):
            r = Rig()
            fence = r.call(r.agent, "acquire_writer")["fence"]
            solo = house._room("living", False)
            solo["moduleId"] = "house/level/solo"
            solo["ports"], solo["ownedSeams"] = [], []
            r.call(r.agent, "apply_operation", fence=fence, transaction=txn(0, [create(solo)], "e1"))
            rev = 1
            current = solo
            for n in range(1, 4):
                nxt = copy.deepcopy(current)
                nxt["revision"] = rev + 1
                nxt["provenance"] = dict(nxt["provenance"], note=f"edit {n}")
                try:
                    r.call(r.agent, "apply_operation", fence=fence, transaction=txn(rev, [swap(nxt, rev)], f"e{n + 1}"))
                except ToolFailure as failure:
                    self.assertEqual(failure.code, "BUDGET_EXCEEDED")
                    self.assertFalse(failure.body["retryable"])
                    break
                rev, current = rev + 1, nxt
            else:
                self.fail("the key budget was never hit")
        def boom(point):
            if point == "after-validate":
                raise RuntimeError("injected")
        r = Rig(_fault_hook=boom)
        fence = r.call(r.agent, "acquire_writer")["fence"]
        before, _ = room_pair()
        body = r.fail(self, "INTERNAL_ERROR", r.agent, "apply_operation", fence=fence,
                      transaction=txn(0, [create(m) for m in before.values()], "f1"))
        self.assertTrue(body["retryable"])

    def test_owner_api_codes(self):
        r = self.rig
        with self.assertRaises(ToolFailure) as caught:
            r.owner_api.pause(r.agent, "home")
        self.assertEqual(caught.exception.code, "FORBIDDEN")
        with self.assertRaises(ToolFailure) as caught:
            r.owner_api.pause(r.owner, "no-such")
        self.assertEqual(caught.exception.code, "NOT_FOUND")


# ============================================================================ owner REST + tickets
class OwnerApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_response_echoes_the_exact_requested_project_id_and_unauthenticated_is_typed(self):
        project = "echo.project-1"
        owner = ENV.mint("owner-9")
        async with ENV.http(owner) as http:
            for action in ("open", "heartbeat", "pause", "resume", "ticket"):
                r = await http.post(f"{ENV.base}/owner/v1/projects/{project}/{action}", json={})
                self.assertEqual(r.status_code, 200, (action, r.text))
                self.assertEqual(r.json()["projectId"], project, action)
            r = await http.get(f"{ENV.base}/owner/v1/projects/{project}")
            self.assertEqual(r.json()["projectId"], project)
            r = await http.post(f"{ENV.base}/owner/v1/projects/not-mine-zzz/pause", json={})
            self.assertEqual((r.status_code, r.json()["projectId"], r.json()["error"]["code"]), (404, "not-mine-zzz", "NOT_FOUND"))
        async with ENV.http() as http:
            r = await http.post(f"{ENV.base}/owner/v1/projects/{project}/pause", json={})
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (401, "UNAUTHENTICATED"))
        async with ENV.http(ENV.mint("agent-1")) as http:
            r = await http.post(f"{ENV.base}/owner/v1/projects/{project}/pause", json={})
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (403, "FORBIDDEN"))
            r = await http.post(f"{ENV.base}/owner/v1/projects/{project}/grants", content=b"{" * 10)
            self.assertIn(r.status_code, (400, 403))

    async def test_reopen_never_discards_the_draft_without_an_explicit_new_epoch(self):
        project = "reopen.1"
        owner = await ENV.setup_project(project)
        actor = ENV.host.actor(TENANT, project)
        again = await ENV.owner_post(owner, project, "open")
        self.assertEqual((again.status_code, again.json()["epoch"], again.json()["created"]), (200, 1, False))
        self.assertIs(ENV.host.actor(TENANT, project), actor)
        other_owner = await ENV.owner_post(ENV.mint("owner-2"), project, "open")
        self.assertEqual((other_owner.status_code, other_owner.json()["error"]["code"]), (403, "FORBIDDEN"))
        # review P1: another principal of the SAME tenant can neither re-open nor take over via newEpoch
        digest = actor.state_digest()
        for body in ({}, {"newEpoch": True}, {"newEpoch": True, "extra": 1}):
            taken = await ENV.owner_post(ENV.mint("mallory"), project, "open", body)
            self.assertEqual((taken.status_code, taken.json()["error"]["code"]), (403, "FORBIDDEN"), body)
        self.assertIs(ENV.host.actor(TENANT, project), actor)
        self.assertEqual((actor.owner, actor.epoch, actor.state_digest()), (ENV.pid("owner-1"), 1, digest))
        self.assertEqual((await ENV.owner_post(owner, project, "heartbeat")).status_code, 200)   # still the owner
        status = await ENV.owner_post(owner, project, "pause")
        self.assertEqual(status.status_code, 200)
        await ENV.owner_post(owner, project, "resume")
        fresh = await ENV.owner_post(owner, project, "open", {"newEpoch": True})
        self.assertEqual((fresh.json()["epoch"], fresh.json()["created"]), (2, True))
        self.assertIsNot(ENV.host.actor(TENANT, project), actor)

    async def test_owner_pause_and_revoke_fence_the_agent_over_the_wire(self):
        project = "pause.revoke-1"
        owner = await ENV.setup_project(project)
        agent = ENV.mint("agent-1")
        async with ENV.client(agent, project) as client:
            fence = (await client.call_tool("acquire_writer", {})).structured_content["fence"]
            self.assertEqual((await ENV.owner_post(owner, project, "pause")).status_code, 200)
            paused = await client.call_tool("apply_operation", {"transaction": txn(0, [], "z1"), "fence": fence})
            self.assertEqual(paused.structured_content["error"]["code"], "PAUSED_BY_OWNER")
            self.assertEqual((await ENV.owner_post(owner, project, "resume")).status_code, 200)
        r = await ENV.owner_post(owner, project, "revoke", {"sub": "agent-1"})
        self.assertEqual((r.status_code, r.json()["revoked"], r.json()["projectId"]), (200, True, project))
        async with ENV.http(agent) as http:                              # revoked: no capability any more
            gone = await http.post(f"{ENV.audience}?project={project}", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                   headers={"Accept": "application/json, text/event-stream",
                                            "MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list"})
            self.assertEqual(gone.status_code, 403)
        r = await ENV.owner_post(owner, project, "grants", {"sub": "agent-1", "client": "x", "scopes": ["read", "admin"]})
        self.assertEqual(r.status_code, 400)

    async def test_requests_inbox_is_read_only_for_agents_and_tenant_scoped(self):
        project = "inbox.1"
        owner = await ENV.setup_project(project)
        r = await ENV.owner_post(owner, project, "requests", {"text": "Please add a window to bedroom A"})
        self.assertEqual(r.json()["requestId"], 1)
        async with ENV.client(ENV.mint("agent-1"), project) as client:
            got = (await client.call_tool("read_owner_requests", {"sinceId": 0})).structured_content
            self.assertTrue(got["untrusted"])
            self.assertEqual([x["text"] for x in got["requests"]], ["Please add a window to bedroom A"])
            self.assertEqual((await client.call_tool("read_owner_requests", {"sinceId": 1})).structured_content["requests"], [])
            bad = await client.call_tool("read_owner_requests", {"sinceId": -1})
            self.assertEqual(bad.structured_content["error"]["code"], "INVALID_REQUEST")
        async with ENV.http(ENV.mint("agent-1", tenant="globex")) as http:
            r = await http.post(f"{ENV.audience}?project={project}", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                headers={"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28",
                                         "Mcp-Method": "tools/list"})
            self.assertEqual(r.status_code, 404)
        self.assertEqual(ENV.host.requests.read("globex", project), [])


class OpenProjectOwnershipTests(unittest.TestCase):
    """Review P1: check-and-open is atomic and ownership is enforced for every kind of open."""

    def principals(self):
        mk = lambda sub, tenant=TENANT: Principal(f"p-{sub}", tenant, ISSUER, sub, "t")
        return mk("alice"), mk("mallory"), mk("carol", "globex")

    def test_other_principal_cannot_take_over_with_new_epoch_and_nothing_changes(self):
        host = ProjectHost()
        api = OwnerApi(host)
        alice, mallory, _ = self.principals()
        self.assertEqual(api.open(alice, "proj-a"), {"projectId": "proj-a", "epoch": 1, "created": True})
        actor = host.actor(TENANT, "proj-a")
        before = (actor.owner, actor.epoch, actor.state_digest())
        for flag in (False, True):
            with self.assertRaises(ToolFailure) as caught:
                api.open(mallory, "proj-a", new_epoch=flag)
            self.assertEqual(caught.exception.code, "FORBIDDEN")
        self.assertIs(host.actor(TENANT, "proj-a"), actor)
        self.assertEqual((actor.owner, actor.epoch, actor.state_digest()), before)
        self.assertEqual(api.status(alice, "proj-a")["epoch"], 1)               # alice is not locked out
        self.assertEqual(api.open(alice, "proj-a"), {"projectId": "proj-a", "epoch": 1, "created": False})
        self.assertEqual(api.open(alice, "proj-a", new_epoch=True)["epoch"], 2)  # the owner still can
        self.assertTrue(actor._closed)

    def test_other_tenant_with_the_same_project_name_is_a_different_project(self):
        host = ProjectHost()
        api = OwnerApi(host)
        alice, _, carol = self.principals()
        api.open(alice, "shared-name")
        self.assertEqual(api.open(carol, "shared-name")["created"], True)
        self.assertNotEqual(host.actor(TENANT, "shared-name").owner, host.actor("globex", "shared-name").owner)

    def test_concurrent_first_open_has_exactly_one_owner_and_the_winner_is_not_closed(self):
        for attempt in range(25):
            host = ProjectHost()
            api = OwnerApi(host)
            alice, mallory, _ = self.principals()
            barrier, results = threading.Barrier(2), {}

            def go(who, new_epoch):
                barrier.wait()
                try:
                    results[who.id] = api.open(who, "race", new_epoch=new_epoch)
                except ToolFailure as failure:
                    results[who.id] = failure.code
            threads = [threading.Thread(target=go, args=(alice, attempt % 2 == 0)),
                       threading.Thread(target=go, args=(mallory, attempt % 2 == 1))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            winners = [k for k, v in results.items() if isinstance(v, dict)]
            losers = [k for k, v in results.items() if v == "FORBIDDEN"]
            self.assertEqual((len(winners), len(losers)), (1, 1), results)
            actor = host.actor(TENANT, "race")
            self.assertEqual(actor.owner, winners[0])
            self.assertFalse(actor._closed)
            self.assertEqual(actor.epoch, 1)


class TicketTests(unittest.TestCase):
    def test_ticket_shape_expiry_single_use_and_binding(self):
        from datetime import datetime, timedelta, timezone
        now = [datetime(2026, 11, 11, 12, 0, 0, tzinfo=timezone.utc)]
        store = TicketStore(ttl_seconds=120, now=lambda: now[0])
        issued = store.issue("acme", "home", "p-owner")
        self.assertTrue(32 <= len(issued["ticket"]) <= 512)
        self.assertEqual(issued["expiresAt"], "2026-11-11T12:02:00Z")
        self.assertLessEqual(issued["ttlSeconds"], 300)
        self.assertEqual(store.consume(issued["ticket"], "acme", "home"), "p-owner")
        self.assertIsNone(store.consume(issued["ticket"], "acme", "home"))        # single use
        for tenant, project in (("globex", "home"), ("acme", "other")):             # bound to tenant+project, burned on sight
            t = store.issue("acme", "home", "p-owner")
            self.assertIsNone(store.consume(t["ticket"], tenant, project))
            self.assertIsNone(store.consume(t["ticket"], "acme", "home"))
        late = store.issue("acme", "home", "p-owner")
        now[0] += timedelta(seconds=121)
        self.assertIsNone(store.consume(late["ticket"], "acme", "home"))
        for bad in (None, "", "x" * 31, "x" * 513, 12345, "A" * 64):
            self.assertIsNone(store.consume(bad, "acme", "home"))
        with self.assertRaises(ValueError):
            TicketStore(ttl_seconds=301)
        with self.assertRaises(ValueError):
            TicketStore(ttl_seconds=0)
        self.assertNotIn(issued["ticket"], repr(store.__dict__))                   # only a digest is stored

    def test_outstanding_tickets_are_bounded(self):
        store = TicketStore(max_outstanding=2)
        store.issue("a", "p", "o")
        store.issue("a", "p", "o")
        with self.assertRaises(OverflowError):
            store.issue("a", "p", "o")


class RequestStoreTests(unittest.TestCase):
    def test_bounds_ttl_and_isolation(self):
        t = [0.0]
        store = RequestStore(clock=lambda: t[0])
        for n in range(55):
            store.post("acme", "home", f"req {n}")
        items = store.read("acme", "home")
        self.assertEqual((len(items), items[0]["text"], items[-1]["id"]), (50, "req 5", 55))
        self.assertEqual([x["id"] for x in store.read("acme", "home", 52)], [53, 54, 55])
        self.assertEqual(store.read("globex", "home"), [])
        self.assertEqual(store.read("acme", "other"), [])
        store.post("acme", "home", "é" * 2048)                       # exactly 4096 bytes
        with self.assertRaises(RequestError):
            store.post("acme", "home", "é" * 2049)
        for bad in ("", "   ", "a\x00b", "a\x1bb", 5):
            with self.assertRaises(RequestError):
                store.post("acme", "home", bad)
        t[0] += 1800
        self.assertEqual(store.read("acme", "home"), [])
        with self.assertRaises(RequestError):
            store.read("acme", "home", -1)
        with self.assertRaises(RequestError):
            store.read("", "home")

    def test_no_logging_or_disk_in_the_inbox(self):
        text = (ROOT / "core/project/requests.py").read_text()
        for banned in ("logging", "print(", "open(", "pathlib", "sqlite", "pickle", "write_text"):
            self.assertNotIn(banned, text)


# ============================================================================ S2 authenticated local bridge
class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rig = Rig()
        self.fence = self.rig.call(self.rig.agent, "acquire_writer")["fence"]
        self.bridge = BridgeServer(self.rig.tools, self.rig.agent, "home").start()
        self.addCleanup(self.bridge.stop)

    def test_binds_loopback_only_with_a_random_per_launch_secret(self):
        self.assertEqual(self.bridge.address[0], "127.0.0.1")
        other = BridgeServer(self.rig.tools, self.rig.agent, "home")
        self.addCleanup(other.stop)
        self.assertEqual(len(self.bridge.secret), 64)
        self.assertNotEqual(self.bridge.secret, other.secret)

    def test_second_local_process_without_the_secret_is_refused(self):
        env = self.bridge.env()
        good = bridge_call("operation_status", {}, env=env)
        self.assertTrue(good["ok"], good)
        self.assertEqual(good["result"]["projectId"], "home")
        for tamper in ({"SIBAMBO_BRIDGE_SECRET": "0" * 64}, {"SIBAMBO_BRIDGE_SECRET": ""},
                       {"SIBAMBO_BRIDGE_SECRET": self.bridge.secret[:-1] + "x"}):
            refused = bridge_call("operation_status", {}, env={**env, **tamper})
            self.assertFalse(refused["ok"])
            self.assertEqual(refused["error"]["code"], "UNAUTHENTICATED")
        missing = bridge_call("operation_status", {}, env={"SIBAMBO_BRIDGE_ADDR": env["SIBAMBO_BRIDGE_ADDR"]})
        self.assertFalse(missing["ok"])
        import socket
        with socket.create_connection(self.bridge.address, timeout=5) as raw:       # raw frame without any secret
            raw.sendall(b'{"id":1,"tool":"read_project","args":{}}\n')
            self.assertEqual(raw.makefile("rb").readline(), b"")
        with socket.create_connection(self.bridge.address, timeout=5) as raw:       # garbage
            raw.sendall(b"\xff\xfe not json\n")
            self.assertEqual(raw.makefile("rb").readline(), b"")
        wrong_host = bridge_call("operation_status", {}, env={**env, "SIBAMBO_BRIDGE_ADDR": "0.0.0.0:1"})
        self.assertFalse(wrong_host["ok"])

    async def test_real_stdio_client_shares_the_one_canonical_actor_with_http(self):
        params = StdioServerParameters(command=sys.executable, args=["-m", "service.stdio_bridge"],
                                       env={"PYTHONPATH": str(ROOT), **self.bridge.env()})
        before, _ = room_pair()
        async with Client(params, mode="auto") as client:
            names = {t.name for t in (await client.list_tools()).tools}
            self.assertEqual(names, set(TOOLS))
            done = await client.call_tool("apply_operation", {
                "transaction": txn(0, [create(m) for m in before.values()], "s1"), "fence": self.fence})
            self.assertFalse(done.is_error, done.structured_content)
            self.assertEqual(done.structured_content["projectId"], "home")
        read = self.rig.call(self.rig.owner, "read_project")          # same actor, no second draft
        self.assertEqual(read["projectRevision"], 1)
        self.assertEqual(len(read["modules"]), 2)

    async def test_stdio_without_secret_cannot_do_anything(self):
        env = {k: v for k, v in self.bridge.env().items() if k != "SIBAMBO_BRIDGE_SECRET"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "service.stdio_bridge"],
                                       env={"PYTHONPATH": str(ROOT), **env})
        async with Client(params, mode="auto") as client:
            result = await client.call_tool("read_project", {})
            self.assertTrue(result.is_error)
            self.assertEqual(result.structured_content["error"]["code"], "UNAUTHENTICATED")
        self.assertEqual(self.rig.call(self.rig.owner, "read_project")["projectRevision"], 0)


# ============================================================================ S11 hash-locked dependencies
class HashLockTests(unittest.TestCase):
    def test_lock_is_fully_hashed_and_pins_the_baseline(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import check_hash_lock
        text = (ROOT / "service/requirements.lock").read_text()
        self.assertEqual(check_hash_lock.check(text), [])
        self.assertIn("mcp==2.3.0", text)
        self.assertIn("--hash=sha256:", text)
        bad = text.replace("mcp==2.3.0", "mcp==2.3.0 ", 1).replace(
            "    --hash=sha256:", "    # no hash\n    --hash-removed:", 1)
        self.assertTrue(check_hash_lock.check(bad))
        self.assertTrue(check_hash_lock.check("mcp==2.3.0\nstarlette>=1\n"))
        self.assertTrue(check_hash_lock.check("-e ./local\n"))
        self.assertTrue(check_hash_lock.check("pkg @ https://example.test/pkg.whl --hash=sha256:" + "0" * 64 + "\n"))

    def test_service_has_no_save_export_or_cli_path_and_no_provider_credentials(self):
        for path in (ROOT / "service").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for banned in ("subprocess", "os.system", "JournalStore", "fsync", "pickle", "eval(", "exec("):
                self.assertNotIn(banned, text, f"{path.name}: {banned}")
        self.assertFalse(any(("save" in name or "export" in name) for name in TOOLS))


if __name__ == "__main__":
    unittest.main()
