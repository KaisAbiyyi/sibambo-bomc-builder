"""BMB-020: deterministic graph to BOMC 1.2 metadata compiler.

Geometry-bearing Module IR is supported through a bounded real semantic writer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
import tempfile

from bomc.adapter.writer_v12 import (
    HEADER, ENTRY, IDENTITY, MAX_INPUT_BYTES, MAX_NODES,
    UnsupportedFeature, encode_graph,
)
from core.assembly.merge import Assembly, AssemblyError, assemble
from bomc.compiler.semantic_v12 import encode_semantic, GeometryEncodingError
from core.graph import dag
from core.geometry.semantics import validate_module_faces, SemanticFaceError

MODULE_FIELDS = {
    "schemaVersion", "moduleId", "parentId", "revision", "localFrame",
    "bounds", "operations", "materials", "ports", "ownedSeams",
    "dependencies", "provenance", "faceAnnotations",
}
REQUIRED = MODULE_FIELDS - {"faceAnnotations"}
FRAME_FIELDS = {"unit", "handedness", "upAxis", "forwardAxis", "transform"}
ROOT_NAME = "BOMC Builder assembly"


class CompileError(UnsupportedFeature):
    """Input cannot be represented without information loss."""


@dataclass(frozen=True)
class Compiled:
    payload: bytes
    sha256: str
    node_count: int
    string_count: int
    section_ids: tuple[int, ...]
    coverage: tuple[int, ...]
    geometry_info: dict | None = None

    def receipt(self) -> dict:
        return {
            "profile": "bomc-1.2-semantic-solid-subset" if self.geometry_info else "bomc-1.2-metadata-only",
            "sha256": self.sha256,
            "sizeBytes": len(self.payload),
            "nodeCount": self.node_count,
            "stringCount": self.string_count,
            "sections": list(self.section_ids),
            "coverage": list(self.coverage),
            "geometrySemanticsValid": bool(self.geometry_info),
            **({k: v for k, v in self.geometry_info.items() if k not in ("coverage", "sectionIds")}
               if self.geometry_info else {}),
        }


def _need(ok: bool, why: str) -> None:
    if not ok:
        raise CompileError(why)


def _object(value: object, required: set[str], allowed: set[str], where: str) -> dict:
    _need(isinstance(value, dict), f"{where}: expected object")
    _need(required <= value.keys(), f"{where}: missing {sorted(required - value.keys())}")
    _need(value.keys() <= allowed, f"{where}: unsupported {sorted(value.keys() - allowed)}")
    return value


def _to_wire_matrix(row_major: object) -> list[float]:
    try:
        matrix = dag.validate_transform(row_major, "module transform")
    except dag.GraphError as exc:
        raise CompileError(str(exc)) from exc
    return [matrix[r * 4 + c] for c in range(4) for r in range(4)]


def _stable_id(kind: str, name: str, used: dict[str, str]) -> str:
    token = kind + "-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]
    _need(token not in used or used[token] == kind + ":" + name, "digest collision")
    used[token] = kind + ":" + name
    return token


def _emit(nodes: list[dict]) -> Compiled:
    _need(1 <= len(nodes) <= MAX_NODES, "writer node budget exceeded")
    try:
        payload = encode_graph({"schemaVersion": "bmb-writer-graph-v1",
                                "name": ROOT_NAME, "nodes": nodes})
    except (UnsupportedFeature, TypeError, OverflowError) as exc:
        raise CompileError(str(exc)) from exc
    header = HEADER.unpack_from(payload)
    rows = [ENTRY.unpack_from(payload, HEADER.size + i * ENTRY.size)
            for i in range(header[5])]
    sections = {row[0]: row for row in rows}
    _need(set(sections) == {1, 2, 11, 12, 13, 17, 20},
          "unexpected writer sections")
    coverage_row = sections[17]
    coverage_payload = payload[coverage_row[3]:coverage_row[3] + coverage_row[4]]
    _need(coverage_payload == bytes(24), "nonzero coverage without geometry")
    return Compiled(payload, hashlib.sha256(payload).hexdigest(), len(nodes),
                    sections[2][6], tuple(sorted(sections)), (0,)*6)


def compile_assembly(assembly: Assembly) -> Compiled:
    """Compile verified BMB-011 assembly preserving local placement transforms."""
    _need(isinstance(assembly, Assembly), "BMB-011 Assembly required")
    _need(0 < len(assembly.modules) < MAX_NODES, "assembly exceeds writer budget")
    for mid, module in assembly.modules.items():
        doc = _object(module, REQUIRED, MODULE_FIELDS, mid)
        try:
            validate_module_faces(doc)
        except SemanticFaceError as exc:
            raise CompileError(f"{mid}: Module IR schema / semantic rejection: {exc}") from exc
        frame = _object(doc["localFrame"], FRAME_FIELDS, FRAME_FIELDS, mid + ".localFrame")
        _need(frame["unit"] == "m" and frame["handedness"] == "right" and
              frame["upAxis"] == "+Z" and frame["forwardAxis"] == "+Y",
              f"{mid}: invalid local frame convention")
        _to_wire_matrix(frame["transform"])
        bounds = _object(doc["bounds"], {"min", "max"}, {"min", "max"}, mid + ".bounds")
        for part in ("min", "max"):
            vec = bounds[part]
            _need(isinstance(vec, list) and len(vec) == 3, f"{mid}: malformed bounds")
            for v in vec:
                _need(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 1e6,
                      f"{mid}: invalid bounds")
        if not doc["operations"]:
            _need(all(v == 0 for part in ("min", "max") for v in bounds[part]),
                  f"{mid}: nonzero bounds with no geometry")
        provenance = _object(doc["provenance"], {"origin", "generator"},
                             {"origin", "generator", "note"}, mid + ".provenance")
        _need(provenance["origin"] in ("synthetic", "user-authored") and
              isinstance(provenance["generator"], str) and
              len(provenance["generator"]) <= 160, f"{mid}: invalid provenance")
        _need(mid in assembly.world_transforms, f"{mid}: unresolved world transform")

    used: dict[str, str] = {}
    parent_names = sorted({m["parentId"] for m in assembly.modules.values()
                           if m["parentId"] is not None and
                           m["parentId"] not in assembly.modules})
    groups = {parent: _stable_id("g", parent, used) for parent in parent_names}
    module_ids = {mid: _stable_id("m", mid, used) for mid in assembly.modules}
    nodes = [{"id": "root", "kind": "root", "name": ROOT_NAME,
              "parentId": None, "transform": list(IDENTITY)}]
    for parent, token in sorted(groups.items()):
        _need(len(parent) <= 128, "external parent exceeds name limit")
        nodes.append({"id": token, "kind": "group", "name": parent,
                      "parentId": "root", "transform": list(IDENTITY)})
    for mid, module in sorted(assembly.modules.items()):
        _need(len(mid) <= 128, "module exceeds BOMC name limit")
        parent = module["parentId"]
        parent_id = module_ids[parent] if parent in module_ids else (
            groups[parent] if parent is not None else "root")
        nodes.append({"id": module_ids[mid], "kind": "group", "name": mid,
                      "parentId": parent_id,
                      "transform": _to_wire_matrix(module["localFrame"]["transform"])})
    if any(module["operations"] for module in assembly.modules.values()):
        try:
            binary, info = encode_semantic(assembly, nodes)
        except (GeometryEncodingError, ValueError, TypeError, KeyError,
                OverflowError, RecursionError) as exc:
            raise CompileError("semantic geometry rejected: " + str(exc)) from exc
        return Compiled(binary, hashlib.sha256(binary).hexdigest(), len(nodes),
                        _string_count(binary), info["sectionIds"], info["coverage"], info)
    _need(not any(module["materials"] or module["ports"] or module["ownedSeams"] or
                  module.get("faceAnnotations") for module in assembly.modules.values()),
          "nonempty semantic metadata without geometry cannot be dropped")
    return _emit(nodes)


def _string_count(binary: bytes) -> int:
    for i in range(HEADER.unpack_from(binary)[5]):
        row = ENTRY.unpack_from(binary, HEADER.size + i * ENTRY.size)
        if row[0] == 2:
            return row[6]
    raise CompileError("missing strings section")


def compile_document(value: object) -> Compiled:
    """BMB-006 envelope -> BMB-011 assembly -> real BOMC 1.2 solid subset."""
    doc = _object(value, {"schemaVersion", "modules"},
                  {"schemaVersion", "modules"}, "document")
    _need(doc["schemaVersion"] == "1.0.0", "unsupported document schemaVersion")
    _need(isinstance(doc["modules"], list), "modules must be a list")
    for index, module in enumerate(doc["modules"]):
        _need(isinstance(module, dict), f"modules[{index}]: expected object")
    try:
        return compile_assembly(assemble(doc["modules"]))
    except AssemblyError as exc:
        raise CompileError(str(exc)) from exc


def compile_definition_graph(graph: dag.DefinitionGraph, root_definition: str) -> Compiled:
    """Expand BMB-009 DAG deterministically as empty-group occurrences."""
    _need(isinstance(graph, dag.DefinitionGraph), "DefinitionGraph required")
    try:
        graph.world_transforms(root_definition)
    except dag.GraphError as exc:
        raise CompileError(str(exc)) from exc
    nodes = [{"id": "root", "kind": "root", "name": ROOT_NAME,
              "parentId": None, "transform": list(IDENTITY)}]
    used: dict[str, str] = {}

    def walk(owner: str, parent: str, prefix: str, depth: int) -> None:
        _need(depth <= dag.MAX_DEPTH, "definition depth budget exceeded")
        for instance, target, local in graph.instances(owner):
            path = prefix + "/" + instance if prefix else instance
            token = _stable_id("i", path, used)
            nodes.append({"id": token, "kind": "group", "name": target,
                          "parentId": parent, "transform": _to_wire_matrix(local)})
            _need(len(nodes) <= MAX_NODES, "expanded graph exceeds writer node budget")
            walk(target, token, path, depth + 1)

    try:
        walk(root_definition, "root", "", 1)
    except dag.GraphError as exc:
        raise CompileError(str(exc)) from exc
    return _emit(nodes)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for k, v in pairs:
        _need(k not in result, f"duplicate JSON key {k!r}")
        result[k] = v
    return result


def load_document(path: Path) -> object:
    try:
        _need(path.stat().st_size <= MAX_INPUT_BYTES, "JSON input budget exceeded")
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs,
            parse_constant=lambda c: (_ for _ in ()).throw(CompileError("invalid number " + c)))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CompileError(f"invalid input JSON: {exc}") from exc


def _atomic_write(path: Path, data: bytes) -> None:
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".bmb020-",
                                         suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Strict BMB-020 graph-to-BOMC")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        compiled = compile_document(load_document(args.input))
        _atomic_write(args.output, compiled.payload)
        print(json.dumps(compiled.receipt(), sort_keys=True))
    except (CompileError, ValueError, OSError) as exc:
        parser.exit(2, f"BMB-020 reject: {exc}\n")


if __name__ == "__main__":
    main()
