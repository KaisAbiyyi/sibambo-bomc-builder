"""BMB-022: subprocess acceptance with public synthetic fixtures only."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = "house/living"
K = "house/kitchen"


class CLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"

    def cmd(self, command, *args, payload=b"", include_root=True):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload).encode()
        if isinstance(payload, str):
            payload = payload.encode()
        argv = [sys.executable, "-m", "cli.bmb"]
        if include_root:
            argv.extend(["--root", str(self.root)])
        argv.extend([command, *map(str, args)])
        proc = subprocess.run(argv, input=payload, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, cwd=ROOT, timeout=20)
        lines = proc.stdout.decode().splitlines()
        self.assertEqual(len(lines), 1, (proc.returncode, proc.stdout, proc.stderr))
        self.assertFalse(proc.stderr)
        return proc.returncode, json.loads(lines[0])

    def create(self, mid=M):
        rc, resp = self.cmd("create", "--module-id", mid)
        self.assertEqual((rc, resp["ok"]), (0, True), resp)
        return resp["result"]

    def edit(self, rev, key, ops, *, mid=M, mins=None):
        payload = {"ops": ops}
        if mins is not None:
            payload["minRevisions"] = mins
        return self.cmd("edit", "--module-id", mid, "--expected-revision", rev, "--key", key, payload=payload)

    def op(self, bid="wall", value=1):
        return [{"op": "add", "id": bid, "data": {"v": value}}]

    def journal(self, mid=M):
        return (self.root / "modules" / mid.replace("/", "__") / "journal.jsonl")

    def test_create_inspect_validate(self):
        self.create()
        rc, r = self.cmd("inspect", "--module-id", M)
        self.assertEqual(rc, 0)
        self.assertEqual(r["result"]["revision"], 0)
        self.assertEqual(r["result"]["blockIds"], [])
        self.assertEqual(len(r["result"]["journalHash"]), 64)
        rc, r = self.cmd("validate")
        self.assertEqual((rc, r["result"]["revisions"]), (0, {M: 0}))

    def test_edit_and_snapshot(self):
        self.create()
        rc, r = self.edit(0, "k1", self.op())
        self.assertEqual((rc, r["result"]["revision"]), (0, 1))
        rc, r = self.cmd("inspect", "--module-id", M, "--blocks")
        self.assertEqual((rc, r["result"]["blocks"]), (0, {"wall": {"v": 1}}))
        self.assertEqual(r["result"]["blockCount"], 1)

    def test_idempotent_replay_no_new_bytes(self):
        self.create()
        self.edit(0, "same", self.op())
        original = self.journal().read_bytes()
        rc, r = self.edit(0, "same", self.op())
        self.assertEqual(rc, 0)
        self.assertTrue(r["result"]["replayed"])
        self.assertEqual(self.journal().read_bytes(), original)

    def test_stale_write_no_mutation(self):
        self.create()
        self.edit(0, "first", self.op())
        original = self.journal().read_bytes()
        rc, r = self.edit(0, "second", self.op("other"))
        self.assertEqual((rc, r["error"]["code"]), (3, "STALE_REVISION"))
        self.assertEqual(self.journal().read_bytes(), original)

    def test_conflicting_idempotency_key(self):
        self.create()
        self.edit(0, "first", self.op())
        original = self.journal().read_bytes()
        rc, r = self.edit(1, "first", self.op("other"))
        self.assertEqual((rc, r["error"]["code"]), (3, "IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.journal().read_bytes(), original)

    def test_invalid_edit_atomic(self):
        self.create()
        original = self.journal().read_bytes()
        rc, r = self.edit(0, "bad", self.op() + [{"op": "remove", "id": "absent"}])
        self.assertEqual((rc, r["error"]["code"]), (2, "INVALID_OPERATION"))
        self.assertEqual(self.journal().read_bytes(), original)

    def test_dependency_minimums(self):
        self.create(M)
        self.create(K)
        self.edit(0, "living1", self.op())
        rc, r = self.edit(0, "kitchen1", self.op("sink"), mid=K, mins={M: 1})
        self.assertEqual((rc, r["result"]["revision"]), (0, 1))
        original = self.journal(K).read_bytes()
        rc, r = self.edit(1, "kitchen2", self.op("oven"), mid=K, mins={M: 2})
        self.assertEqual((rc, r["error"]["code"]), (3, "STALE_DEPENDENCY"))
        self.assertEqual(self.journal(K).read_bytes(), original)

    def test_rollback_and_replay(self):
        self.create()
        self.edit(0, "k1", self.op("wall", 1))
        self.edit(1, "k2", [{"op": "replace", "id": "wall", "data": {"v": 2}}])
        args = ("--module-id", M, "--expected-revision", 2, "--key", "rb1", "--to-revision", 1)
        rc, r = self.cmd("rollback", *args)
        self.assertEqual((rc, r["result"]["revision"]), (0, 3))
        before = self.journal().read_bytes()
        rc, r = self.cmd("rollback", *args)
        self.assertEqual(rc, 0)
        self.assertTrue(r["result"]["replayed"])
        self.assertEqual(self.journal().read_bytes(), before)
        self.assertEqual(self.cmd("inspect", "--module-id", M, "--blocks")[1]["result"]["blocks"]["wall"], {"v": 1})

    def test_rollback_rejects_current_revision(self):
        self.create()
        self.edit(0, "k1", self.op())
        before = self.journal().read_bytes()
        rc, r = self.cmd("rollback", "--module-id", M, "--expected-revision", 1, "--key", "bad", "--to-revision", 1)
        self.assertEqual((rc, r["error"]["code"]), (2, "INVALID_OPERATION"))
        self.assertEqual(self.journal().read_bytes(), before)

    def test_corruption_is_detected(self):
        self.create()
        self.journal().write_bytes(self.journal().read_bytes() + b'{"bad":true}\n')
        rc, r = self.cmd("validate")
        self.assertEqual((rc, r["error"]["code"]), (4, "CORRUPT_JOURNAL"))

    def test_scoped_inspect_ignores_other_corrupt_module(self):
        self.create(M)
        self.create(K)
        p = self.journal(K)
        p.write_bytes(p.read_bytes() + b'{"bad":true}\n')
        self.assertEqual(self.cmd("inspect", "--module-id", M)[0], 0)
        self.assertEqual(self.cmd("validate")[1]["error"]["code"], "CORRUPT_JOURNAL")

    def test_bounded_and_invalid_json(self):
        self.create()
        before = self.journal().read_bytes()
        for payload in (b"{", b'{"ops":[],"ops":[]}', b'{"ops":NaN}', b"\xff", b" " * (1024 * 1024 + 1)):
            with self.subTest(payload=payload[:20]):
                rc, r = self.cmd("edit", "--module-id", M, "--expected-revision", 0, "--key", "bad", payload=payload)
                self.assertEqual((rc, r["error"]["code"]), (2, "INVALID_ARGUMENT"))
        self.assertEqual(self.journal().read_bytes(), before)

    def test_bad_request_schema(self):
        self.create()
        rc, r = self.cmd("edit", "--module-id", M, "--expected-revision", 0, "--key", "bad",
                         payload={"ops": [], "extra": True})
        self.assertEqual((rc, r["error"]["code"]), (2, "INVALID_ARGUMENT"))

    def test_assembly_validation(self):
        envelope = json.loads((ROOT / "examples" / "module-ir-two-rooms.json").read_text())
        rc, r = self.cmd("validate", "--assembly-stdin", payload=envelope, include_root=False)
        self.assertEqual(rc, 0)
        self.assertEqual(r["result"]["mode"], "assembly")
        self.assertEqual(r["result"]["moduleCount"], 2)
        self.assertEqual(len(r["result"]["seams"]), 1)
        envelope["modules"].append(envelope["modules"][0])
        rc, r = self.cmd("validate", "--assembly-stdin", payload=envelope, include_root=False)
        self.assertEqual((rc, r["error"]["code"]), (2, "INVALID_ASSEMBLY"))

    def test_assembly_bad_envelope_and_root_combo(self):
        rc, r = self.cmd("validate", "--assembly-stdin", payload={"modules": [], "extra": True}, include_root=False)
        self.assertEqual((rc, r["error"]["code"]), (2, "INVALID_ARGUMENT"))
        rc, r = self.cmd("validate", "--assembly-stdin", payload={"modules": []})
        self.assertEqual((rc, r["error"]["code"]), (2, "INVALID_ARGUMENT"))

    def test_error_payload_is_bounded_even_for_oversized_flags(self):
        rc, value = self.cmd("create", "--module-id", "X" * 10000)
        self.assertEqual((rc, value["error"]["code"]), (2, "INVALID_OPERATION"))
        self.assertLessEqual(len(value["error"]["message"]), 512)

    def test_assembly_version_is_pinned(self):
        rc, value = self.cmd("validate", "--assembly-stdin",
                             payload={"schemaVersion": "9.0.0", "modules": []}, include_root=False)
        self.assertEqual((rc, value["error"]["code"]), (2, "INVALID_ARGUMENT"))

    def test_root_and_parser_errors(self):
        rc, r = self.cmd("create", "--module-id", "../unsafe")
        self.assertEqual((rc, r["error"]["code"]), (2, "INVALID_OPERATION"))
        rc, r = self.cmd("inspect", "--module-id", M)
        self.assertEqual((rc, r["error"]["code"]), (4, "STORAGE_ERROR"))
        rc, r = self.cmd("create")
        self.assertEqual((rc, r["error"]["code"]), (2, "INVALID_ARGUMENT"))
        rc, r = self.cmd("oops", include_root=False)
        self.assertEqual((rc, r["error"]["code"]), (2, "INVALID_ARGUMENT"))


if __name__ == "__main__":
    unittest.main()
