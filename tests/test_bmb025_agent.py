"""BMB-025: real, bounded stdio MCP and BMB-024 context on synthetic projects."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
