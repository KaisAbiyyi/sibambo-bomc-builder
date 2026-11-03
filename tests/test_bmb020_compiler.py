"""BMB-020 synthetic compiler tests; no private asset or local owner gate."""
import copy
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bomc.adapter.writer_v12 import HEADER, ENTRY  # noqa: E402
from bomc.compiler.graph_to_bomc import (  # noqa: E402
    CompileError, compile_document, compile_definition_graph, load_document)
from core.graph import dag  # noqa: E402
from tools.bomc_fixture_harness import inspect_container  # noqa: E402


def module(mid="house/level/a", parent="house/level", transform=None):
    return {
        "schemaVersion": "1.0.0", "moduleId": mid, "parentId": parent,
        "revision": 1,
        "localFrame": {"unit": "m", "handedness": "right", "upAxis": "+Z",
                       "forwardAxis": "+Y", "transform": list(transform or dag.IDENTITY)},
        "bounds": {"min": [0, 0, 0], "max": [0, 0, 0]},
        "operations": [], "materials": [], "ports": [], "ownedSeams": [],
        "dependencies": [],
        "provenance": {"origin": "synthetic", "generator": "bmb020-test"},
    }


def envelope(*modules):
    return {"schemaVersion": "1.0.0", "modules": list(modules)}


def section(result, ident):
    inspect_container(result.payload)
    for index in range(HEADER.unpack_from(result.payload)[5]):
        row = ENTRY.unpack_from(result.payload, HEADER.size + index * ENTRY.size)
        if row[0] == ident:
            return row, result.payload[row[3]:row[3] + row[4]]
    raise AssertionError("section not found")


class CompilerTests(unittest.TestCase):
    def test_canonical_permutation_group_dedup_and_affine(self):
        a = module()
        b = module("house/level/b", transform=dag.translation(2.5, -4, 1))
        c = module("house/level/c", parent=a["moduleId"],
                   transform=dag.shear_xy(0.125))
        original = envelope(b, c, a)
        snapshot = copy.deepcopy(original)
        first = compile_document(original)
        second = compile_document(envelope(a, b, c))
        self.assertEqual(original, snapshot)
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.node_count, 5)  # root, external group, 3 modules
        self.assertEqual(first.string_count, 5)
        self.assertEqual(first.section_ids, (1, 2, 11, 12, 13, 17, 20))
        self.assertEqual(first.coverage, (0,) * 6)
        self.assertEqual(section(first, 17)[1], bytes(24))
        transforms = section(first, 13)[1]
        matrices = [struct.unpack_from("<12d", transforms, 12 + 96 * i)
                    for i in range(first.node_count)]
        self.assertIn((1, 0, 0, 0, 1, 0, 0, 0, 1, 2.5, -4, 1), matrices)
        self.assertIn((1, 0, 0, 0.125, 1, 0, 0, 0, 1, 0, 0, 0), matrices)
        self.assertFalse(first.receipt()["geometrySemanticsValid"])

    def test_nested_parent_mirror_and_dag_shared_definition(self):
        parent = module("house/level", parent=None, transform=dag.mirror("x"))
        child = module("house/level/a", parent="house/level")
        self.assertEqual(compile_document(envelope(child, parent)).node_count, 3)

        def build(reverse=False):
            graph = dag.DefinitionGraph()
            graph.add_definition("house")
            graph.add_definition("room")
            items = [("west", dag.translation(-2, 0, 0)),
                     ("east", dag.translation(2, 0, 0))]
            for name, matrix in reversed(items) if reverse else items:
                graph.add_instance("house", name, "room", matrix)
            return graph

        left = compile_definition_graph(build(), "house")
        right = compile_definition_graph(build(True), "house")
        self.assertEqual(left.payload, right.payload)
        self.assertEqual(left.node_count, 3)
        self.assertEqual(left.string_count, 2)

    def test_two_independent_cold_processes_byte_and_sha_equal(self):
        doc = envelope(module(), module("house/level/b", transform=dag.mirror("x")))
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "source.json"
            inp.write_text(json.dumps(doc), encoding="utf-8")
            result = []
            for i in range(2):
                out = Path(tmp) / f"out-{i}.bomc"
                process = subprocess.run([
                    sys.executable, "-m", "bomc.compiler.graph_to_bomc",
                    "--input", str(inp), "--output", str(out),
                ], cwd=ROOT, capture_output=True, text=True, check=True)
                result.append((json.loads(process.stdout), out.read_bytes()))
            self.assertEqual(result[0], result[1])
            receipt, payload = result[0]
            self.assertEqual(receipt["sha256"], hashlib.sha256(payload).hexdigest())
            inspect_container(payload)
            self.assertEqual(receipt["coverage"], [0] * 6)

    def test_reject_malformed_semantics_and_source_features_explicitly(self):
        for key in ("operations", "materials", "ports", "ownedSeams", "faceAnnotations"):
            with self.subTest(key=key):
                item = module()
                item[key] = [{"invalid": "never silently discard"}]
                with self.assertRaisesRegex(CompileError, "schema|invalid|port|seam|nonempty|source"):
                    compile_document(envelope(item))

    def test_invalid_models_fail_closed(self):
        source = envelope(module())
        mutations = (
            lambda d: d.update(schemaVersion="1.1.0"),
            lambda d: d.update(unknown=True),
            lambda d: d["modules"][0].update(unknown=True),
            lambda d: d["modules"][0]["bounds"]["max"].__setitem__(0, 1),
            lambda d: d["modules"][0]["localFrame"].update(unit="mm"),
            lambda d: d["modules"][0]["localFrame"]["transform"].__setitem__(0, 0),
            lambda d: d["modules"][0].update(parentId="house/level/a"),
            lambda d: d["modules"][0].update(materials=None),
            lambda d: d["modules"].append(copy.deepcopy(d["modules"][0])),
        )
        for mutation in mutations:
            doc = copy.deepcopy(source)
            mutation(doc)
            with self.assertRaises(CompileError):
                compile_document(doc)

    def test_budget_and_json_duplicate_rejection_no_output(self):
        with self.assertRaises(CompileError):
            compile_document(envelope(*(module(f"house/level/m-{i}") for i in range(128))))
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "bad.json", Path(tmp) / "bad.bomc"
            src.write_text('{"schemaVersion":"1.0.0","schemaVersion":"1.0.0","modules":[]}')
            with self.assertRaises(CompileError):
                load_document(src)
            run = subprocess.run([sys.executable, "-m",
                                  "bomc.compiler.graph_to_bomc",
                                  "--input", str(src), "--output", str(dst)],
                                 cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse(dst.exists())


if __name__ == "__main__":
    unittest.main()
