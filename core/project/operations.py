"""SE-01: typed draft-operation-v1 transactions over Module IR.

A transaction is 1-8 unique ``replace_module`` / ``remove_module`` changes.
``apply_transaction`` stages a deep clone of the whole project, applies every change,
re-validates the *entire* staged project (schema, assembly/seam ownership, geometry
projection, compiler probe) and only then returns a new immutable ``ProjectState``.
Any failure raises before anything is returned, so the prior state is never mutated
and a one-sided reciprocal seam can never be committed.

Typed helpers (``add_floor``/``add_wall``/``add_opening``/``update_operation``) lower to
``replace_module`` through the existing geometry builders. There is no arbitrary code,
shell or expression evaluation anywhere in this module. This module is pure: no I/O,
no actor, no auth, no sockets (SE-02/03/05 own those).
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator

from core.assembly.merge import Assembly, AssemblyError, assemble
from core.geometry.floor import FloorError, build_floor_slab
from core.geometry.openings import build_wall_with_openings
from core.geometry.semantics import SemanticFaceError, validate_module_faces
from core.geometry.wall import build_wall_run
from core.project import projection as _projection

SCHEMA_VERSION = "draft-operation-v1"
VIEW_SCHEMA_VERSION = "draft-view-v1"
MAX_CHANGES = 8                       # modules per transaction (frozen contract)
MAX_REQUEST_BYTES = 256 * 1024        # request cap (frozen contract)
MAX_MODULE_BYTES = 64 * 1024          # canonical module block cap (frozen contract)
MAX_PROJECT_BYTES = 2 * 1024 * 1024   # project envelope cap (frozen contract)
MAX_IDEMPOTENCY_ENTRIES = 1024

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
_OP_SCHEMA = json.loads((SCHEMA_DIR / "draft-operation-v1.schema.json").read_text(encoding="utf-8"))
_OP_VALIDATOR = Draft202012Validator(_OP_SCHEMA)


class OperationError(ValueError):
    """Transaction rejected before any state mutation."""


def _need(ok: bool, why: str) -> None:
    if not ok:
        raise OperationError(why)


def canonical_json(value: object) -> bytes:
    """Exact canonical UTF-8 bytes: sorted keys, compact, no NaN/Infinity."""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise OperationError("value is not canonical finite JSON") from exc


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        _need(key not in out, f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _reject_constant(value):
    raise OperationError(f"invalid JSON constant {value}")


def parse_transaction(payload: bytes) -> dict:
    """Bounded, strict decode of a request body (duplicate keys / NaN / bad UTF-8 rejected)."""
    _need(type(payload) is bytes and len(payload) <= MAX_REQUEST_BYTES,
          "request must be bytes of at most 256 KiB")
    try:
        txn = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_pairs,
                         parse_constant=_reject_constant)
    except OperationError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise OperationError("request is not strict UTF-8 JSON") from exc
    return txn


# --- immutable project state ------------------------------------------------

@dataclass(frozen=True)
class ProjectState:
    """Committed project revision. Treat as immutable; apply_transaction returns a new one."""
    project_revision: int = 0
    modules: dict = field(default_factory=dict)       # moduleId -> deep-copied Module IR
    idempotency: dict = field(default_factory=dict)   # key -> (request sha256, resulting revision)

    def module_revisions(self) -> dict:
        return {mid: m["revision"] for mid, m in sorted(self.modules.items())}

    def document(self) -> dict:
        return {"schemaVersion": "1.0.0",
                "modules": [copy.deepcopy(m) for _, m in sorted(self.modules.items())]}


EMPTY_STATE = ProjectState()


@dataclass(frozen=True)
class TransactionResult:
    state: ProjectState
    replayed: bool
    changed_modules: tuple
    removed_modules: tuple


# --- validation -------------------------------------------------------------

def _schema_check(txn: object) -> None:
    _projection_finite(txn)
    errors = sorted(_OP_VALIDATOR.iter_errors(txn),
                    key=lambda e: (list(map(str, e.absolute_path)), e.message))
    if errors:
        where = "/".join(map(str, errors[0].absolute_path)) or "<root>"
        raise OperationError(f"draft-operation-v1 schema: {where}: {errors[0].message}")


def _projection_finite(value: object) -> None:
    stack = [(value, 1)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        _need(count <= 2_000_000 and depth <= 64, "request JSON exceeds depth or size budget")
        if type(item) is float:
            _need(math.isfinite(item), "non-finite number")
        elif type(item) is list:
            stack.extend((c, depth + 1) for c in item)
        elif type(item) is dict:
            for k, c in item.items():
                _need(type(k) is str, "non-string JSON key")
                stack.append((c, depth + 1))


def _dependents(modules: dict, target: str, removing: set) -> list:
    out = []
    for mid, m in sorted(modules.items()):
        if mid in removing:
            continue
        refs = []
        if m.get("parentId") == target:
            refs.append("parent")
        if any(d.get("moduleId") == target for d in m.get("dependencies", [])):
            refs.append("dependency")
        if any((p.get("peer") or {}).get("moduleId") == target for p in m.get("ports", [])):
            refs.append("seam port peer")
        if any(target in s.get("participants", []) for s in m.get("ownedSeams", [])):
            refs.append("seam participant")
        if refs:
            out.append((mid, refs))
    return out


def _compile_probe(modules: dict) -> None:
    """Prove the staged project still compiles under the unchanged compiler limits."""
    from bomc.compiler.graph_to_bomc import compile_document, CompileError  # lazy: core never owns bomc
    try:
        compile_document({"schemaVersion": "1.0.0",
                          "modules": [copy.deepcopy(m) for _, m in sorted(modules.items())]})
    except CompileError as exc:
        raise OperationError("staged project rejected by compiler: " + str(exc)) from exc


def _validate_project(modules: dict) -> Assembly | None:
    """Full-project validation of a staged module map."""
    if not modules:
        return None
    for mid, m in sorted(modules.items()):
        try:
            validate_module_faces(m)
        except SemanticFaceError as exc:
            raise OperationError(f"{mid}: {exc}") from exc
        size = len(canonical_json(m))
        _need(size <= MAX_MODULE_BYTES,
              f"{mid}: canonical module is {size} bytes, over the 64 KiB block cap")
    try:
        assembly = assemble([m for _, m in sorted(modules.items())])
    except AssemblyError as exc:
        raise OperationError("assembly rejected: " + str(exc)) from exc
    doc = {"schemaVersion": "1.0.0", "modules": [m for _, m in sorted(modules.items())]}
    _need(len(canonical_json(doc)) <= MAX_PROJECT_BYTES, "project exceeds the 2 MiB envelope")
    if any(m["operations"] for m in modules.values()):
        try:
            _projection.collect_module_faces(assembly)
        except _projection.GeometryEncodingError as exc:
            raise OperationError("geometry projection rejected: " + str(exc)) from exc
        _compile_probe(modules)
    return assembly


def apply_transaction(state: ProjectState, txn: object) -> TransactionResult:
    """Atomically apply a draft-operation-v1 transaction, or raise OperationError."""
    _need(isinstance(state, ProjectState), "ProjectState required")
    _need(type(txn) is dict, "transaction must be an object")
    _schema_check(txn)
    _need(len(canonical_json(txn)) <= MAX_REQUEST_BYTES, "request exceeds 256 KiB")
    request_hash = sha256_hex(canonical_json(txn))

    key = txn["idempotencyKey"]
    if key in state.idempotency:
        prior_hash, _rev = state.idempotency[key]
        _need(prior_hash == request_hash, "idempotencyKey reused with a different request")
        return TransactionResult(state, True, (), ())

    _need(txn["baseProjectRevision"] == state.project_revision,
          f"stale baseProjectRevision {txn['baseProjectRevision']}, project is at {state.project_revision}")

    changes = txn["changes"]
    ids = [c["moduleId"] for c in changes]
    _need(len(set(ids)) == len(ids), "duplicate moduleId in one transaction")

    staged = copy.deepcopy(state.modules)           # staged clone; live state stays untouched
    removing = {c["moduleId"] for c in changes if c["op"] == "remove_module"}
    changed, removed = [], []
    for c in changes:
        mid, expected = c["moduleId"], c["expectedModuleRevision"]
        current = state.modules.get(mid)
        if c["op"] == "replace_module":
            module = copy.deepcopy(c["module"])
            _need(module.get("moduleId") == mid, f"{mid}: module body carries a different moduleId")
            if current is None:
                _need(expected is None, f"{mid}: expectedModuleRevision must be null for a new module")
            else:
                _need(expected == current["revision"],
                      f"{mid}: stale expectedModuleRevision {expected}, module is at {current['revision']}")
                _need(module.get("revision") == current["revision"] + 1,
                      f"{mid}: replacement revision must be {current['revision'] + 1}")
            staged[mid] = module
            changed.append(mid)
        else:
            _need(current is not None, f"{mid}: cannot remove a module that does not exist")
            _need(expected == current["revision"],
                  f"{mid}: stale expectedModuleRevision {expected}, module is at {current['revision']}")
            deps = _dependents(state.modules, mid, removing)
            _need(not deps, f"{mid}: still referenced by " +
                  "; ".join(f"{d} ({', '.join(r)})" for d, r in deps))
            del staged[mid]
            removed.append(mid)

    _validate_project(staged)                       # raises before any state is created

    idem = dict(state.idempotency)
    new_revision = state.project_revision + 1
    idem[key] = (request_hash, new_revision)
    while len(idem) > MAX_IDEMPOTENCY_ENTRIES:
        idem.pop(next(iter(idem)))
    new_state = ProjectState(new_revision, dict(sorted(staged.items())), idem)
    return TransactionResult(new_state, False, tuple(sorted(changed)), tuple(sorted(removed)))


# --- views ------------------------------------------------------------------

def canonical_ir_json(state: ProjectState) -> bytes:
    """Exact UTF-8 bytes of the canonical project Module IR document."""
    return canonical_json(state.document())


def project_view(state: ProjectState) -> dict:
    """draft-view-v1: shared projection + exact-byte hashes (hash before parsing)."""
    ir_bytes = canonical_ir_json(state)
    if state.modules and any(m["operations"] for m in state.modules.values()):
        projection = _projection.project_assembly(assemble(state.document()["modules"]))
    else:
        projection = {"schemaVersion": "1.0.0", "units": "m", "upAxis": "+Z",
                      "transformConvention": "row-major module-to-assembly; apply once to local Float64 positions",
                      "modules": []}
    projection_bytes = canonical_json(projection)
    return {"schemaVersion": VIEW_SCHEMA_VERSION,
            "projectRevision": state.project_revision,
            "moduleRevisions": state.module_revisions(),
            "canonicalIrSha256": sha256_hex(ir_bytes),
            "projectionSha256": sha256_hex(projection_bytes),
            "projection": projection}


def projection_json(state: ProjectState) -> bytes:
    return canonical_json(project_view(state)["projection"])


# --- typed helpers (lower to replace_module) ---------------------------------

def _clone(module: dict) -> dict:
    _need(type(module) is dict, "module must be an object")
    return copy.deepcopy(module)


def _material_ok(module: dict, material_id, material: dict | None = None) -> None:
    """Material must exist, or be supplied as a full solid-colour definition to add."""
    known = {m["materialId"] for m in module["materials"]}
    if material is not None:
        _need(type(material) is dict and material.get("materialId") == material_id,
              "material definition must carry the same materialId")
        _need(material_id not in known, f"duplicate materialId {material_id!r}")
        module["materials"].append(copy.deepcopy(material))
        return
    _need(material_id is None or material_id in known, f"unknown materialId {material_id!r}")


def _op_extent(op: dict) -> tuple:
    if op["kind"] == "floor-slab":
        xs = [p[0] for p in op["footprint"]]
        ys = [p[1] for p in op["footprint"]]
        return (min(xs), min(ys), op["elevation"] - op["thickness"],
                max(xs), max(ys), op["elevation"])
    xs = [p[0] for p in op["path"]]
    ys = [p[1] for p in op["path"]]
    t = op["thickness"]
    return (min(xs) - t, min(ys) - t, op["baseElevation"],
            max(xs) + t, max(ys) + t, op["baseElevation"] + op["height"])


def _grow_bounds(module: dict, op: dict) -> None:
    ext = _op_extent(op)
    b = module["bounds"]
    if len(module["operations"]) == 1 and all(v == 0 for part in ("min", "max") for v in b[part]):
        lo, hi = list(ext[:3]), list(ext[3:])
    else:
        lo = [min(b["min"][i], ext[i]) for i in range(3)]
        hi = [max(b["max"][i], ext[i + 3]) for i in range(3)]
    b["min"], b["max"] = lo, hi


def _finish(module: dict, replaced_op: dict | None, op: dict | None) -> dict:
    """Common tail: geometry self-check through the existing builders, then bump revision."""
    try:
        if op is not None and op["kind"] == "floor-slab":
            build_floor_slab(op)
        elif op is not None and op["kind"] == "wall-run":
            build_wall_run(op)
        for o in module["operations"]:
            if o["kind"] == "opening-cut":
                wall = next((w for w in module["operations"] if w["opId"] == o["targetWallOpId"]), None)
                _need(wall is not None and wall["kind"] == "wall-run",
                      f"opening {o['opId']!r} must target an existing wall-run")
                build_wall_with_openings(wall, [x for x in module["operations"]
                                                if x["kind"] == "opening-cut"
                                                and x["targetWallOpId"] == wall["opId"]])
    except OperationError:
        raise
    except Exception as exc:  # the geometry builders raise their own typed errors
        raise OperationError(f"geometry builder rejected the change: {exc}") from exc
    module["revision"] += 1
    return module


def _unique_op(module: dict, op_id: str) -> None:
    _need(isinstance(op_id, str) and op_id, "opId required")
    _need(all(o["opId"] != op_id for o in module["operations"]), f"duplicate opId {op_id!r}")


def add_floor(module, op_id, footprint, thickness, elevation, material_id, role="floor", material=None):
    m = _clone(module)
    _unique_op(m, op_id)
    _material_ok(m, material_id, material)
    op = {"kind": "floor-slab", "opId": op_id, "role": role, "materialId": material_id,
          "footprint": [list(p) for p in footprint], "thickness": thickness, "elevation": elevation}
    m["operations"].append(op)
    _grow_bounds(m, op)
    return _finish(m, None, op)


def add_wall(module, op_id, path, thickness, height, base_elevation, material_id, material=None):
    m = _clone(module)
    _unique_op(m, op_id)
    _material_ok(m, material_id, material)
    op = {"kind": "wall-run", "opId": op_id, "role": "wall", "materialId": material_id,
          "path": [list(p) for p in path], "thickness": thickness, "height": height,
          "baseElevation": base_elevation}
    m["operations"].append(op)
    _grow_bounds(m, op)
    return _finish(m, None, op)


def add_opening(module, op_id, target_wall_op_id, offset, width, height, sill_height, opening_type):
    m = _clone(module)
    _unique_op(m, op_id)
    wall = next((o for o in m["operations"] if o["opId"] == target_wall_op_id), None)
    _need(wall is not None and wall["kind"] == "wall-run", "opening must target an existing wall-run")
    op = {"kind": "opening-cut", "opId": op_id, "role": "opening", "targetWallOpId": target_wall_op_id,
          "offset": offset, "width": width, "height": height, "sillHeight": sill_height,
          "openingType": opening_type}
    m["operations"].append(op)
    # Face annotations on a cut wall have no cut mapping; drop them rather than keep stale labels.
    if "faceAnnotations" in m:
        m["faceAnnotations"] = [a for a in m["faceAnnotations"] if a["opId"] != target_wall_op_id]
    return _finish(m, None, op)


_UPDATABLE = {
    "floor-slab": {"footprint", "thickness", "elevation", "materialId", "role"},
    "wall-run": {"path", "thickness", "height", "baseElevation", "materialId"},
    "opening-cut": {"offset", "width", "height", "sillHeight", "openingType"},
}


def update_operation(module, op_id, **fields):
    m = _clone(module)
    op = next((o for o in m["operations"] if o["opId"] == op_id), None)
    _need(op is not None, f"unknown opId {op_id!r}")
    allowed = _UPDATABLE[op["kind"]]
    bad = sorted(set(fields) - allowed)
    _need(not bad, f"fields not updatable on {op['kind']}: {bad}")
    _need(fields, "no fields to update")
    if "materialId" in fields:
        _material_ok(m, fields["materialId"])
    op.update(copy.deepcopy(fields))
    if op["kind"] != "opening-cut":
        _grow_bounds(m, op)
    return _finish(m, None, op if op["kind"] != "opening-cut" else None)


HELPERS = {
    "add_floor": add_floor, "add_wall": add_wall,
    "add_opening": add_opening, "update_operation": update_operation,
}


def lower_helper(state: ProjectState, call: dict) -> dict:
    """Lower a typed helper call to a replace_module change (never executes anything else)."""
    _need(type(call) is dict and call.get("tool") in HELPERS, "unsupported helper tool")
    args = {k: v for k, v in call.items() if k not in ("tool", "moduleId")}
    mid = call.get("moduleId")
    current = state.modules.get(mid)
    _need(current is not None, f"unknown moduleId {mid!r}")
    try:
        module = HELPERS[call["tool"]](current, **args)
    except TypeError as exc:
        raise OperationError(f"bad helper arguments: {exc}") from exc
    return {"op": "replace_module", "moduleId": mid,
            "expectedModuleRevision": current["revision"], "module": module}


def make_transaction(state: ProjectState, changes: list, idempotency_key: str,
                     transaction_id: str | None = None) -> dict:
    return {"schemaVersion": SCHEMA_VERSION,
            "transactionId": transaction_id or idempotency_key,
            "idempotencyKey": idempotency_key,
            "baseProjectRevision": state.project_revision,
            "changes": changes}
