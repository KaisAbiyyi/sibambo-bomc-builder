"""BMB-023: stdio JSON-RPC + hostile synthetic requests, no owner files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MID = "house/living"
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "synthetic-test", "version": "1"},
}


def request(method, payload=None, ident=1, *, meta=None):
    params = {"_meta": META if meta is None else meta}
    if payload is not None:
        params.update(payload)
    return {"jsonrpc": "2.0", "id": ident, "method": method, "params": params}


def tool(name, args=None, ident=1):
    return request("tools/call", {"name": name, "arguments": args if args is not None else {}}, ident)


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()

    def talk(self, *messages, writes=True, raw=None, root=None):
        argv = [sys.executable, "-m", "agent.bmb_mcp", "--root", str(root or self.root)]
        if writes:
            argv.append("--allow-writes")
        payload = raw if raw is not None else b"".join(
            json.dumps(item, separators=(",", ":")).encode("utf-8") + b"\n"
            for item in messages
        )
        proc = subprocess.run(argv, cwd=ROOT, input=payload, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=70)
        lines = [json.loads(s) for s in proc.stdout.splitlines()]
        return proc.returncode, lines, proc.stderr

    def valid(self, *messages, **kw):
        rc, out, err = self.talk(*messages, **kw)
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(out), len(messages), (out, err))
        self.assertFalse(err, err)
        return out

    def test_discover_without_handshake(self):
        out = self.valid(request("server/discover"), request("tools/list", ident=2))
        self.assertEqual(out[0]["result"]["supportedVersions"], ["2026-07-28"])
        self.assertEqual(out[0]["result"]["resultType"], "complete")
        names = {entry["name"] for entry in out[1]["result"]["tools"]}
        self.assertEqual(len(names), 6)
        self.assertIn("bmb_edit_module", names)

    def test_read_only_launch_hides_write_tools_and_rejects_forged_call(self):
        out = self.valid(request("tools/list"),
                         tool("bmb_create_module", {"moduleId": MID}, 2), writes=False)
        names = {entry["name"] for entry in out[0]["result"]["tools"]}
        self.assertNotIn("bmb_create_module", names)
        self.assertEqual(out[1]["result"]["structuredContent"]["error"]["code"], "PERMISSION_DENIED")
        self.assertFalse((self.root / "modules").exists())

    def test_create_inspect_edit_replay_rollback(self):
        ops = [{"op": "add", "id": "wall", "data": {"height": 3}}]
        out = self.valid(
            tool("bmb_create_module", {"moduleId": MID}, 1),
            tool("bmb_edit_module", {"moduleId": MID, "expectedRevision": 0,
                                    "idempotencyKey": "step-1", "ops": ops}, 2),
            tool("bmb_edit_module", {"moduleId": MID, "expectedRevision": 0,
                                    "idempotencyKey": "step-1", "ops": ops}, 3),
            tool("bmb_inspect_module", {"moduleId": MID, "includeBlocks": True}, 4),
            tool("bmb_rollback_module", {"moduleId": MID, "expectedRevision": 1,
                                        "idempotencyKey": "undo", "toRevision": 0}, 5),
            tool("bmb_validate_journals", {}, 6),
        )
        self.assertTrue(all(row["result"]["structuredContent"]["ok"] for row in out))
        self.assertTrue(out[2]["result"]["structuredContent"]["data"]["replayed"])
        self.assertEqual(out[3]["result"]["structuredContent"]["data"]["blocks"]["wall"]["height"], 3)
        self.assertEqual(out[-1]["result"]["structuredContent"]["data"]["revisions"], {MID: 2})

    def test_stale_revision_is_error_result_not_protocol_error(self):
        self.valid(tool("bmb_create_module", {"moduleId": MID}))
        edits = {"moduleId": MID, "expectedRevision": 0, "idempotencyKey": "first",
                 "ops": [{"op": "add", "id": "a", "data": {"a": 1}}]}
        out = self.valid(tool("bmb_edit_module", edits, 1),
                         tool("bmb_edit_module", {**edits, "idempotencyKey": "second"}, 2))
        self.assertFalse(out[1]["result"]["structuredContent"]["ok"])
        self.assertTrue(out[1]["result"]["isError"])
        self.assertEqual(out[1]["result"]["structuredContent"]["error"]["code"], "REVISION_CONFLICT")

    def test_idempotency_conflict_does_not_change_journal(self):
        self.valid(tool("bmb_create_module", {"moduleId": MID}))
        ops = [{"op": "add", "id": "a", "data": {"v": 1}}]
        self.valid(tool("bmb_edit_module", {"moduleId": MID, "expectedRevision": 0,
                                           "idempotencyKey": "same", "ops": ops}))
        original = (self.root / "modules" / "house__living" / "journal.jsonl").read_bytes()
        out = self.valid(tool("bmb_edit_module", {"moduleId": MID, "expectedRevision": 1,
                                                  "idempotencyKey": "same", "ops": ops}))[0]
        self.assertEqual(out["result"]["structuredContent"]["error"]["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(original, (self.root / "modules" / "house__living" / "journal.jsonl").read_bytes())

    def test_invalid_args_unknown_tool_and_shell_escape(self):
        for name, arg in [
            ("bmb_create_module", {"moduleId": "../../outside"}),
            ("bmb_create_module", {"moduleId": "C:\\Windows\\system32"}),
            ("bmb_create_module", {"moduleId": MID, "cmd": "whoami"}),
            ("bmb_inspect_module", {"moduleId": MID, "includeBlocks": "true"}),
            ("bmb_edit_module", {"moduleId": MID, "expectedRevision": False,
                                 "idempotencyKey": "x", "ops": []}),
            ("bmb_edit_module", {"moduleId": MID, "expectedRevision": 0,
                                 "idempotencyKey": "x", "ops": [{"op": "add", "id": "a",
                                                                "data": {}, "shell": "exec"}]}),
        ]:
            with self.subTest(name=name, arg=arg):
                value = self.valid(tool(name, arg))[0]["result"]
                self.assertEqual(value["structuredContent"]["error"]["code"], "INVALID_ARGUMENT")
        value = self.valid(tool("unknown", {}))[0]["result"]
        self.assertEqual(value["structuredContent"]["error"]["code"], "UNKNOWN_TOOL")
        self.assertFalse((self.root / "modules").exists())

    def test_malformed_frame_and_duplicates(self):
        for raw in (b'{"jsonrpc":"2.0","id":1,"id":2,"method":"tools/list"}\n',
                    b'{"not":"json"\n', b'\xff\n', b'{"x":NaN}\n'):
            with self.subTest(raw=raw):
                rc, out, err = self.talk(raw=raw)
                self.assertEqual((rc, len(out)), (0, 1), err)
                self.assertIn(out[0]["error"]["code"], (-32700, -32600))
        rc, out, _ = self.talk(raw=b" " * (256 * 1024 + 3) + b"\n")
        self.assertEqual((rc, len(out), out[0]["error"]["code"]), (0, 1, -32600))

    def test_metadata_version_and_rpc_method_errors(self):
        no_caps = {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}
        old = {"io.modelcontextprotocol/protocolVersion": "2025-11-25",
               "io.modelcontextprotocol/clientCapabilities": {}}
        out = self.valid(
            request("tools/list", meta=no_caps, ident=1),
            request("tools/list", meta=old, ident=2),
            request("initialize", ident=3),
        )
        self.assertEqual(out[0]["error"]["code"], -32602)
        self.assertEqual(out[1]["error"]["code"], -32022)
        self.assertEqual(out[1]["error"]["data"]["supported"], ["2026-07-28"])
        self.assertEqual(out[2]["error"]["code"], -32601)

    def test_validate_synthetic_assembly(self):
        envelope = json.loads((ROOT / "examples" / "module-ir-two-rooms.json").read_text())
        out = self.valid(tool("bmb_validate_assembly", {"document": envelope}))[0]
        self.assertTrue(out["result"]["structuredContent"]["ok"])
        self.assertEqual(out["result"]["structuredContent"]["data"]["moduleCount"], 2)
        envelope["schemaVersion"] = "invalid"
        out = self.valid(tool("bmb_validate_assembly", {"document": envelope}))[0]
        self.assertEqual(out["result"]["structuredContent"]["error"]["code"], "INVALID_ARGUMENT")

    def test_explicit_count_and_depth_limits(self):
        ops = [{"op": "add", "id": "a", "data": {}}] * 257
        out = self.valid(tool("bmb_edit_module", {"moduleId": MID, "expectedRevision": 0,
                         "idempotencyKey": "over", "ops": ops}))[0]
        self.assertEqual(out["result"]["structuredContent"]["error"]["code"], "LIMIT_EXCEEDED")
        nested = {}
        ptr = nested
        for _ in range(34):
            ptr["a"] = {}
            ptr = ptr["a"]
        out = self.valid(tool("bmb_validate_assembly", {"document": nested}))[0]
        # Frame depth is rejected before JSON-RPC tool dispatch.\n        self.assertEqual(out["error"]["code"], -32600)

    def test_symlink_module_denied(self):
        self.valid(tool("bmb_create_module", {"moduleId": MID}))
        module = self.root / "modules" / "house__living"
        try:
            (self.root / "modules" / "house__other").symlink_to(module, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation requires OS privilege")
        rc, out, err = self.talk(tool("bmb_inspect_module", {"moduleId": MID}))
        self.assertEqual(rc, 2)
        self.assertFalse(out)
        self.assertIn(b"unsafe root", err)

    def test_hardlink_journal_denied(self):
        self.valid(tool("bmb_create_module", {"moduleId": MID}))
        journal = self.root / "modules" / "house__living" / "journal.jsonl"
        try:
            os.link(journal, self.root / "other")
        except (OSError, NotImplementedError):
            self.skipTest("hardlinks unavailable")
        rc, out, err = self.talk(tool("bmb_inspect_module", {"moduleId": MID}))
        self.assertEqual(rc, 2)
        self.assertFalse(out)
        self.assertIn(b"unsafe root", err)

    def test_launch_rejects_relative_root(self):
        rc, out, err = self.talk(root=Path("relative-project"))
        self.assertEqual(rc, 2)
        self.assertFalse(out)
        self.assertIn(b"MCP launch rejected", err)

    def test_notifications_have_no_reply(self):
        notify = {"jsonrpc": "2.0", "method": "notifications/cancelled",
                  "params": {"requestId": 42}}
        rc, out, err = self.talk(notify, request("server/discover", ident=9))
        self.assertEqual((rc, len(out)), (0, 1), err)
        self.assertEqual(out[0]["id"], 9)

    def test_each_result_has_bounded_output_and_server_info(self):
        self.valid(tool("bmb_create_module", {"moduleId": MID}))
        result = self.valid(tool("bmb_inspect_module", {"moduleId": MID}))[0]["result"]
        self.assertEqual(result["resultType"], "complete")
        self.assertIn("io.modelcontextprotocol/serverInfo", result["_meta"])
        self.assertLess(len(json.dumps(result).encode()), 256 * 1024)

    def test_empty_stream_exits_without_stdout(self):
        rc, out, err = self.talk(raw=b"")
        self.assertEqual((rc, out, err), (0, [], b""))


    def test_rate_limit_is_bounded_on_single_process(self):
        out = self.valid(*(tool("unknown", {}, i) for i in range(1, 62)))
        self.assertEqual(out[0]["result"]["structuredContent"]["error"]["code"], "UNKNOWN_TOOL")
        self.assertEqual(out[-1]["result"]["structuredContent"]["error"]["code"], "LIMIT_EXCEEDED")

    def test_large_inspection_never_returns_truncated_json(self):
        self.valid(tool("bmb_create_module", {"moduleId": MID}))
        ops = [{"op": "add", "id": f"block-{i}", "data": {"label": "x" * 54_000}}
               for i in range(4)]
        out = self.valid(tool("bmb_edit_module", {"moduleId": MID, "expectedRevision": 0,
                         "idempotencyKey": "large", "ops": ops}),
                         tool("bmb_inspect_module", {"moduleId": MID, "includeBlocks": True}, 2))
        self.assertTrue(out[0]["result"]["structuredContent"]["ok"])
        self.assertEqual(out[1]["result"]["structuredContent"]["error"]["code"], "LIMIT_EXCEEDED")
        self.assertEqual(self.valid(tool("bmb_inspect_module", {"moduleId": MID}))[0]
                         ["result"]["structuredContent"]["data"]["blockCount"], 4)

    def test_exclusive_root_lock_blocks_second_server(self):
        argv = [sys.executable, "-m", "agent.bmb_mcp", "--root", str(self.root)]
        first = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            first.stdin.write(json.dumps(request("server/discover")).encode() + b"\\n")
            first.stdin.flush()
            ready = json.loads(first.stdout.readline())
            self.assertEqual(ready["id"], 1)
            second = subprocess.run(argv, cwd=ROOT, input=b"", stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=20)
            self.assertEqual(second.returncode, 2)
            self.assertFalse(second.stdout)
        finally:
            first.stdin.close()
            first.wait(timeout=10)



if __name__ == "__main__":
    unittest.main()
