import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MATRIX = ROOT / "compatibility" / "bomc-1.2-matrix.json"

class TestMatrix(unittest.TestCase):
    def test_pairs_and_evidence(self):
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
        profiles = matrix["profiles"]
        ids = set()
        passed = set()
        for row in matrix["cases"]:
            self.assertNotIn(row["id"], ids)
            ids.add(row["id"])
            self.assertIn(row["reader"], profiles)
            self.assertIn(row["writer"], profiles | {"builderWriter12": {}})
            self.assertIn(row["status"], matrix["statusLegend"])
            if row["status"] == "PASS":
                passed.add(row["id"])
                self.assertEqual(row["evidence"]["repo"], "KaisAbiyyi/sibambo-editor")
                self.assertIn("/actions/runs/", row["evidence"]["ciRun"])
                self.assertEqual(len(row["evidence"]["testedPrHeadSha"]), 40)
        self.assertEqual(len(ids), 8)
        self.assertEqual(passed, {"EDITOR12_EDITOR_WEB_EDIT", "EDITOR12_EDITOR_E4_VIEW"})
        checks = matrix["actualConsumerChecks"]
        self.assertEqual({entry["repo"] for entry in checks}, {"KaisAbiyyi/sibambo-editor", "KaisAbiyyi/sibambo-model-eval"})
        self.assertTrue(all(entry["result"] == "PASS" and entry["failed"] == 0 for entry in checks))

    def test_section_gate(self):
        m = json.loads(MATRIX.read_text(encoding="utf-8"))["profiles"]
        self.assertEqual(set(m["rubyProducer12"]["required"]), {1,2,11,12,13,17,20})
        self.assertEqual(set(m["rubyDecoder12"]["required"]), {1,2,11,12,13,17})
        self.assertIn(241, m["editorWebCore12"]["required"])
        self.assertNotIn(241, m["rubyProducer12"]["required"] + m["rubyProducer12"]["optional"])

    def test_negative_vectors_distinct(self):
        m = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertEqual(len({x["id"] for x in m["negatives"]}),len(m["negatives"]))
        self.assertTrue(all(x["status"] != "PASS" for x in m["negatives"]))

if __name__ == "__main__":
    unittest.main()
