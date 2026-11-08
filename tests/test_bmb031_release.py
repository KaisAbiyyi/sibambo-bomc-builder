"""BMB-031: fail-closed packaging, evidence and owner-authorization regression tests."""
import copy
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.release_readiness import MANDATORY, audit

HEAD = "a" * 40


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.zip_name = "bomc-builder-foundation-beta-0.1.0-beta.0-" + HEAD[:12] + ".zip"
        documents = ["README.md", "LICENSE", "AGENTS.md", "docs/LICENSE-IP-FIXTURE-POLICY.md",
                     "docs/BMB-031-FOUNDATION-BETA.md", "docs/BMB-031-PROVENANCE.md",
                     "docs/BMB-031-OWNER-HANDOFF.md"]
        for name in documents + ["test.txt"]:
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("GNU GENERAL PUBLIC LICENSE Version 3 GPL-3.0 synthetic fixtures and acceptance\n"
                            if name == "LICENSE" or "POLICY" in name else "synthetic test file " * 3,
                            encoding="utf-8")
        license_meta = {"project_spdx": "GPL-3.0-only", "fixtures": "SYNTHETIC_ONLY",
                        "clean_room": "POLICY_ONLY_NOT_INDEPENDENTLY_CERTIFIED",
                        "transitive_dependency_audit": "NOT_RUN", "historical_source_ip_audit": "NOT_RUN"}
        runtime = {"python": "3.12", "packages": [{"name": "jsonschema", "version": "4.23.0",
                                                   "license": "MIT"}]}
        self.plan = {"schema_version": "bmb-foundation-beta-plan-v1", "target": "Foundation Beta",
                     "version": "0.1.0-beta.0", "version_status": "PROVISIONAL_OWNER_APPROVAL_REQUIRED",
                     "runtime": runtime, "license": license_meta,
                     "source": {"baseline_main_sha": HEAD}, "required_documents": documents,
                     "publication": {"approved": False, "published": False}}
        self.ledger = {"schema_version": "bmb-release-evidence-v1",
                       "gates": [{"id": key, "status": "NOT_RUN", "mandatory": True,
                                  "limitation": "intentionally not run", "evidence": None}
                                 for key in sorted(MANDATORY)],
                       "owner_approvals": {key: False for key in (
                           "scope_and_exclusions", "integration_merges", "native_acceptance",
                           "version_and_tag", "publication")},
                       "authorized_exclusions": []}
        info = zipfile.ZipInfo("test.txt", date_time=(1980, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_STORED
        self.archive = self.root / self.zip_name
        with zipfile.ZipFile(self.archive, "w") as output:
            output.writestr(info, (self.root / "test.txt").read_bytes())
        data = self.archive.read_bytes()
        self.manifest = {"schema_version": "bmb-foundation-beta-manifest-v1",
                         "approval": "NOT_APPROVED", "source_sha": HEAD,
                         "source_tree_sha": HEAD, "baseline_main_sha": HEAD,
                         "license": license_meta, "runtime": runtime,
                         "artifact": {"name": self.zip_name, "sha256": digest(data), "bytes": len(data)},
                         "files": [{"path": "test.txt", "sha256": digest((self.root / "test.txt").read_bytes()),
                                    "bytes": (self.root / "test.txt").stat().st_size}]}

    def check(self):
        return audit(self.plan, self.ledger, self.manifest, self.root, self.root, HEAD)

    def test_packaging_ready_is_not_release_approval(self):
        result = self.check()
        self.assertTrue(result["packagingReady"], result["packagingErrors"])
        self.assertFalse(result["releaseApproved"])
        self.assertIn("windows_native_security: NOT_RUN", result["releaseBlockers"])

    def test_missing_mandatory_evidence_is_blocking(self):
        self.ledger["gates"] = self.ledger["gates"][1:]
        result = self.check()
        self.assertFalse(result["packagingReady"])
        self.assertTrue(any("missing mandatory" in item for item in result["packagingErrors"]))

    def test_unverified_pass_cannot_promote_not_run(self):
        self.ledger["gates"][0]["status"] = "PASS"
        result = self.check()
        self.assertFalse(result["packagingReady"])
        self.assertTrue(any("PASS without evidence" in x for x in result["packagingErrors"]))

    def test_invalid_pass_source_sha_is_blocked(self):
        gate = self.ledger["gates"][0]
        gate["status"] = "PASS"
        gate["evidence"] = {"source_sha": "0" * 40,
                            "pr_url": "https://github.com/KaisAbiyyi/sibambo-bomc-builder/pull/55",
                            "workflow_run_url": "https://github.com/KaisAbiyyi/sibambo-bomc-builder/actions/runs/123",
                            "scope": "synthetic"}
        self.assertTrue(any("invalid source SHA" in x for x in self.check()["packagingErrors"]))

    def test_artifact_digest_must_be_real(self):
        self.manifest["artifact"]["sha256"] = "f" * 64
        self.assertFalse(self.check()["packagingReady"])

    def test_source_sha_mismatch_is_blocking(self):
        self.manifest["source_sha"] = "b" * 40
        self.assertFalse(self.check()["packagingReady"])

    def test_source_tree_mismatch_is_blocking(self):
        self.manifest["source_tree_sha"] = "b" * 40
        result = audit(self.plan, self.ledger, self.manifest, self.root, self.root, HEAD, HEAD)
        self.assertFalse(result["packagingReady"])
        self.assertTrue(any("tree SHA" in issue for issue in result["packagingErrors"]))

    def test_approval_flags_without_owner_proof_are_not_authorization(self):
        self.ledger["owner_approvals"] = {key: True for key in self.ledger["owner_approvals"]}
        result = self.check()
        self.assertFalse(result["releaseApproved"])
        self.assertTrue(any("authorization evidence absent" in x for x in result["releaseBlockers"]))

    def test_incomplete_owner_approval(self):
        self.ledger["owner_approvals"]["publication"] = True
        result = self.check()
        self.assertFalse(result["releaseApproved"])
        self.assertTrue(any("owner approvals incomplete" in x for x in result["releaseBlockers"]))

    def test_unapproved_exclusion_cannot_elevate_status(self):
        self.ledger["gates"][0]["status"] = "OUT_OF_SCOPE"
        self.ledger["authorized_exclusions"] = [
            {"gate_id": self.ledger["gates"][0]["id"], "approved_by_owner": False,
             "reason": "synthetic test only"}]
        self.assertTrue(any("unapproved exclusion" in x for x in self.check()["releaseBlockers"]))

    def test_unsupported_status_fails(self):
        self.ledger["gates"][0]["status"] = "DONE"
        self.assertFalse(self.check()["packagingReady"])

    def test_missing_document_fails(self):
        (self.root / "docs/BMB-031-OWNER-HANDOFF.md").unlink()
        self.assertFalse(self.check()["packagingReady"])


if __name__ == "__main__":
    unittest.main()
