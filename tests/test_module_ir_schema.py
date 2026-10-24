import copy
import json
import pathlib
import unittest
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[1]
def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

class ModuleIrSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load("schemas/module-ir-v1.schema.json")
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)
        cls.example = load("examples/module-ir-two-rooms.json")

    def assert_rejected(self, changed):
        self.assertFalse(self.validator.is_valid(changed), "malformed module IR accepted")

    def test_synthetic_two_modules(self):
        self.validator.validate(self.example)
        self.assertEqual(len(self.example["modules"]), 2)

    def test_unknown_version(self):
        invalid = copy.deepcopy(self.example)
        invalid["schemaVersion"] = "2.0.0"
        self.assert_rejected(invalid)

    def test_unknown_operation(self):
        invalid = copy.deepcopy(self.example)
        invalid["modules"][0]["operations"][0]["kind"] = "magic-wall"
        self.assert_rejected(invalid)

    def test_negative_thickness(self):
        invalid = copy.deepcopy(self.example)
        invalid["modules"][0]["operations"][0]["thickness"] = -0.1
        self.assert_rejected(invalid)

    def test_affine_bottom_row(self):
        invalid = copy.deepcopy(self.example)
        invalid["modules"][1]["localFrame"]["transform"][15] = 2
        self.assert_rejected(invalid)

    def test_missing_peer(self):
        invalid = copy.deepcopy(self.example)
        del invalid["modules"][0]["ports"][0]["peer"]
        self.assert_rejected(invalid)

    def test_no_unknown_fields(self):
        invalid = copy.deepcopy(self.example)
        invalid["modules"][0]["operations"][0]["secretBinarySection241"] = "opaque"
        self.assert_rejected(invalid)

    def test_module_id_namespace(self):
        invalid = copy.deepcopy(self.example)
        invalid["modules"][0]["moduleId"] = "../unsafe"
        self.assert_rejected(invalid)

if __name__ == "__main__":
    unittest.main()
