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
        for row in matrix["cases"]:
            self.assertNotIn(row["id"], ids)
            ids.add(row["id"])
            self.assertIn(row["reader"], profiles)
            self.assertIn(row["writer"], profiles | {"builderWriter12": {}})
            self.assertIn(row["status"], matrix["statusLegend"])
            self.assertNotEqual(row["status"], "PASS")
        self.assertEqual(len(ids), 8)

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
