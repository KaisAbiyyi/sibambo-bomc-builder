import importlib.util
import pathlib
import json
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fixture_harness", ROOT / "tools/bomc_fixture_harness.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

class FixtureHarnessTests(unittest.TestCase):
    def test_deterministic_synthetic_containers(self):
        blobs, manifest = module.build_all()
        self.assertEqual(len(blobs), 6)
        ledger = json.loads((ROOT / "fixtures/container-only-reference-sha256.json").read_text(encoding="utf8"))
        self.assertEqual(ledger["qualification"], "CONTAINER_ONLY_NON_SEMANTIC")
        pinned = {item["name"]: item for item in ledger["cases"]}
        self.assertEqual(set(pinned), set(blobs))
        for row in manifest["cases"]:
            blob = blobs[row["name"]]
            self.assertEqual(blob, module.generate(row["name"]))
            self.assertEqual(row["sha256"], module.hashlib.sha256(blob).hexdigest())
            self.assertEqual(row["sha256"], pinned[row["name"]]["sha256"])
            self.assertEqual(row["byteSize"], pinned[row["name"]]["bytes"])
            self.assertEqual(len(module.inspect_container(blob)), row["sectionCount"])

    def test_reject_structural_corruption(self):
        for name, bad in module.corruptions(module.generate("floor")).items():
            with self.subTest(name=name):
                with self.assertRaises(module.InvalidBomc):
                    module.inspect_container(bad)

    def test_explicit_semantic_noncertification(self):
        _, manifest = module.build_all()
        for row in manifest["cases"]:
            self.assertEqual(row["scope"], "container-only")
            self.assertFalse(row["semanticBomcTablesValid"])
            self.assertEqual(row["independentConsumerStatus"], "NOT_RUN")

if __name__ == "__main__":
    unittest.main()
