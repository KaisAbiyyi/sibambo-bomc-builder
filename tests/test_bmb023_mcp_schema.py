"""Independent JSON Schema validation against pinned official MCP 2026-07-28 schema.

Vendored upstream schema is immutable at commit 271ecc9accafdd9b83a3c869fa67c22953b2af80.
Validation uses jsonschema 4.23.0 in CI, not the adapter's hand-written predicates.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator

from test_bmb023_mcp import META, MID, ROOT, request, tool

SCHEMA_PATH = ROOT / "tests" / "fixtures" / "mcp-2026-07-28-schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate(definition, value):
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
              "$defs": SCHEMA["$defs"], "$ref": "#/$defs/" + definition}
    Draft202012Validator(schema).validate(value)


class MCPPublishedSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        self.root.mkdir(mode=0o700)

    def exchange(self, *messages, writes=False):
        argv = [sys.executable, "-m", "agent.bmb_mcp", "--root", str(self.root)]
        if writes:
            argv.append("--allow-writes")
        payload = b"".join(json.dumps(x).encode("utf-8") + b"\n" for x in messages)
        p = subprocess.run(argv, cwd=ROOT, input=payload, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=70)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(p.stderr, p.stderr)
        output = [json.loads(s) for s in p.stdout.splitlines()]
        self.assertEqual(len(output), len(messages))
        return output

    def test_official_schema_meta_and_tool_schema_valid(self):
        self.assertEqual(SCHEMA["$schema"], "https://json-schema.org/draft/2020-12/schema")
        for method, definition in (("server/discover", "DiscoverRequest"),
                                   ("tools/list", "ListToolsRequest")):
            validate(definition, request(method))
        validate("CallToolRequest", request("tools/call", {"name": "bmb_validate_journals"}))
        validate("CallToolRequest", tool("bmb_validate_journals"))
        self.assertEqual(META["io.modelcontextprotocol/protocolVersion"], "2026-07-28")

    def test_complete_discovery_and_listing_against_published_schema(self):
        messages = [request("server/discover"), request("tools/list", ident=2)]
        for writes in (False, True):
            out = self.exchange(*messages, writes=writes)
            validate("DiscoverResultResponse", out[0])
            validate("ListToolsResultResponse", out[1])
            for row in out:
                result = row["result"]
                self.assertEqual(result["ttlMs"], 0)
                self.assertEqual(result["cacheScope"], "private")
                self.assertEqual(result["resultType"], "complete")
            self.assertEqual(out[0]["result"]["supportedVersions"], ["2026-07-28"])
            names = {x["name"] for x in out[1]["result"]["tools"]}
            self.assertEqual(len(names), 6 if writes else 3)
            for item in out[1]["result"]["tools"]:
                Draft202012Validator.check_schema(item["inputSchema"])

    def test_schema_tool_results_and_protocol_errors(self):
        out = self.exchange(
            request("tools/call", {"name": "bmb_validate_journals"}),
            request("tools/call", {"name": "bmb_create_module",
                                   "arguments": {"moduleId": MID}}, 2),
            request("tools/call", {"name": "definitely_unknown"}, 3),
            request("tools/call", {"name": "bmb_validate_journals", "arguments": None}, 4),
            writes=False,
        )
        for row in out[:2]:
            validate("CallToolResultResponse", row)
            self.assertIn("resultType", row["result"])
        self.assertFalse(out[0]["result"]["isError"])
        self.assertTrue(out[1]["result"]["isError"])
        self.assertEqual(out[1]["result"]["structuredContent"]["error"]["code"], "PERMISSION_DENIED")
        for row in out[2:]:
            validate("JSONRPCErrorResponse", row)
            self.assertEqual(row["error"]["code"], -32602)
            self.assertNotIn("result", row)

    def test_jsonrpc_malformed_and_rejected_metadata_against_schema(self):
        no_caps = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
        bad = self.exchange(
            request("tools/list", meta=no_caps),
            request("tools/list", meta={**META, "io.modelcontextprotocol/protocolVersion": "2025-11-25"}, ident=2),
            request("tools/list", {"extra": True}, ident=3),
        )
        for row in bad:
            validate("JSONRPCErrorResponse", row)
        self.assertEqual([x["error"]["code"] for x in bad], [-32602, -32022, -32602])


if __name__ == "__main__":
    unittest.main()
