"""Contract-lint positives and adversarial negatives for the BMB-004 synthetic fixture."""
import copy
import json
import unittest
from pathlib import Path

from scripts.validate_bmb004_baseline import validate

FIXTURE = json.loads((Path(__file__).resolve().parents[1] /
                     "benchmarks" / "agent-baseline-v0.json").read_text(encoding="utf-8"))


class BaselineContractTests(unittest.TestCase):
    def test_nominal_synthetic_fixture(self):
        validate(FIXTURE)

    def assert_rejects(self, mutate):
        fixture = copy.deepcopy(FIXTURE)
        mutate(fixture)
        with self.assertRaises(ValueError):
            validate(fixture)

    def test_duplicate_step_id_rejected(self):
        self.assert_rejects(lambda x: x["script"][1].update(step=1))

    def test_untrusted_command_tool_rejected(self):
        self.assert_rejects(lambda x: x["script"][0].update(tool="execute_shell"))

    def test_duplicate_room_id_rejected(self):
        self.assert_rejects(lambda x: x["rooms"][1].update(id="house/f1/living"))

    def test_different_tool_cannot_reuse_idempotency_key(self):
        self.assert_rejects(lambda x: x["script"][7].update(key="create-house-v0"))

    def test_replay_requires_prior_write(self):
        self.assert_rejects(lambda x: x["script"][2].update(key="never-seen-key"))

    def test_missing_revision_conflict_rejected(self):
        self.assert_rejects(lambda x: x["script"][6].update(expected="PASS"))

    def test_missing_independent_import_rejected(self):
        self.assert_rejects(lambda x: x["script"][-1].update(tool="bomc_inspect"))

    def test_fake_evidence_rejected(self):
        self.assert_rejects(lambda x: x["initial_evidence"].update(recorded_tool_calls=12))

    def test_excessive_or_nonfinite_dimensions_rejected(self):
        self.assert_rejects(lambda x: x["door"].update(final_clear_width_m=float("inf")))

    def test_non_synthetic_provenance_rejected(self):
        self.assert_rejects(lambda x: x.update(kind="private-model-derived"))

    def test_trial_count_drift_rejected(self):
        self.assert_rejects(lambda x: x["trial_policy"].update(cold_trials=1))


if __name__ == "__main__":
    unittest.main()
