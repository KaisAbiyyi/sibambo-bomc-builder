"""BMB-012 contract and adversarial synthetic validation tests."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.assembly import assemble
from core.graph import dag
from core.validator import validate_assembly, Diagnostic, ValidationReport

LIV, HALL = "house/floor-1/living", "house/floor-1/hall"


def example():
    return json.loads((ROOT / "examples/module-ir-two-rooms.json").read_text())["modules"]


def find(mods, mid):
    return next(m for m in mods if m["moduleId"] == mid)


def standalone(mid, at=(0, 0, 0), turn=0):
    return {"schemaVersion": "1.0.0", "moduleId": mid, "parentId": None, "revision": 0,
            "localFrame": {"unit": "m", "handedness": "right", "upAxis": "+Z", "forwardAxis": "+Y",
                           "transform": list(dag.compose(dag.translation(*at), dag.rotation_z(turn)))},
            "bounds": {"min": [-1, -1, -1], "max": [1, 1, 1]},
            "operations": [{"kind": "floor-slab", "opId": "floor", "footprint":
                            [[-1, -1], [1, -1], [1, 1], [-1, 1]], "thickness": 0.1, "elevation": -1}],
            "materials": [], "ports": [], "ownedSeams": [], "dependencies": [],
            "provenance": {"origin": "synthetic"}}


class ValidationTests(unittest.TestCase):
    def codes(self, value):
        return {x.code for x in value.diagnostics}

    def test_sample_pass_and_serializable(self):
        r = validate_assembly(example())
        self.assertTrue(r.ok, r.to_dict())
        self.assertEqual(r.to_dict()["collisionModel"], "world-affine-module-bounds-SAT")
        json.dumps(r.to_dict())

    def test_assembly_or_raw_and_order_independent(self):
        mods = example()
        a = validate_assembly(mods)
        b = validate_assembly(assemble(list(reversed(mods))))
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertTrue(a.ok)

    def test_inputs_never_mutated(self):
        mods = example()
        before = copy.deepcopy(mods)
        validate_assembly(mods)
        self.assertEqual(mods, before)

    def test_material_reference_missing(self):
        mods = example()
        find(mods, LIV)["operations"][0]["materialId"] = "absent"
        r = validate_assembly(mods)
        self.assertFalse(r.ok)
        self.assertIn("MATERIAL_MISSING", self.codes(r))
        self.assertEqual(next(d.module_id for d in r.diagnostics if d.code == "MATERIAL_MISSING"), LIV)

    def test_duplicate_material_and_operation(self):
        mods = example()
        liv = find(mods, LIV)
        liv["materials"].append(copy.deepcopy(liv["materials"][0]))
        liv["operations"].append(copy.deepcopy(liv["operations"][0]))
        r = validate_assembly(mods)
        self.assertTrue({"MATERIAL_DUPLICATE", "OPERATION_DUPLICATE"}.issubset(self.codes(r)))

    def test_opening_target_missing(self):
        mods = example()
        find(mods, LIV)["operations"][2]["targetWallOpId"] = "other"
        self.assertIn("WALL_MISSING", self.codes(validate_assembly(mods)))

    def test_opening_outside_wall(self):
        mods = example()
        find(mods, LIV)["operations"][2]["offset"] = 2.5
        self.assertIn("OPENING_OUT_OF_WALL", self.codes(validate_assembly(mods)))
        find(mods, LIV)["operations"][2]["offset"] = 1
        find(mods, LIV)["operations"][2]["sillHeight"] = 2.5
        self.assertIn("OPENING_OUT_OF_WALL", self.codes(validate_assembly(mods)))

    def test_operation_outside_bounds(self):
        mods = example()
        find(mods, LIV)["operations"][0]["footprint"][0][0] = -0.5
        self.assertIn("OPERATION_OUT_OF_BOUNDS", self.codes(validate_assembly(mods)))

    def test_nonfinite_and_negative_bounds(self):
        mods = example()
        find(mods, LIV)["bounds"]["max"][0] = -1
        self.assertIn("BOUNDS_INVALID", self.codes(validate_assembly(mods)))
        find(mods, LIV)["bounds"]["max"][0] = float("nan")
        self.assertFalse(validate_assembly(mods).ok)

    def test_port_outside_module(self):
        mods = example()
        find(mods, LIV)["ports"][0]["localTransform"][7] = 9
        self.assertIn("PORT_OUT_OF_BOUNDS", self.codes(validate_assembly(mods)))

    def test_invalid_report_order_independent(self):
        mods = example()
        find(mods, HALL)["ports"][0]["peer"]["portId"] = "missing"
        first = validate_assembly(mods).to_dict()
        second = validate_assembly(list(reversed(mods))).to_dict()
        self.assertEqual(first, second)

    def test_unresolved_port_reciprocity(self):
        mods = example()
        find(mods, HALL)["ports"][0]["peer"]["portId"] = "missing"
        self.assertIn("PORT_UNRESOLVED", self.codes(validate_assembly(mods)))

    def test_unresolved_seam_owner(self):
        mods = example()
        find(mods, LIV)["ownedSeams"] = []
        self.assertIn("SEAM_UNRESOLVED", self.codes(validate_assembly(mods)))

    def test_duplicate_seam_owner(self):
        mods = example()
        hall = find(mods, HALL)
        hall["ownedSeams"] = [{"seamId": "east-shared", "ownerModuleId": HALL,
                               "participants": [LIV, HALL], "surfaceOpId": "floor-1"}]
        self.assertIn("SEAM_DUPLICATE_OWNER", self.codes(validate_assembly(mods)))

    def test_missing_dependency(self):
        mods = example()
        find(mods, HALL)["dependencies"][0]["moduleId"] = "house/missing"
        self.assertIn("DEPENDENCY_MISSING", self.codes(validate_assembly(mods)))

    def test_overlap_world_boxes(self):
        mods = [standalone("demo/one"), standalone("demo/two", (1, 0, 0))]
        r = validate_assembly(mods)
        self.assertIn("MODULE_BOUNDS_COLLISION", self.codes(r))
        issue = next(d for d in r.diagnostics if d.code == "MODULE_BOUNDS_COLLISION")
        self.assertEqual((issue.module_id, issue.related_module_id), ("demo/one", "demo/two"))

    def test_touching_allowed_and_tolerance(self):
        mods = [standalone("demo/one"), standalone("demo/two", (2, 0, 0))]
        self.assertTrue(validate_assembly(mods).ok)
        mods[1]["localFrame"]["transform"][3] = 1.9995
        self.assertTrue(validate_assembly(mods).ok)
        self.assertIn("MODULE_BOUNDS_COLLISION", self.codes(validate_assembly(mods, tolerance_m=0.0001)))

    def test_affine_sat_prevents_aabb_false_positive(self):
        mods = [standalone("demo/one", turn=45), standalone("demo/two", (2, 2, 0), turn=45)]
        self.assertTrue(validate_assembly(mods).ok)

    def test_rotated_and_sheared_overlap_detected(self):
        a = standalone("demo/one", turn=35)
        b = standalone("demo/two", (0.2, 0.2, 0), turn=-25)
        b["localFrame"]["transform"] = list(dag.compose(dag.translation(0.2, 0.2, 0), dag.shear_xy(0.5)))
        self.assertIn("MODULE_BOUNDS_COLLISION", self.codes(validate_assembly([a, b])))

    def test_container_no_collision(self):
        parent = standalone("demo/parent")
        parent["operations"] = []
        child = standalone("demo/child")
        child["parentId"] = "demo/parent"
        self.assertTrue(validate_assembly([parent, child]).ok)

    def test_invalid_tolerance_fails_closed(self):
        self.assertIn("CONFIG_INVALID", self.codes(validate_assembly(example(), tolerance_m=-1)))
        self.assertIn("CONFIG_INVALID", self.codes(validate_assembly(example(), tolerance_m=float("nan"))))
        self.assertIn("CONFIG_INVALID", self.codes(validate_assembly(example(), tolerance_m=True)))

    def test_corrupt_assembly_revalidated(self):
        a = assemble(example())
        a.modules[LIV]["operations"][0]["materialId"] = "absent"
        self.assertIn("MATERIAL_MISSING", self.codes(validate_assembly(a)))

    def test_strange_nested_input_never_raw_crash(self):
        mods = example()
        find(mods, LIV)["ports"][0]["peer"] = []
        self.assertFalse(validate_assembly(mods).ok)
        self.assertIn("PORT_UNRESOLVED", self.codes(validate_assembly(mods)))
        mods = example()
        mods[0]["bounds"]["min"] = [[], None, True]
        self.assertIn("BOUNDS_INVALID", self.codes(validate_assembly(mods)))


if __name__ == "__main__":
    unittest.main()
