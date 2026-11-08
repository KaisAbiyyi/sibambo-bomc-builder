#!/usr/bin/env python3
"""BMB-031 deterministic, source-only Foundation Beta candidate packaging.

No tags, publication, external binaries, private fixtures or network access.
The resulting package is an unapproved candidate, not a GitHub Release.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as package_metadata
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
HIGH_CONFIDENCE_SECRETS = (
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(rb"sk-proj-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
)
PRIVATE_PATHS = (re.compile(rb"[A-Za-z]:\\Users\\[^\\\s]+", re.I),
                 re.compile(rb"[A-Za-z]:\\projects\\", re.I))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def installed_license_metadata(spec: dict, *, optional: bool = False) -> dict:
    name, version = spec["name"], spec["version"]
    try:
        package = package_metadata.distribution(name)
    except package_metadata.PackageNotFoundError:
        if optional:
            return {"name": name, "expectedVersion": version, "status": "OPTIONAL_NOT_INSTALLED"}
        raise ValueError("pinned runtime dependency not installed: " + name)
    if package.version != version:
        raise ValueError("dependency version mismatch: {} expected {}, observed {}".format(
            name, version, package.version))
    info = package.metadata
    return {"name": name, "version": package.version,
            "licenseExpression": info.get("License-Expression"),
            "license": info.get("License"),
            "licenseClassifiers": [str(v) for v in info.get_all("Classifier", [])
                                   if str(v).startswith("License ::")],
            "requires": package.requires or [],
            "status": "INSTALLED_METADATA_OBSERVED_NOT_TRANSITIVE_CERTIFICATION"}


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.PIPE).decode().strip()


def selected_files(plan: dict) -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    tracked = {x.decode("utf-8") for x in raw.split(b"\0") if x}
    roots = tuple(plan["packaging"]["source_roots"])
    explicit = set(plan["packaging"]["source_files"])
    missing = explicit - tracked
    if missing:
        raise ValueError("required tracked release sources missing: " + ", ".join(sorted(missing)))
    selected = sorted(p for p in tracked if p in explicit or p.startswith(roots))
    for rel in selected:
        candidate = ROOT / rel
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("source is not a regular non-symlink file: " + rel)
        if candidate.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("oversize source: " + rel)
        if any(part in ("..", ".git", "dist", "__pycache__") for part in Path(rel).parts):
            raise ValueError("unsafe source path: " + rel)
    return selected


def build(out: Path) -> dict:
    plan = json.loads((ROOT / "release/foundation-beta.json").read_text(encoding="utf-8"))
    if plan.get("schema_version") != "bmb-foundation-beta-plan-v1":
        raise ValueError("unknown release plan format")
    if plan.get("version_status") != "PROVISIONAL_OWNER_APPROVAL_REQUIRED":
        raise ValueError("publication contract must remain provisional")
    source_sha = git("rev-parse", "HEAD")
    tree_sha = git("rev-parse", "HEAD^{tree}")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("invalid HEAD")
    if subprocess.run(["git", "diff", "--quiet", "--"], cwd=ROOT, check=False).returncode != 0:
        raise ValueError("modified tracked files: refuse to package uncommitted content")
    if subprocess.run(["git", "merge-base", "--is-ancestor", plan["source"]["baseline_main_sha"], "HEAD"],
                      cwd=ROOT, check=False).returncode != 0:
        raise ValueError("verified baseline main is not an ancestor")
    files = selected_files(plan)
    inventory = []
    archive_name = "{}-{}-{}.zip".format(
        plan["packaging"]["artifact_prefix"], plan["version"], source_sha[:12])
    out.mkdir(parents=True, exist_ok=True)
    archive = out / archive_name
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as output:
        for rel in files:
            # Use Git object bytes, not checkout bytes: Windows autocrlf must not
            # change the release inventory or artifact SHA for the same commit.
            body = subprocess.check_output(["git", "show", "HEAD:" + rel], cwd=ROOT)
            for pattern in (*HIGH_CONFIDENCE_SECRETS, *PRIVATE_PATHS):
                if pattern.search(body):
                    raise ValueError("potential secret or private path in release source: " + rel)
            info = zipfile.ZipInfo(rel, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            output.writestr(info, body)
            inventory.append({"path": rel, "sha256": digest(body), "bytes": len(body)})
    payload = archive.read_bytes()
    if len(payload) > plan["packaging"]["max_artifact_bytes"]:
        archive.unlink()
        raise ValueError("archive exceeds maximum size")
    manifest = {
        "schema_version": "bmb-foundation-beta-manifest-v1",
        "target": plan["target"],
        "release_version": plan["version"],
        "approval": "NOT_APPROVED",
        "source_sha": source_sha,
        "source_tree_sha": tree_sha,
        "baseline_main_sha": plan["source"]["baseline_main_sha"],
        "bomc": plan["compatibility"],
        "runtime": plan["runtime"],
        "license": plan["license"],
        "provenance": {"artifact_contents": "tracked source only", "fixture_policy": "synthetic-only",
                       "historical_ip_audit": "NOT_RUN", "transitive_dependency_audit": "NOT_RUN",
                       "native_windows_acceptance": "NOT_RUN"},
        "artifact": {"name": archive_name, "sha256": digest(payload), "bytes": len(payload),
                     "format": "zip-stored-fixed-1980-timestamp"},
        "files": inventory,
    }
    (out / "release-manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n",
                                              encoding="utf-8")
    provenance = {
        "source_sha": source_sha,
        "license": "GPL-3.0-only",
        "policy": "docs/LICENSE-IP-FIXTURE-POLICY.md",
        "runtime_packages": [installed_license_metadata(spec) for spec in plan["runtime"]["packages"]],
        "optional_validation_packages": [
            installed_license_metadata(spec, optional=True) for spec in plan["runtime"]["optional_validation"]
        ],
        "metadata_review": "METADATA_ONLY; runtime and transitive wheel notices/SBOM still unverified",
        "unresolved": ["independent IP chain of title", "transitive dependency licenses and source notices",
                       "historical repository and third-party asset provenance",
                       "original consumer and native Windows release certification"],
        "packaged_files": len(inventory),
        "package_sha256": manifest["artifact"]["sha256"],
        "claim": "Bounded archive inventory only; not a forensic or legal certification",
    }
    (out / "provenance-report.json").write_text(json.dumps(provenance, sort_keys=True, indent=2) + "\n",
                                                encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        manifest = build(args.out.resolve())
        print(json.dumps({"source_sha": manifest["source_sha"], "artifact": manifest["artifact"],
                          "file_count": len(manifest["files"]), "approved": False}, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as exc:
        print("BMB-031 package BLOCKED: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
