"""BMB-026 independent synthetic cloud gates: BOMC, topology and localized revision."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bomc.compiler.graph_to_bomc import CompileError, compile_document  # noqa: E402
from core.assembly import AssemblyError, DuplicateOwnershipError, assemble  # noqa: E402
from core.geometry.openings import build_wall_with_openings  # noqa: E402
from core.storage.journal import JournalStore  # noqa: E402
from core.identity.store import StaleRevisionError  # noqa: E402
from examples.bmb026_house import (ROOM_IDS, ROOMS, build_house, canonical_hash, evidence)  # noqa: E402
from tests.interop.reader import read as independent_read  # noqa: E402


def modules(document):
    return {m["moduleId"]: m for m in document["modules"]}


class FourRoomTests(unittest.TestCase):
    def setUp(self):
        self.baseline = build_house()
        self.revised = build_house(revised=True)

    def test_layout_four_named_rooms_and_one_flat_roof(self):
        self.assertEqual(set(modules(self.baseline)),
                         set(ROOM_IDS.values()) | {"house/level/roof"})
        self.assertEqual(len(ROOMS), 4)
        self.assertEqual([m["revision"] for m in self.baseline["modules"]], [1] * 5)
        self.assertEqual([m["revision"] for m in self.revised["modules"]], [1, 2, 1, 1, 1])
        roof = modules(self.baseline)["house/level/roof"]
        self.assertEqual(roof["operations"][0]["role"], "roof")
        for room in ROOMS:
            self.assertEqual(sum(op["kind"] == "floor-slab" for op in
                                 modules(self.baseline)[ROOM_IDS[room]]["operations"]), 1)

    def test_four_recipient_seams_and_single_geometric_owner(self):
        graph = assemble(self.baseline["modules"])
        expected = {"living-a": ROOM_IDS["living"],
                    "living-b": ROOM_IDS["living"],
                    "a-bath": ROOM_IDS["bedroom-a"],
                    "b-bath": ROOM_IDS["bedroom-b"]}
        self.assertEqual({s.seam_id: s.owner for s in graph.seams}, expected)
        self.assertEqual(graph.neighbours(ROOM_IDS["living"]),
                         [ROOM_IDS["bedroom-a"], ROOM_IDS["bedroom-b"]])
        self.assertEqual(graph.neighbours(ROOM_IDS["bath"]),
                         [ROOM_IDS["bedroom-a"], ROOM_IDS["bedroom-b"]])
        self.assertEqual(assemble(list(reversed(self.baseline["modules"]))).seams, graph.seams)
        self.assertEqual(len([p for m in graph.modules.values() for p in m["ports"]
                              if p["kind"] == "doorway"]), 6)
        self.assertEqual(len([p for m in graph.modules.values() for p in m["ports"]
                              if p["kind"] == "shared-boundary"]), 2)

    def test_real_wall_cutouts_and_clearance(self):
        door_count, window_count = 0, 0
        for module in self.baseline["modules"]:
            for op in module["operations"]:
                if op["kind"] != "opening-cut":
                    continue
                wall = next(w for w in module["operations"]
                            if w["opId"] == op["targetWallOpId"])
                product = build_wall_with_openings(wall, [op])
                self.assertEqual(product["wall"]["topology"], "conforming-quad-voids")
                self.assertGreater(len(product["wall"]["faces"]), 4)
                self.assertEqual(len(product["inserts"]), 1)
                full_volume = 0.15 * wall["height"] * (4 if wall["opId"] != "wall-east"
                              else 3)
                self.assertLess(product["wall"]["volume"], full_volume)
                if op["openingType"] == "door":
                    door_count += 1
                    self.assertGreaterEqual(product["doorwayClearance"][0]["width"], 0.70)
                else:
                    window_count += 1
                    self.assertEqual(product["doorwayClearance"], [])
        self.assertEqual((door_count, window_count), (3, 1))

    def test_localized_revision_no_rewrite_of_other_modules(self):
        before, after = modules(self.baseline), modules(self.revised)
        self.assertEqual(set(before), set(after))
        changed = {mid for mid in before if canonical_hash(before[mid]) != canonical_hash(after[mid])}
        self.assertEqual(changed, {ROOM_IDS["bedroom-a"]})
        for mid in set(before) - changed:
            self.assertEqual(before[mid], after[mid])
            self.assertEqual(canonical_hash(before[mid]), canonical_hash(after[mid]))
        room = after[ROOM_IDS["bedroom-a"]]
        self.assertEqual(room["revision"], 2)
        self.assertEqual([o["width"] for o in room["operations"]
                          if o["opId"] == "exterior-window"], [1.2])
        self.assertEqual(assemble(self.baseline["modules"]).seams,
                         assemble(self.revised["modules"]).seams)


    def test_real_per_module_journal_revision_preserves_other_files(self):
        """BMB-010 persistence proof, not merely two regenerated JSON snapshots."""
        target = ROOM_IDS["bedroom-a"]
        before, after = modules(self.baseline), modules(self.revised)
        with tempfile.TemporaryDirectory(prefix="bmb026-journal-") as temp:
            store = JournalStore(temp)
            journal_paths = {}
            for mid, module in sorted(before.items()):
                self.assertEqual(store.create_module(mid), 0)
                result = store.apply(mid, 0, "bmb026-initial",
                                     [{"op": "add", "id": "source", "data": module}])
                self.assertEqual((result.revision, result.replayed), (1, False))
                journal_paths[mid] = (Path(temp) / "modules" /
                                      mid.replace("/", "__") / "journal.jsonl")
            preserved = {mid: (path.read_bytes(), path.stat().st_mtime_ns)
                         for mid, path in journal_paths.items() if mid != target}
            original_target = journal_paths[target].read_bytes()
            with self.assertRaises(StaleRevisionError):
                store.apply(target, 0, "bmb026-stale",
                            [{"op": "replace", "id": "source", "data": after[target]}])
            self.assertEqual(journal_paths[target].read_bytes(), original_target)
            actual = store.apply(target, 1, "bmb026-exterior-window",
                                 [{"op": "replace", "id": "source", "data": after[target]}])
            self.assertEqual((actual.revision, actual.replayed), (2, False))
            self.assertNotEqual(journal_paths[target].read_bytes(), original_target)
            reopened = JournalStore.open(temp)
            for mid, source in sorted(after.items()):
                revision, blocks = reopened.snapshot(mid)
                self.assertEqual(revision, 2 if mid == target else 1)
                self.assertEqual(blocks["source"], source)
                if mid != target:
                    file_path = journal_paths[mid]
                    self.assertEqual((file_path.read_bytes(), file_path.stat().st_mtime_ns),
                                     preserved[mid], "unrelated module file was rewritten")
            self.assertEqual(
                compile_document({"schemaVersion": "1.0.0",
                                  "modules": [reopened.snapshot(mid)[1]["source"]
                                              for mid in sorted(after)]}).sha256,
                compile_document(self.revised).sha256)
            replay = reopened.apply(target, 1, "bmb026-exterior-window",
                                    [{"op": "replace", "id": "source", "data": after[target]}])
            self.assertTrue(replay.replayed)
            self.assertEqual(replay.revision, 2)
            self.assertEqual({mid: journal_paths[mid].read_bytes() for mid in preserved},
                             {mid: data[0] for mid, data in preserved.items()})

    def test_both_states_compile_and_independent_builder_binary_read(self):
        for doc in (self.baseline, self.revised):
            compiled = compile_document(doc)
            parsed = independent_read(compiled.payload)
            self.assertEqual(compiled.sha256, hashlib.sha256(compiled.payload).hexdigest())
            self.assertGreater(parsed["counts"]["meshes"], 0)
            self.assertGreater(parsed["counts"]["faces"], 0)
            self.assertGreater(parsed["triangles"], 0)
            self.assertIn(17, parsed["sections"])
            self.assertEqual(compiled.coverage[0], parsed["counts"]["faces"])
            self.assertGreaterEqual(parsed["bounds"][3], 8)
            self.assertGreaterEqual(parsed["bounds"][4], 6)
        self.assertNotEqual(compile_document(self.baseline).sha256,
                            compile_document(self.revised).sha256)

    def test_shuffled_modules_and_operations_are_compiler_canonical(self):
        doc = copy.deepcopy(self.baseline)
        first = compile_document(doc).sha256
        doc["modules"].reverse()
        for m in doc["modules"]:
            m["operations"].reverse()
        self.assertEqual(first, compile_document(doc).sha256)

    def test_duplicate_seam_owner_fails_closed(self):
        doc = copy.deepcopy(self.baseline)
        a = modules(doc)
        other = a[ROOM_IDS["bedroom-a"]]
        other["ownedSeams"].append({
            "seamId": "living-a", "ownerModuleId": ROOM_IDS["bedroom-a"],
            "participants": [ROOM_IDS["living"], ROOM_IDS["bedroom-a"]],
            "surfaceOpId": "wall-east",
        })
        with self.assertRaises(DuplicateOwnershipError):
            assemble(doc["modules"])
        with self.assertRaises(CompileError):
            compile_document(doc)

    def test_misaligned_port_fails_closed(self):
        doc = copy.deepcopy(self.baseline)
        a = modules(doc)[ROOM_IDS["bath"]]
        port = next(p for p in a["ports"] if p["seamId"] == "a-bath")
        port["width"] += 0.05
        with self.assertRaises(AssemblyError):
            assemble(doc["modules"])
        with self.assertRaises(CompileError):
            compile_document(doc)

    def test_broken_revision_dependency_fails_closed(self):
        doc = copy.deepcopy(self.baseline)
        m = modules(doc)[ROOM_IDS["bath"]]
        m["dependencies"][0]["minRevision"] = 3
        with self.assertRaises(AssemblyError):
            assemble(doc["modules"])

    def test_unsupported_invalid_cutout_fails_closed(self):
        doc = copy.deepcopy(self.baseline)
        m = modules(doc)[ROOM_IDS["bedroom-a"]]
        next(o for o in m["operations"] if o["opId"] == "exterior-window")["width"] = 4
        with self.assertRaises(CompileError):
            compile_document(doc)

    def test_builder_receipt_never_promotes_native_consumer(self):
        _, _, receipt = evidence()
        self.assertEqual(receipt["roomCount"], 4)
        self.assertEqual(len(receipt["preservedModuleHashes"]), 4)
        self.assertEqual(receipt["gates"]["native_editor_e4_import"], "NOT_RUN")
        self.assertEqual(receipt["gates"]["owner_visual_acceptance"], "NOT_RUN")
        self.assertEqual(receipt["gates"]["builder_source_assembly_compiler_reader"], "PASS")

    def test_cli_writes_two_real_bomc_files_with_matching_receipt(self):
        with tempfile.TemporaryDirectory(prefix="bmb026-") as tmp:
            job = subprocess.run([sys.executable, "-m", "examples.bmb026_house",
                                  "--out-dir", tmp], cwd=ROOT,
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(job.returncode, 0, job.stdout + job.stderr)
            receipt = json.loads((Path(tmp) / "receipt.json").read_text())
            for state in ("baseline", "revised"):
                payload = (Path(tmp) / f"{state}.bomc").read_bytes()
                source = json.loads((Path(tmp) / f"{state}.json").read_text())
                independent_read(payload)
                self.assertEqual(hashlib.sha256(payload).hexdigest(),
                                 receipt["outputs"][state]["sha256"])
                self.assertEqual(compile_document(source).payload, payload)

    def test_repeated_cold_subprocess_compilation_identical_sha(self):
        with tempfile.TemporaryDirectory(prefix="bmb026-cold-") as tmp:
            source = Path(tmp) / "house.json"
            source.write_text(json.dumps(self.baseline, sort_keys=True), encoding="utf-8")
            digests = []
            for attempt in range(2):
                destination = Path(tmp) / f"attempt-{attempt}.bomc"
                job = subprocess.run([sys.executable, "-m", "bomc.compiler.graph_to_bomc",
                                      "--input", str(source), "--output", str(destination)],
                                     cwd=ROOT, capture_output=True, text=True, timeout=120)
                self.assertEqual(job.returncode, 0, job.stdout + job.stderr)
                digests.append(hashlib.sha256(destination.read_bytes()).hexdigest())
            self.assertEqual(digests[0], digests[1])


if __name__ == "__main__":
    unittest.main()
