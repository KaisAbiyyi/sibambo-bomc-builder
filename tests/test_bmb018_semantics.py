"""BMB-018: schema, semantic references, side materials and strict JSON readback."""
import copy
import json
import pathlib
import unittest

from jsonschema import Draft202012Validator
from core.geometry.semantics import (
    SemanticFaceError, inspect_semantic_faces, with_semantic_faces,
    encode_semantic_module, decode_semantic_module,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class SemanticFaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load("schemas/module-ir-v1.schema.json")
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def setUp(self):
        self.envelope = load("examples/module-ir-semantic-faces.json")
        self.module = self.envelope["modules"][0]

    def test_valid_three_roles_and_both_sides_roundtrip(self):
        self.validator.validate(self.envelope)
        original = copy.deepcopy(self.module)
        encoded = encode_semantic_module(self.module)
        decoded = decode_semantic_module(encoded)
        self.assertEqual(decoded, original)
        self.assertEqual(self.module, original)
        indexed = {f["role"]: f for f in inspect_semantic_faces(decoded)}
        self.assertEqual(set(indexed), {"floor", "wall", "roof"})
        self.assertEqual((indexed["wall"]["frontMaterialId"], indexed["wall"]["backMaterialId"]),
                         ("plaster", "brick"))
        self.assertEqual(indexed["floor"]["label"], "Living floor top")
        self.assertEqual(indexed["roof"]["backMaterialId"], "concrete")

    def test_deterministic_face_order_and_pure_copy(self):
        shuffled = copy.deepcopy(self.module)
        shuffled["semanticFaces"].reverse()
        self.assertEqual(encode_semantic_module(shuffled), encode_semantic_module(self.module))
        original = copy.deepcopy(self.module)
        changed = with_semantic_faces(self.module, list(reversed(self.module["semanticFaces"])))
        self.assertEqual(self.module, original)
        self.assertEqual(changed["semanticFaces"][0]["faceId"], "floor-top")
        changed["semanticFaces"][0]["label"] = "Changed"
        self.assertEqual(original["semanticFaces"][0]["label"], "Living floor top")

    def test_legacy_module_without_annotations_is_unchanged(self):
        module = load("examples/module-ir-two-rooms.json")["modules"][0]
        self.assertEqual(inspect_semantic_faces(module), [])
        self.assertEqual(decode_semantic_module(encode_semantic_module(module)), module)
        self.assertNotIn("semanticFaces", module)

    def test_schema_rejects_invalid_face_fields(self):
        for edit in (
            lambda f: f.update(extra="not-allowed"),
            lambda f: f.update(role="painting"),
            lambda f: f.update(label=""),
            lambda f: f.update(faceId="../outside"),
            lambda f: f.pop("backMaterialId"),
        ):
            with self.subTest(edit=edit):
                doc = copy.deepcopy(self.envelope)
                edit(doc["modules"][0]["semanticFaces"][0])
                self.assertFalse(self.validator.is_valid(doc))

    def assert_semantic_rejected(self, mutate):
        doc = copy.deepcopy(self.module)
        mutate(doc)
        with self.assertRaises(SemanticFaceError):
            encode_semantic_module(doc)

    def test_unknown_references_and_duplicate_ids_fail_closed(self):
        for action in (
            lambda d: d["semanticFaces"][0].update(frontMaterialId="missing"),
            lambda d: d["semanticFaces"][0].update(backMaterialId="missing"),
            lambda d: d["semanticFaces"][0].update(ownerOpId="missing"),
            lambda d: d["semanticFaces"].append(copy.deepcopy(d["semanticFaces"][0])),
            lambda d: d["materials"].append(copy.deepcopy(d["materials"][0])),
            lambda d: d["operations"].append(copy.deepcopy(d["operations"][0])),
        ):
            with self.subTest(action=action):
                self.assert_semantic_rejected(action)

    def test_role_owner_mismatch_and_opening_ref_fail_closed(self):
        self.assert_semantic_rejected(lambda d: d["semanticFaces"][0].update(role="roof"))
        self.assert_semantic_rejected(lambda d: d["operations"][1].update(role="floor"))
        self.assert_semantic_rejected(lambda d: d["semanticFaces"][2].update(ownerOpId="floor-plate"))
        def opening(d):
            d["operations"].append(dict(kind="opening-cut", opId="door-cut",
                                        targetWallOpId="north-wall", offset=0.2,
                                        width=0.9, height=2.0, sillHeight=0,
                                        openingType="door"))
            d["semanticFaces"][0]["ownerOpId"] = "door-cut"
        self.assert_semantic_rejected(opening)

    def test_bad_labels_and_unexpected_fields(self):
        for text in (" with-space", "trailing ", "bad\nline", "\ud800", "", "x" * 161):
            with self.subTest(text=repr(text)):
                self.assert_semantic_rejected(lambda d: d["semanticFaces"][0].update(label=text))
        self.assert_semantic_rejected(lambda d: d["semanticFaces"][0].update(secret=1))

    def test_strict_decode_duplicates_nonfinite_and_bytes_budget(self):
        payload = encode_semantic_module(self.module)
        for corrupt in (b'{"materials":[],"materials":[],"operations":[]}',
                        b'{"materials":[],"operations":[],"semanticFaces":[],"x":NaN}',
                        b'{"materials":[],"operations":[],"semanticFaces":[],"x":1e999}',
                        b"\xff\xfe",
                        b" " * (2 * 1024 * 1024 + 1),
                        b"[]"):
            with self.subTest(corrupt=corrupt[:40]):
                with self.assertRaises(SemanticFaceError):
                    decode_semantic_module(corrupt)
        altered = payload.replace(b'"plaster"', b'"missing"', 1)
        with self.assertRaises(SemanticFaceError):
            decode_semantic_module(altered)

    def test_reference_table_budgets_fail_closed(self):
        self.assert_semantic_rejected(lambda d: d["materials"].extend(
            {"materialId": "mat-" + str(i)} for i in range(2001)))
        self.assert_semantic_rejected(lambda d: d["operations"].extend(
            {"opId": "op-" + str(i)} for i in range(10_001)))

    def test_nan_in_other_fields_is_not_serialized(self):
        self.assert_semantic_rejected(lambda d: d["materials"][0].update(opacity=float("nan")))

    def test_non_materialized_roof_is_documented_not_binary(self):
        roof = [op for op in self.module["operations"] if op["opId"] == "roof-plate"][0]
        self.assertEqual((roof["kind"], roof["role"]), ("floor-slab", "roof"))
        self.assertFalse(any("mesh" in op for op in self.module["operations"]))


if __name__ == "__main__":
    unittest.main()
