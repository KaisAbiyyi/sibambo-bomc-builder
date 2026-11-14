"""v1.6 local demo mode: runner, owner verifier, bridge secret file, requestId association, guide/IR delivery."""
from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from service import local_demo as ld                                   # noqa: E402
from service.bridge import ENV_ADDR, ENV_SECRET_FILE, bridge_call       # noqa: E402
from service.guide.tool_descriptions import GUIDE_SHA256, GUIDE_VERSION, TOOLS  # noqa: E402
from service.mcp_http import INSTRUCTIONS                              # noqa: E402
from service.owner_mcp import OwnerMcp                                 # noqa: E402
from service.tools import ToolFailure, Tools                           # noqa: E402
from examples import bmb026_house as house                             # noqa: E402
from tests.test_remote_mcp import create, swap, txn                    # noqa: E402

SECRET = "s" * 40
ORIGINS = ("http://localhost:5175",)


def demo(project="local-demo", clients=tuple(ld.CLIENTS)):
    return ld.LocalDemo(project=project, port=8765, owner_secret=SECRET, editor_origins=ORIGINS, clients=clients)


class VerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_exact_owner_secret_is_accepted_and_no_jwt_is_ever_verified(self):
        v = ld.LocalVerifier(SECRET, "http://127.0.0.1:8765/mcp")
        self.assertEqual(v.principal_of(SECRET).subject, ld.OWNER_SUB)
        for bad in ("", SECRET[:-1], SECRET + "x", "Bearer " + SECRET, "a.b.c"):
            self.assertIsNone(v.principal_of(bad))
        self.assertIsNone(await v.verify_token(SECRET))
        with self.assertRaises(ValueError):
            ld.LocalVerifier("short", "http://127.0.0.1:8765/mcp")


