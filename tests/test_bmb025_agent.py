"""BMB-025: real, bounded stdio MCP and BMB-024 context on synthetic projects."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from agentguide.controller import (
    ControllerError, FIXTURE, META, MCPClient, REPO, _error_code, _request, _tool,
    run_scenario,
)

ASSEMBLY = REPO / "examples" / "module-ir-two-rooms.json"


class ScriptedAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenario = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.assembly = json.loads(ASSEMBLY.read_text(encoding="utf-8"))

    def test_baseline_scripted_mcp_flow_and_all_explicit_gates(self):
        with tempfile.TemporaryDirectory(prefix="bmb025-test-") as temp:
            root = Path(temp) / "private-project"
            result = run_scenario(root, copy.deepcopy(self.scenario), copy.deepcopy(self.assembly))
            self.assertEqual(result["bmb025TargetVerdict"], "PASS")
            self.assertEqual(result["fullProductE2E"], "INCOMPLETE")
            self.assertEqual(result["observations"]["revisions"],
                             {"house/floor-1/living": 2, "house/floor-1/hall": 1})
            self.assertTrue(result["observations"]["hallHashUnchanged"])
            self.assertTrue(result["observations"]["livingHashAdvanced"])
            self.assertEqual(result["observations"]["graphModules"], 2)
            self.assertEqual(result["observations"]["resume"], "current")
            self.assertEqual(result["observations"]["mcpToolCalls"], 18)
            self.assertEqual(result["fixtureSha256"], hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
            self.assertEqual(result["unexpectedFailures"], [])
            self.assertTrue(all(x in {"PASS", "NOT_RUN"} for x in result["gates"].values()))
            for gate in ("mcp_discovery", "create_inspect", "stale_edit_rejected", "local_repair",
                         "idempotent_replay", "unrelated_module_unchanged", "journal_integrity",
                         "synthetic_ir_graph_validation", "unsafe_input_rejected",
                         "readonly_write_denied", "scoped_context", "checkpoint_resume"):
                self.assertEqual(result["gates"][gate], "PASS", gate)
            for gate in ("journal_ir_mapping", "typed_geometry_or_bomc_compile",
                         "independent_consumer_readback", "live_llm_agent",
                         "native_windows_security", "provider_native_token_usage"):
                self.assertEqual(result["gates"][gate], "NOT_RUN", gate)
            self.assertEqual(
                [x["code"] for x in result["expectedNegativeTests"]],
                ["REVISION_CONFLICT", "INVALID_ARGUMENT", "INVALID_ARGUMENT", "PERMISSION_DENIED"],
            )
            self.assertFalse((root / "modules" / "house__forbidden").exists())
            self.assertTrue((root / "sessions" / "bmb025-demo.jsonl").is_file())

    def test_declared_contract_rejects_wrong_revision_target_before_launch(self):
        fixture = copy.deepcopy(self.scenario)
        fixture["revision"]["module"] = "house/floor-1/hall"
        with tempfile.TemporaryDirectory(prefix="bmb025-bad-") as temp:
            root = Path(temp) / "project"
            with self.assertRaisesRegex(ControllerError, "revision target mismatch"):
                run_scenario(root, fixture, copy.deepcopy(self.assembly))
            self.assertFalse((root / "modules").exists())

    def test_protocol_metadata_and_unsafe_no_write_grant(self):
        self.assertEqual(META["io.modelcontextprotocol/protocolVersion"], "2026-07-28")
        request = _request("tools/call", {"name": "bmb_validate_journals", "arguments": {}}, 5)
        self.assertEqual(request["id"], 5)
        self.assertEqual(request["params"]["_meta"], META)
        with tempfile.TemporaryDirectory(prefix="bmb025-ro-") as temp:
            root = Path(temp) / "project"
            root.mkdir(mode=0o700)
            calls = MCPClient(root, writes=False).batch([
                _tool("bmb_create_module", {"moduleId": "house/living"}),
                _tool("bmb_validate_journals"),
            ])
            self.assertEqual(_error_code(calls[0], "read-only create"), "PERMISSION_DENIED")
            self.assertEqual(calls[1]["result"]["structuredContent"]["data"]["revisions"], {})
            self.assertFalse((root / "modules").exists())


    def test_red_gate_unexpected_stale_acceptance_must_not_queue_repair(self):
        """If the transport says stale edit succeeded, no repair or replay may have been sent."""
        original = MCPClient.batch
        seen = []

        def injected(client, actions):
            for method, params in actions:
                if method == "tools/call":
                    seen.append((params["name"], (params["arguments"] or {}).get("idempotencyKey")))
            responses = original(client, actions)
            for idx, (method, params) in enumerate(actions):
                if method == "tools/call" and (params["arguments"] or {}).get("idempotencyKey") == "bmb025-stale":
                    responses[idx] = copy.deepcopy(responses[idx])
                    responses[idx]["result"]["isError"] = False
                    responses[idx]["result"]["structuredContent"] = {
                        "ok": True, "data": {"revision": 1, "replayed": False}}
            return responses

        with tempfile.TemporaryDirectory(prefix="bmb025-stale-gate-") as tmp:
            root = Path(tmp) / "project"
            with mock.patch.object(MCPClient, "batch", injected):
                with self.assertRaises(ControllerError):
                    run_scenario(root, copy.deepcopy(self.scenario), copy.deepcopy(self.assembly))
            self.assertNotIn(("bmb_edit_module", "bmb025-door-095"), seen)
            from core.storage.journal import JournalStore
            self.assertEqual(JournalStore.open(root).revision("house/floor-1/living"), 1)

    def test_red_gate_corrupt_stale_inspection_must_not_queue_repair(self):
        """An unexpected post-stale revision/hash halts before any recovery mutation."""
        original = MCPClient.batch
        seen = []
        stale_seen = False

        def injected(client, actions):
            nonlocal stale_seen
            for method, params in actions:
                if method == "tools/call":
                    key = (params["arguments"] or {}).get("idempotencyKey")
                    seen.append((params["name"], key))
                    if key == "bmb025-stale":
                        stale_seen = True
            responses = original(client, actions)
            if stale_seen:
                for idx, (method, params) in enumerate(actions):
                    if method == "tools/call" and params["name"] == "bmb_inspect_module":
                        if params["arguments"]["moduleId"] == "house/floor-1/living":
                            responses[idx] = copy.deepcopy(responses[idx])
                            responses[idx]["result"]["structuredContent"]["data"]["journalHash"] = "f" * 64
                            break
            return responses

        with tempfile.TemporaryDirectory(prefix="bmb025-inspect-gate-") as tmp:
            root = Path(tmp) / "project"
            with mock.patch.object(MCPClient, "batch", injected):
                with self.assertRaises(ControllerError):
                    run_scenario(root, copy.deepcopy(self.scenario), copy.deepcopy(self.assembly))
            self.assertNotIn(("bmb_edit_module", "bmb025-door-095"), seen)
            from core.storage.journal import JournalStore
            self.assertEqual(JournalStore.open(root).revision("house/floor-1/living"), 1)

    def test_red_revised_assembly_input_must_reflect_accepted_journal_width(self):
        """Assert the document actually SENT over MCP is the revised synthetic 0.95m graph."""
        original = MCPClient.batch
        documents = []

        def observed(client, actions):
            for method, params in actions:
                if method == "tools/call" and params["name"] == "bmb_validate_assembly":
                    document = params["arguments"]["document"]
                    if document.get("schemaVersion") == "1.0.0":
                        documents.append(copy.deepcopy(document))
            return original(client, actions)

        with tempfile.TemporaryDirectory(prefix="bmb025-ir-") as tmp:
            with mock.patch.object(MCPClient, "batch", observed):
                result = run_scenario(Path(tmp) / "project",
                                      copy.deepcopy(self.scenario), copy.deepcopy(self.assembly))
        self.assertEqual(len(documents), 1)
        document = documents[0]
        living = next(m for m in document["modules"] if m["moduleId"] == "house/floor-1/living")
        hall = next(m for m in document["modules"] if m["moduleId"] == "house/floor-1/hall")
        door = next(op for op in living["operations"] if op["kind"] == "opening-cut")
        self.assertEqual(door["width"], 0.95)
        self.assertEqual(living["ports"][0]["width"], 0.95)
        self.assertEqual(hall["ports"][0]["width"], 0.95)
        self.assertEqual(living["revision"], 2)
        self.assertEqual(hall["dependencies"][0]["minRevision"], 2)
        self.assertEqual(result["observations"]["validatedDoorWidthM"], 0.95)
        self.assertEqual(result["gates"]["revised_synthetic_ir_projection"], "PASS")


if __name__ == "__main__":
    unittest.main()
