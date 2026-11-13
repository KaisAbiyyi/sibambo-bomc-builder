"""SE-03.A: the remote construction guide and agent-grade tool descriptions.

A scripted client (a real MCP SDK client over TLS) completes a two-module seam build by following
ONLY the guide's own examples, so the guide cannot rot. First-attempt tool-call validity is
measured here and reported (SE-11 repeats it with real agents).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.types import Tool  # noqa: E402,F401  (imported to prove the SDK type module is available)

from service import errors  # noqa: E402
from service.guide.tool_descriptions import GUIDE_PATH, GUIDE_SHA256, GUIDE_VERSION, TOOLS  # noqa: E402
from tests import test_remote_mcp as base  # noqa: E402

GUIDE = GUIDE_PATH.read_text(encoding="utf-8")


def example(tag: str) -> dict:
    match = re.search(r"```json " + re.escape(tag) + r"\n(.+?)\n```", GUIDE, re.S)
    assert match, f"guide example {tag} missing"
    return json.loads(match.group(1))


class GuideTextTests(unittest.TestCase):
    def test_guide_hash_and_version_match_what_read_project_reports(self):
        self.assertEqual(GUIDE_SHA256, hashlib.sha256(GUIDE.encode("utf-8")).hexdigest())
        self.assertEqual(GUIDE_VERSION, 1)
        self.assertIn("guideVersion 1", GUIDE)

    def test_guide_states_the_non_negotiables(self):
        for phrase in ("+Z is up", "Metres", "untrusted data", "send one write", "never in parallel",
                       "8 KiB", "one room per module", "BUSY", "retryAfterMs", "idempotencyKey", "no save or export",
                       "256 KiB", "64 KiB", "1 to 8 modules"):
            self.assertIn(phrase.lower(), GUIDE.lower(), phrase)

    def test_every_error_code_the_guide_names_exists_in_the_catalogue(self):
        named = set(re.findall(r"`([A-Z][A-Z_]{3,})`", GUIDE))
        self.assertTrue(named)
        self.assertEqual(sorted(c for c in named if c not in errors.CATALOG), [])

    def test_tool_descriptions_lint_units_bounds_example_and_error_codes(self):
        self.assertEqual(set(TOOLS), {"read_project", "inspect_module", "acquire_writer", "release_writer",
                                      "apply_operation", "operation_status", "validate_draft", "read_owner_requests"})
        for name, text in TOOLS.items():
            for label in ("Units:", "Bounds:", "Example:", "Errors:"):
                self.assertIn(label, text, f"{name} lacks {label}")
            tail = text.split("Errors:", 1)[1].split(". ", 1)[0]
            codes = [c.strip(" .") for c in tail.split(",") if c.strip(" .")]
            self.assertTrue(codes, name)
            for code in codes:
                self.assertIn(code, errors.CATALOG, f"{name}: unknown code {code}")
            example_text = text.split("Example:", 1)[1].split(" Errors:", 1)[0]
            self.assertIn("->", example_text, f"{name}: example needs an input and a result")
            self.assertIn("untrusted data", text, f"{name} must warn that results are untrusted")
            self.assertLess(len(text), 2400, name)
        self.assertIn("metres", TOOLS["apply_operation"])
        self.assertIn("+Z", TOOLS["apply_operation"])
        self.assertIn("one at a time", TOOLS["apply_operation"].lower())
        self.assertFalse(any(w in n for n in TOOLS for w in ("save", "export")))

    def test_guide_examples_are_valid_modules_within_the_granularity_budget(self):
        from core.project.operations import canonical_json
        create = example("example:seam-create")
        for change in create["changes"]:
            self.assertLessEqual(len(canonical_json(change["module"])), 8 * 1024)
        self.assertEqual(len(create["changes"]), 2)


class EvidenceTests(unittest.TestCase):
    def test_evidence_matches_the_pinned_expected_values_and_fails_closed(self):
        from examples import se03_evidence as ev
        receipt, log = ev.run()
        self.assertEqual(ev.check(receipt, ROOT / "docs/stable/owner-handoff/se03-expected.json"), [])
        self.assertEqual(receipt["guideSha256"], GUIDE_SHA256)
        self.assertLessEqual(receipt["compactReadProjectBytes"], 4096)
        self.assertEqual(receipt["errorCodeCount"], len(set(errors.CATALOG) - {'RENDER_PENDING'}))  # frozen SE-03 receipt; SE-05 adds this code
        self.assertTrue(all(v.startswith(("PASS", "NOT_RUN")) for v in receipt["gates"].values()))
        self.assertTrue(any(line.startswith("REJECTED") for line in log))
        tampered = dict(receipt, projectionSha256="0" * 64)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text(json.dumps({k: tampered[k] for k in ev.EXPECTED_KEYS}))
            self.assertTrue(ev.check(receipt, path))


class ScriptedClientTests(unittest.IsolatedAsyncioTestCase):
    """Follows the guide's loop literally: read -> acquire -> write A -> write B -> validate -> release."""

    @classmethod
    def setUpClass(cls):
        base.setUpModule()

    @classmethod
    def tearDownClass(cls):
        base.tearDownModule()

    async def test_scripted_client_completes_a_two_module_seam_build_from_the_guide(self):
        project = "guide.build-1"
        await base.ENV.setup_project(project)
        calls = {"total": 0, "invalid": 0}
        async with base.ENV.client(base.ENV.mint("agent-1"), project) as client:
            async def call(name, args):
                calls["total"] += 1
                result = await client.call_tool(name, args)
                if result.is_error and result.structured_content["error"]["code"] in ("INVALID_REQUEST", "INVALID_OPERATION"):
                    calls["invalid"] += 1
                return result

            read = (await call("read_project", {})).structured_content
            self.assertEqual(read["guideSha256"], GUIDE_SHA256)          # the agent sees which guide to follow
            self.assertEqual(read["projectRevision"], 0)
            fence = (await call("acquire_writer", {})).structured_content["fence"]
            a = await call("apply_operation", {"transaction": example("example:seam-create"), "fence": fence})
            self.assertFalse(a.is_error, a.structured_content)
            self.assertEqual(a.structured_content["projectRevision"], 1)
            # the guide says a single module of the pair is rejected, and nothing changes
            join = example("example:seam-join")
            half = json.loads(json.dumps(join))
            half["idempotencyKey"] = half["transactionId"] = "guide-half"
            half["changes"] = half["changes"][:1]
            rejected = await call("apply_operation", {"transaction": half, "fence": fence})
            self.assertEqual(rejected.structured_content["error"]["code"], "INVALID_OPERATION")
            b = await call("apply_operation", {"transaction": join, "fence": fence})
            self.assertFalse(b.is_error, b.structured_content)
            self.assertEqual(b.structured_content["projectRevision"], 2)
            checked = (await call("validate_draft", {})).structured_content
            self.assertTrue(checked["valid"] and checked["compiled"], checked)
            final = (await call("read_project", {})).structured_content
            self.assertEqual(final["projectRevision"], 2)
            self.assertEqual(sorted(m["revision"] for m in final["modules"]), [2, 2])
            self.assertTrue((await call("release_writer", {"fence": fence})).structured_content["released"])
        # first-attempt validity: only the deliberate one-sided probe was invalid
        self.assertEqual(calls["invalid"], 1)
        print(f"\nGUIDE_FIRST_ATTEMPT_VALIDITY total={calls['total']} invalid={calls['invalid']} "
              f"(1 deliberate probe) sha={GUIDE_SHA256[:12]}")


if __name__ == "__main__":
    unittest.main()
