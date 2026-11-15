#!/usr/bin/env python3
"""BMB-031 fail-closed release packaging and owner-approval gate (stdlib only).

PASS evidence must have a named exact source SHA, PR, workflow run and scope.
Historical passes do not certify a new release HEAD. No network/CI-status lookup
is performed here; external evidence must be independently verified at review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
STATUSES = frozenset({"PASS", "FAIL", "NOT_RUN", "BLOCKED", "OUT_OF_SCOPE"})
SHA = re.compile(r"[0-9a-f]{40}\Z")
MANDATORY = frozenset({
    "deterministic_compile", "builder_independent_reader", "bmb021_original_consumers",
    "bmb023_mcp_protocol", "bmb026_four_room_house", "bmb027_editor_consumer",
    "bmb028_synthetic_benchmark", "bmb028_four_room_baseline",
    "bmb029_optional_rooms_adapter", "bmb030_adversarial_qa",
    "bmb032_generator_contract", "original_model_eval", "windows_native_security",
    "live_provider_tokens", "real_rooms_detector", "real_generator_adoption",
    "license_chain_of_title", "owner_release_acceptance",
})
APPROVAL_KEYS = frozenset({
    "scope_and_exclusions", "integration_merges", "native_acceptance",
    "version_and_tag", "publication",
})


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("JSON root must be object: " + str(path))
    return value


def audit(plan: dict, ledger: dict, manifest: dict, root: Path, archive_dir: Path,
          current_sha: str, current_tree_sha: str | None = None,
          committed_source: Callable[[str], bytes] | None = None) -> dict:
    # Production passes a git-blob reader, avoiding Windows checkout CRLF
    # conversions; offline test cases inject controlled fixture file bytes.
    if committed_source is None:
        committed_source = lambda rel: (root / rel).read_bytes()
    errors: list[str] = []
    blockers: list[str] = []
    checked: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    require(plan.get("schema_version") == "bmb-foundation-beta-plan-v1", "plan schema mismatch")
    require(ledger.get("schema_version") == "bmb-release-evidence-v1", "ledger schema mismatch")
    require(manifest.get("schema_version") == "bmb-foundation-beta-manifest-v1", "manifest schema mismatch")
    require(plan.get("target") == "Foundation Beta", "unexpected target")
    require(plan.get("version_status") == "PROVISIONAL_OWNER_APPROVAL_REQUIRED",
            "release plan silently changed to approved")
    require(manifest.get("approval") == "NOT_APPROVED", "package must not claim owner approval")
    require(plan.get("publication", {}).get("approved") is False, "plan publication must be withheld")
    require(plan.get("publication", {}).get("published") is False, "package marked published")
    require(plan.get("runtime", {}).get("python") == "3.12", "Python 3.12 version pin missing")
    require(any(isinstance(d, dict) and d.get("name") == "jsonschema"
                and d.get("version") == "4.23.0" and bool(d.get("license"))
                for d in plan.get("runtime", {}).get("packages", [])),
            "pinned jsonschema runtime dependency/license missing")
    require(plan.get("license", {}).get("project_spdx") == "GPL-3.0-only", "GPL-3.0-only declaration missing")
    require(plan.get("license", {}).get("fixtures") == "SYNTHETIC_ONLY", "synthetic-only declaration missing")
    require(plan.get("license", {}).get("clean_room") == "POLICY_ONLY_NOT_INDEPENDENTLY_CERTIFIED",
            "clean-room certification must not be invented")
    require(manifest.get("license") == plan.get("license"), "manifest license declarations differ from plan")
    require(manifest.get("runtime") == plan.get("runtime"), "manifest dependency declarations differ from plan")
    require(manifest.get("source_sha") == current_sha and bool(SHA.fullmatch(current_sha)),
            "manifest source SHA differs from exact checkout HEAD")
    require(manifest.get("baseline_main_sha") == plan.get("source", {}).get("baseline_main_sha"),
            "baseline source SHA mismatch")
    require(bool(SHA.fullmatch(str(manifest.get("source_tree_sha", "")))), "invalid source tree SHA")
    if current_tree_sha is not None:
        require(manifest.get("source_tree_sha") == current_tree_sha,
                "manifest source tree SHA differs from exact checkout tree")

    for rel in plan.get("required_documents", []):
        path = root / rel
        require(path.is_file() and path.stat().st_size > 25, "missing/empty required document: " + rel)
    license_file = root / "LICENSE"
    policy = root / "docs/LICENSE-IP-FIXTURE-POLICY.md"
    require(license_file.is_file() and "GNU GENERAL PUBLIC LICENSE" in license_file.read_text(errors="replace")
            and "Version 3" in license_file.read_text(errors="replace"),
            "actual GPL-3.0 license text unverified")
    require(policy.is_file() and "GPL-3.0" in policy.read_text(errors="replace") and
            "synthetic" in policy.read_text(errors="replace").lower(),
            "BMB-003 license/fixture policy missing or inconsistent")

    seen = set()
    gates = ledger.get("gates")
    require(isinstance(gates, list), "gates must be a list")
    for item in gates if isinstance(gates, list) else []:
        if not isinstance(item, dict):
            errors.append("invalid gate object")
            continue
        gate_id, status = item.get("id"), item.get("status")
        if gate_id in seen:
            errors.append("duplicate gate: " + str(gate_id))
        seen.add(gate_id)
        require(gate_id in MANDATORY, "unexpected gate: " + str(gate_id))
        require(status in STATUSES, "unsupported gate status: " + str(gate_id))
        require(item.get("mandatory") is True, "required gate made optional: " + str(gate_id))
        require(bool(item.get("limitation")), "gate limitation/scope absent: " + str(gate_id))
        evidence = item.get("evidence")
        if status == "PASS":
            require(isinstance(evidence, dict), "PASS without evidence: " + str(gate_id))
            if isinstance(evidence, dict):
                sha = str(evidence.get("source_sha", ""))
                require(bool(SHA.fullmatch(sha)) and sha != "0" * 40,
                        "PASS with invalid source SHA: " + str(gate_id))
                require(bool(re.fullmatch(r"https://github\.com/[^/]+/[^/]+/pull/\d+",
                                          str(evidence.get("pr_url", "")))),
                        "PASS missing PR: " + str(gate_id))
                require(bool(re.fullmatch(r"https://github\.com/[^/]+/[^/]+/actions/runs/\d+",
                                          str(evidence.get("workflow_run_url", "")))),
                        "PASS missing workflow run: " + str(gate_id))
                require(bool(evidence.get("scope")), "PASS lacks evidenced scope: " + str(gate_id))
                if sha != current_sha:
                    checked.append(gate_id + ": historical " + sha + " (not current-head acceptance)")
                    blockers.append(gate_id + ": historical PASS needs current-head requalification")
        elif evidence is not None:
            require(False, "non-PASS gate has misleading evidence object: " + str(gate_id))
        if status != "PASS":
            if status == "OUT_OF_SCOPE":
                authorized = {x.get("gate_id") for x in ledger.get("authorized_exclusions", [])
                              if isinstance(x, dict) and x.get("approved_by_owner") is True
                              and x.get("reason")}
                if gate_id not in authorized:
                    blockers.append(str(gate_id) + ": unapproved exclusion")
            else:
                blockers.append(str(gate_id) + ": " + str(status))
    require(seen == MANDATORY, "missing mandatory acceptance gates: " +
            ", ".join(sorted(MANDATORY - seen)))

    owner = ledger.get("owner_approvals", {})
    require(isinstance(owner, dict) and set(owner) == APPROVAL_KEYS,
            "owner approval matrix incomplete")
    owner_approved = isinstance(owner, dict) and set(owner) == APPROVAL_KEYS and all(v is True for v in owner.values())
    if not owner_approved:
        blockers.append("owner approvals incomplete (scope, merges, native, version/tag, publication)")
    # This is declaration-shape validation only. Reviewers must verify the linked
    # comment and its author on GitHub; this script does not authenticate identities.
    proof = ledger.get("owner_authorization")
    owner_proof_supplied = isinstance(proof, dict) and proof.get("owner_login") == "KaisAbiyyi" and (
        proof.get("source_sha") == current_sha) and bool(re.fullmatch(
            r"https://github\.com/KaisAbiyyi/sibambo-bomc-builder/issues/31#issuecomment-\d+",
            str(proof.get("owner_comment_url", ""))))
    if not owner_proof_supplied:
        blockers.append("owner source-SHA-specific authorization evidence absent/unverified")
    if plan.get("license", {}).get("transitive_dependency_audit") != "PASS":
        blockers.append("third-party transitive dependency licensing NOT independently verified")
    if plan.get("license", {}).get("historical_source_ip_audit") != "PASS":
        blockers.append("historical IP/provenance NOT independently verified")

    artifact = manifest.get("artifact", {})
    name = artifact.get("name", "") if isinstance(artifact, dict) else ""
    require(isinstance(name, str) and re.fullmatch(r"bomc-builder-foundation-beta-[A-Za-z0-9.+-]+-[0-9a-f]{12}\.zip", name)
            is not None and "/" not in name, "invalid artifact name")
    require(name.endswith(current_sha[:12] + ".zip"), "artifact name lacks exact source SHA")
    archive = archive_dir / name
    if archive.is_file():
        contents = archive.read_bytes()
        require(sha256(contents) == artifact.get("sha256"), "artifact hash mismatch")
        require(len(contents) == artifact.get("bytes"), "artifact size mismatch")
        require(bool(SHA.fullmatch(str(artifact.get("sha256", "")))) if False else
                bool(re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256", "")))),
                "artifact SHA256 is malformed")
        files = manifest.get("files")
        require(isinstance(files, list) and len(files) > 0, "manifest source inventory missing")
        entries = {}
        if isinstance(files, list):
            for entry in files:
                if not isinstance(entry, dict):
                    errors.append("invalid source inventory entry")
                    continue
                rel = entry.get("path", "")
                if not isinstance(rel, str) or rel.startswith("/") or "\\" in rel or ".." in Path(rel).parts:
                    errors.append("unsafe source inventory path")
                    continue
                if rel in entries:
                    errors.append("duplicate source inventory path: " + rel)
                entries[rel] = entry
        try:
            with zipfile.ZipFile(archive) as zf:
                names = zf.namelist()
                require(len(names) == len(set(names)) and set(names) == set(entries),
                        "ZIP entries do not equal the source manifest inventory")
                for info in zf.infolist():
                    rel = info.filename
                    if rel not in entries:
                        continue
                    row = entries[rel]
                    require(info.date_time == (1980, 1, 1, 0, 0, 0) and
                            info.compress_type == zipfile.ZIP_STORED,
                            "nonreproducible ZIP settings: " + rel)
                    require((info.external_attr >> 16) & 0o170000 == 0o100000,
                            "ZIP member not a regular file: " + rel)
                    data = zf.read(info)
                    require(sha256(data) == row.get("sha256") and len(data) == row.get("bytes"),
                            "ZIP member SHA/size mismatch: " + rel)
                    path = root / rel
                    require(path.is_file() and not path.is_symlink() and
                            sha256(committed_source(rel)) == row.get("sha256"),
                            "source checkout no longer matches packaged file: " + rel)
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            errors.append("unreadable artifact archive: " + str(exc))
    else:
        errors.append("artifact missing in generated output directory")

    packaging_ready = not errors
    release_approved = packaging_ready and not blockers and owner_approved and owner_proof_supplied and all(
        item.get("status") in ("PASS", "OUT_OF_SCOPE") for item in gates if isinstance(item, dict)
    )
    return {
        "sourceSha": current_sha, "version": plan.get("version"),
        "packagingReady": packaging_ready, "releaseApproved": release_approved,
        "packagingErrors": sorted(set(errors)), "releaseBlockers": sorted(set(blockers)),
        "historicalEvidence": checked, "evidenceStatus": {item["id"]: item["status"] for item in gates
                                                            if isinstance(item, dict) and "id" in item},
        "publicationAuthorized": False,
        "qualification": "Packaged artifact is a provisional source bundle, not release approval",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=ROOT / "release/foundation-beta.json")
    parser.add_argument("--ledger", type=Path, default=ROOT / "release/acceptance-ledger.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "dist/release-manifest.json")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "dist/readiness")
    parser.add_argument("--gate", choices=("packaging", "release"), default="packaging")
    args = parser.parse_args()
    try:
        source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
        tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT).decode().strip()
        outcome = audit(read_json(args.plan), read_json(args.ledger), read_json(args.manifest),
                        ROOT, args.manifest.parent, source, tree,
                        committed_source=lambda rel: subprocess.check_output(
                            ["git", "show", "HEAD:" + rel], cwd=ROOT, stderr=subprocess.PIPE))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        outcome = {"sourceSha": None, "packagingReady": False, "releaseApproved": False,
                   "packagingErrors": ["readiness input error: " + str(exc)], "releaseBlockers": []}
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "readiness.json").write_text(json.dumps(outcome, sort_keys=True, indent=2) + "\n",
                                                    encoding="utf-8")
    lines = [
        "# BMB-031 Foundation Beta qualification",
        "",
        "- Exact source: " + str(outcome.get("sourceSha")),
        "- Packaging Ready: " + ("PASS" if outcome["packagingReady"] else "BLOCKED"),
        "- Release Approved: " + ("PASS" if outcome["releaseApproved"] else "BLOCKED"),
        "- This checker never publishes, tags, merges or grants owner approval.",
        "", "## Packaging errors", *("- " + x for x in outcome.get("packagingErrors", [])),
        "", "## Release blockers", *("- " + x for x in outcome.get("releaseBlockers", [])),
        "", "## Historical evidence (not current-HEAD acceptance)",
        *("- " + x for x in outcome.get("historicalEvidence", [])), ""
    ]
    (args.report_dir / "readiness.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"packagingReady": outcome["packagingReady"],
                      "releaseApproved": outcome["releaseApproved"],
                      "report": str(args.report_dir)}, sort_keys=True))
    if args.gate == "packaging":
        return 0 if outcome["packagingReady"] else 3
    return 0 if outcome["releaseApproved"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