class RunnerTests(unittest.TestCase):
    def test_exactly_two_named_clients_hold_exactly_read_write(self):
        d = demo()
        self.addCleanup(d.stop)
        actor = d.host.actor(ld.LOCAL_TENANT, "local-demo")
        self.assertEqual(sorted(g.client for g in actor._grants.values()), ["claude-code", "codex"])
        self.assertTrue(all(g.scopes == frozenset({"read", "write"}) for g in actor._grants.values()))
        stranger = ld.principal("someone-else", "claude-code")
        with self.assertRaises(ToolFailure) as caught:
            Tools(d.host).call(stranger, "local-demo", "read_project", {})
        self.assertEqual(caught.exception.code, "GRANT_DENIED")

    def test_unknown_client_is_refused(self):
        with self.assertRaises(ValueError):
            demo(clients=("claude-code", "evil"))

    def test_both_bridges_share_one_actor_and_writers_contend(self):
        d = demo()
        d.start_bridges()
        self.addCleanup(d.stop)
        env = {c: d.bridges[c].env() for c in d.clients}
        a = bridge_call("acquire_writer", {}, env=env["claude-code"])
        self.assertEqual(a["ok"], False)                                   # no viewer yet: E7
        self.assertEqual(a["error"]["code"], "NO_ACTIVE_VIEWER")
        seen = [bridge_call("read_project", {}, env=env[c]) for c in d.clients]
        self.assertTrue(all(r["ok"] for r in seen))
        self.assertEqual({r["result"]["epoch"] for r in seen}, {1})
        self.assertEqual(len(d.host.registry._actors), 1)

    def test_secret_file_works_and_failures_are_uniform_and_leak_nothing(self):
        d = demo()
        d.start_bridges()
        self.addCleanup(d.stop)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            manifest = d.write_client_files(run)
            env = {ENV_ADDR: f"{d.bridges['codex'].address[0]}:{d.bridges['codex'].address[1]}",
                   ENV_SECRET_FILE: (run / "private" / "bridge-codex.secret").as_posix()}
            self.assertTrue(bridge_call("read_project", {}, env=env)["ok"])
            for bad in (run / "missing", run):                               # missing file, directory
                reply = bridge_call("read_project", {}, env={**env, ENV_SECRET_FILE: bad.as_posix()})
                self.assertEqual(reply["error"]["code"], "UNAUTHENTICATED")
                self.assertNotIn(str(bad), json.dumps(reply))
            empty = run / "empty"
            empty.write_text("   ", encoding="utf-8")
            self.assertEqual(bridge_call("read_project", {}, env={**env, ENV_SECRET_FILE: empty.as_posix()})["error"]["code"],
                             "UNAUTHENTICATED")
            big = run / "big"
            big.write_text("x" * 300, encoding="utf-8")
            self.assertEqual(bridge_call("read_project", {}, env={**env, ENV_SECRET_FILE: big.as_posix()})["error"]["code"],
                             "UNAUTHENTICATED")
            # generated configs and manifest carry no secret of any kind
            texts = [(run / "agents" / n).read_text(encoding="utf-8") for n in ("claude.mcp.json", "codex.overrides.json")]
            texts.append(json.dumps(manifest))
            for text in texts:
                self.assertIsNone(re.search(r"[0-9a-f]{64}", text))
                self.assertNotIn(SECRET, text)
            self.assertIn("service.stdio_bridge", texts[0])
            self.assertEqual(manifest["mode"], "local-demo")

    def test_main_refuses_non_loopback_missing_secret_unknown_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            import os
            old = os.environ.get("SIBAMBO_LOCAL_OWNER_TOKEN")
            try:
                os.environ["SIBAMBO_LOCAL_OWNER_TOKEN"] = SECRET
                self.assertEqual(ld.main(["--run-root", tmp, "--bind", "0.0.0.0"]), 2)
                self.assertEqual(ld.main(["--run-root", tmp, "--clients", "evil"]), 2)
                os.environ["SIBAMBO_LOCAL_OWNER_TOKEN"] = "short"
                self.assertEqual(ld.main(["--run-root", tmp]), 2)
            finally:
                if old is None:
                    os.environ.pop("SIBAMBO_LOCAL_OWNER_TOKEN", None)
                else:
                    os.environ["SIBAMBO_LOCAL_OWNER_TOKEN"] = old
            self.assertFalse((Path(tmp) / "manifest.json").exists())


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.d = demo(clients=("codex",))
        self.addCleanup(self.d.stop)
        self.actor = self.d.host.actor(ld.LOCAL_TENANT, "local-demo")
        self.tools = Tools(self.d.host)
        self.agent = self.d.agents["codex"]
        self.hub = self.d.host.drafts
        self.channel = self.hub.channel(self.actor)
        ticket = self.hub.issue_ticket(self.actor)["ticket"]
        self.peer = self.hub.attach(dict(ticket=ticket, projectId="local-demo", epoch=None,
                                         lastAppliedRevision=0, lastRenderedRevision=0))
        self.ack()

    def ack(self):
        snap = self.channel.snapshot()
        self.assertTrue(self.hub.acknowledge(self.peer, snap["revision"], snap["draftSha256"]))

    def call(self, name, **args):
        return self.tools.call(self.agent, "local-demo", name, args)

    def owner_request(self, text="Make it wider"):
        body = dict(action="create", body=text, moduleIds=["house/level/living"], kind="instruction", parameters={})
        OwnerMcp(None, self.d.host, None).dispatch(self.d.owner, "local-demo", "/requests", "POST", body)
        return self.d.host.requests.read(ld.LOCAL_TENANT, "local-demo")[-1]["id"]

    def build_room(self):
        room = house._room("living", False)
        fence = self.call("acquire_writer")["fence"]
        out = self.call("apply_operation", fence=fence, transaction=txn(0, [create(room)], "t1"))
        self.hub.heartbeat(self.peer, True)
        self.ack()
        return room, fence, out

    def test_int_request_id_is_addressed_only_after_the_render_ack(self):
        """Fails on eb28489: an integer id (as read_owner_requests returns it) never associated."""
        room, fence, _ = self.build_room()
        rid = self.owner_request()
        self.assertIsInstance(rid, int)
        listed = self.call("read_owner_requests")["requests"]
        self.assertEqual([item["id"] for item in listed], [rid])
        self.assertEqual(self.channel.requests[str(rid)]["status"], "read")
        revised = copy.deepcopy(room)
        revised["revision"] = 2
        out = self.call("apply_operation", fence=fence, requestId=rid, transaction=txn(1, [swap(revised, 1)], "t2"))
        self.assertEqual(out["projectRevision"], 2)
        self.assertEqual(self.channel.requests[str(rid)]["status"], "read")        # accepted, not yet rendered
        self.hub.heartbeat(self.peer, True)
        self.ack()
        self.assertEqual(self.channel.requests[str(rid)]["status"], "addressed")   # only after ACK

    def test_string_id_unknown_id_and_withdrawn_request(self):
        room, fence, _ = self.build_room()
        rid = self.owner_request()
        self.call("read_owner_requests")
        revised = copy.deepcopy(room)
        revised["revision"] = 2
        self.call("apply_operation", fence=fence, requestId="9999", transaction=txn(1, [swap(revised, 1)], "t2"))
        self.hub.heartbeat(self.peer, True)
        self.ack()
        self.assertEqual(self.channel.requests[str(rid)]["status"], "read")        # unknown id: no association, no error
        revised2 = copy.deepcopy(revised)
        revised2["revision"] = 3
        self.call("apply_operation", fence=fence, requestId=str(rid), transaction=txn(2, [swap(revised2, 2)], "t3"))
        self.channel.requests[str(rid)]["status"] = "withdrawn"
        self.hub.heartbeat(self.peer, True)
        self.ack()
        self.assertEqual(self.channel.requests[str(rid)]["status"], "withdrawn")   # terminal

    def test_include_guide_delivers_hash_matched_version_2_text_and_default_is_unchanged(self):
        plain = self.call("read_project")
        self.assertNotIn("guide", plain)
        full = self.call("read_project", includeGuide=True)
        guide = full["guide"]
        self.assertEqual(guide["version"], GUIDE_VERSION)
        self.assertEqual(GUIDE_VERSION, 2)
        self.assertEqual(guide["sha256"], GUIDE_SHA256)
        import hashlib
        self.assertEqual(hashlib.sha256(guide["markdown"].encode("utf-8")).hexdigest(), GUIDE_SHA256)
        self.assertLessEqual(len(guide["markdown"].encode("utf-8")), 24 * 1024)
        self.assertEqual({k: v for k, v in full.items() if k != "guide"}, plain)

    def test_include_ir_returns_the_committed_module_and_default_is_unchanged(self):
        room, _, _ = self.build_room()
        plain = self.call("inspect_module", moduleId=room["moduleId"])
        self.assertNotIn("module", plain)
        full = self.call("inspect_module", moduleId=room["moduleId"], includeIr=True)
        committed = self.actor._state.project.modules[room["moduleId"]]
        from core.project.operations import canonical_json
        self.assertEqual(canonical_json(full["module"]), canonical_json(committed))
        self.assertEqual({k: v for k, v in full.items() if k != "module"}, plain)
        with self.assertRaises(ToolFailure) as caught:
            self.call("inspect_module", moduleId="house/none", includeIr=True)
        self.assertEqual(caught.exception.code, "NOT_FOUND")

    def test_instructions_and_descriptions_fit_client_limits_and_name_the_new_parameters(self):
        self.assertLessEqual(len(INSTRUCTIONS), 1800)
        for name, text in TOOLS.items():
            self.assertLessEqual(len(text), 2048, name)
        self.assertIn("includeGuide", TOOLS["read_project"])
        self.assertIn("includeIr", TOOLS["inspect_module"])
        self.assertIn("requestId", TOOLS["apply_operation"])


if __name__ == "__main__":
    unittest.main()
