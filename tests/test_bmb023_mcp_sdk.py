"""Real SDK v2.3.0 against actual stdio subprocess, not an internal reader.

CI installs pinned MCP Python SDK 2.3.0. Test data and roots are synthetic.
"""
import asyncio
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import Client, MCPError, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
MID = "house/living"


class MCPRealClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        self.root.mkdir(mode=0o700)

    def server(self, allow_writes=False):
        args = ["-m", "agent.bmb_mcp", "--root", str(self.root)]
        if allow_writes:
            args.append("--allow-writes")
        return StdioServerParameters(command=sys.executable, args=args,
                                     env={"PYTHONPATH": str(ROOT)})

    async def test_sdk_discovery_read_only_and_protocol_error(self):
        async with Client(self.server(), mode="auto") as client:
            self.assertEqual(client.protocol_version, "2026-07-28")
            self.assertIsNotNone(client.server_capabilities.tools)
            found = await client.list_tools()
            names = {tool.name for tool in found.tools}
            self.assertEqual(names, {"bmb_inspect_module", "bmb_validate_journals",
                                     "bmb_validate_assembly"})
            result = await client.call_tool("bmb_validate_journals", {})
            self.assertFalse(result.is_error)
            self.assertTrue(result.structured_content["ok"])
            denied = await client.call_tool("bmb_create_module", {"moduleId": MID})
            self.assertTrue(denied.is_error)
            self.assertEqual(denied.structured_content["error"]["code"], "PERMISSION_DENIED")
            with self.assertRaises(MCPError) as ctx:
                await client.call_tool("this_tool_is_unknown", {})
            self.assertIn("Unknown tool", str(ctx.exception))
        self.assertFalse((self.root / "modules").exists())

    async def test_sdk_write_visibility_success_and_business_failure(self):
        async with Client(self.server(allow_writes=True), mode="auto") as client:
            self.assertEqual(client.protocol_version, "2026-07-28")
            found = await client.list_tools()
            self.assertEqual(len(found.tools), 6)
            created = await client.call_tool("bmb_create_module", {"moduleId": MID})
            self.assertFalse(created.is_error)
            self.assertTrue(created.structured_content["ok"])
            again = await client.call_tool("bmb_create_module", {"moduleId": MID})
            self.assertTrue(again.is_error)
            self.assertIn("error", again.structured_content)
            inspected = await client.call_tool("bmb_inspect_module", {"moduleId": MID})
            self.assertFalse(inspected.is_error)
            self.assertTrue(inspected.structured_content["ok"])


if __name__ == "__main__":
    unittest.main()
