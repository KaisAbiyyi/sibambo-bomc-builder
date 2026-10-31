"""BMB-018: synthetic authored solid materials, face labels and roundtrips."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.geometry.semantics import (SemanticFaceError, encode_authored_module,
                                     decode_authored_module, validate_module_faces)

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "examples/module-ir-two-rooms.json").read_text(
    encoding="utf-8"))["modules"][0]


def sample():
    m = copy.deepcopy(BASE)
    m["operations"].append({
        "kind": "floor-slab", "opId": "flat-roof", "role": "roof",
        "footprint": [[0, 0], [4, 0], [4, 3], [0, 3]],
        "thickness": 0.12, "elevation": 2.8})
    m["materials"].extend([
        {"materialId": "brick", "rgba": [192, 77, 44, 255],
         "opacity": 1, "semanticRole": "wall"},
        {"materialId": "membrane", "rgba": [60, 64, 72, 255],
         "opacity": .98, "semanticRole": "roof"},
        {"materialId": "substrate", "rgba": [165, 160, 152, 255],
         "opacity": 1, "semanticRole": "roof"}])
    m["faceAnnotations"] = [
        {"opId": "east-wall", "faceKey": "front-0", "role": "wall",
         "frontMaterialId": "brick", "backMaterialId": "plaster",
         "label": "Exterior façade"},
        {"opId": "floor-1", "faceKey": "top", "role": "floor",
         "frontMaterialId": "concrete", "backMaterialId": "concrete",
         "label": "Living floor"},
        {"opId": "flat-roof", "faceKey": "top", "role": "roof",
         "frontMaterialId": "membrane", "backMaterialId": "substrate",
         "label": "Flat roof"}]
    return m


class FaceSemanticsTests(unittest.TestCase):
    def rejects(self, change):
        m = sample()
        change(m)
        before = copy.deepcopy(m)
        with self.assertRaises(SemanticFaceError):
            encode_authored_module(m)
        self.assertEqual(m, before)

    def test_all_roles_and_two_sides_roundtrip(self):
        m = sample()
        before = copy.deepcopy(m)
        payload = encode_authored_module(m)
        recovered = decode_authored_module(payload)
        self.assertEqual(m, before)
        self.assertEqual(encode_authored_module(recovered), payload)
        faces = validate_module_faces(recovered)
        self.assertEqual({f["role"] for f in faces}, {"wall", "floor", "roof"})
        wall = next(f for f in faces if f["role"] == "wall")
        self.assertEqual(wall["label"], "Exterior façade")
        self.assertEqual(wall["front"]["rgba"], [192, 77, 44, 255])
        self.assertEqual(wall["back"]["rgba"], [245, 244, 242, 255])
        roof = next(f for f in faces if f["role"] == "roof")
        self.assertEqual(roof["front"]["opacity"], .98)
        self.assertNotEqual(roof["front"]["materialId"], roof["back"]["materialId"])

    def test_order_independent(self):
        a = sample()
        b = copy.deepcopy(a)
        b["faceAnnotations"].reverse()
        self.assertEqual(encode_authored_module(a), encode_authored_module(b))

    def test_legacy_compatible(self):
        self.assertEqual(validate_module_faces(BASE), ())
        self.assertEqual(decode_authored_module(encode_authored_module(BASE))
                         ["moduleId"], BASE["moduleId"])

    def test_duplicate_face(self):
        self.rejects(lambda m: m["faceAnnotations"].append(
            copy.deepcopy(m["faceAnnotations"][0])))

    def test_missing_material(self):
        for side in ("front", "back"):
            with self.subTest(side=side):
                self.rejects(lambda m: m["faceAnnotations"][0].__setitem__(
                    side + "MaterialId", "absent"))

    def test_missing_or_non_solid_operation(self):
        self.rejects(lambda m: m["faceAnnotations"][0].update(opId="absent"))
        self.rejects(lambda m: m["faceAnnotations"][0].update(opId="door-1"))

    def test_mismatched_semantic_role(self):
        self.rejects(lambda m: m["faceAnnotations"][0].update(role="roof"))
        self.rejects(lambda m: m["faceAnnotations"][2].update(role="floor"))
        self.rejects(lambda m: m["materials"][-1].update(semanticRole="wall"))

    def test_bounded_face_keys(self):
        for key in ("front-1", "front-00", "side-100", "../front", "end-0"):
            with self.subTest(key=key):
                self.rejects(lambda m: m["faceAnnotations"][0].update(faceKey=key))
        self.rejects(lambda m: m["faceAnnotations"][1].update(faceKey="side-4"))

    def test_reject_bad_labels(self):
        for label in ("", "   ", "bad\nlabel", "\ud800"):
            with self.subTest(label=repr(label)):
                self.rejects(lambda m: m["faceAnnotations"][0].update(label=label))

    def test_reject_duplicates(self):
        self.rejects(lambda m: m["materials"].append(copy.deepcopy(m["materials"][0])))
        self.rejects(lambda m: m["operations"].append(copy.deepcopy(m["operations"][0])))

    def test_nonfinite(self):
        for number in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(number=str(number)):
                self.rejects(lambda m: m["materials"][0].__setitem__("opacity", number))

    def test_reject_fields_and_colors(self):
        self.rejects(lambda m: m["faceAnnotations"][0].update(secretField=1))
        self.rejects(lambda m: m["materials"][0].__setitem__(
            "rgba", [256, 0, 0, 255]))
        self.rejects(lambda m: m["faceAnnotations"][0].update(
            frontMaterialId="membrane"))

    def test_malformed_decode(self):
        good = encode_authored_module(sample())
        inputs = [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}',
                  b'\xff', b'[]', b'', b'{"schemaVersion":"0.0.0"}',
                  b'x' * 2_000_001,
                  good.replace(b'"revision":1',
                               b'"revision":1,"revision":1')]
        for payload in inputs:
            with self.subTest(payload=payload[:25]):
                with self.assertRaises(SemanticFaceError):
                    decode_authored_module(payload)

    def test_strict_payload_type(self):
        with self.assertRaises(SemanticFaceError):
            decode_authored_module("not bytes")


if __name__ == "__main__":
    unittest.main()
