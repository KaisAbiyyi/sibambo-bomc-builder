"""SE-01 gates: typed draft operations, atomic 1-8 module transactions, shared projection.

Everything here is wholly synthetic and runs in cloud CI. It does not exercise the
actor, auth, WebSocket or Editor (SE-02/03/05 and SE-11 own those) and it is not a
native or owner visual acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from bomc.adapter import writer_v12  # noqa: E402
from bomc.compiler import semantic_v12  # noqa: E402
from bomc.compiler.graph_to_bomc import compile_document  # noqa: E402
from core.assembly import assemble  # noqa: E402
from core.graph import dag  # noqa: E402
from core.project import operations as ops  # noqa: E402
from core.project import projection  # noqa: E402
from core.project.operations import (  # noqa: E402
    EMPTY_STATE, OperationError, apply_transaction, make_transaction, project_view)
from examples import bmb026_house as house  # noqa: E402
from tests.interop.reader import read as independent_read  # noqa: E402

BASELINE_SHA = "071ebe152b44d2bae387818094ad67a6f461645d45d1ad33c195848dbb0b49aa"
REVISED_SHA = "e56924fead241df9a1a76c9de9e0e647b13caf2785cf14bc4c679a8979192233"


def create(module):
    return {"op": "replace_module", "moduleId": module["moduleId"],
            "expectedModuleRevision": None, "module": module}


def replace(state, module):
    return {"op": "replace_module", "moduleId": module["moduleId"],
            "expectedModuleRevision": state.modules[module["moduleId"]]["revision"], "module": module}


def bump(module, revision):
    out = copy.deepcopy(module)
    out["revision"] = revision
    return out


def snapshot(state):
    return (state.project_revision, json.dumps(state.modules, sort_keys=True),
            sorted(state.idempotency))


def compiled_sha(state):
    return compile_document(state.document()).sha256


def four_room_state():
    doc = house.build_house()
    return apply_transaction(EMPTY_STATE, make_transaction(
        EMPTY_STATE, [create(m) for m in doc["modules"]], "four-room-1")).state


def connected_pair():
    """Two previously unconnected rooms and their reciprocal-seam replacements."""
    modules = {n: house._room(n, False) for n in ("living", "bedroom-a")}
    before = {n: copy.deepcopy(m) for n, m in modules.items()}
    house._connect(modules, "living", "bedroom-a", "east", "living-a", opening_offset=1.0)
    for n in modules:
        modules[n]["revision"] = 2
    return before, modules


class FourRoomTransaction(unittest.TestCase):
    def test_four_room_walls_one_atomic_transaction_golden_bytes(self):
        state = four_room_state()
        self.assertEqual(state.project_revision, 1)
        self.assertEqual(len(state.modules), 5)
        self.assertEqual(compiled_sha(state), BASELINE_SHA)
        self.assertEqual(compiled_sha(state), compile_document(house.build_house()).sha256)

    def test_revised_window_is_one_module_transaction_with_golden_bytes(self):
        state = four_room_state()
        revised = {m["moduleId"]: m for m in house.build_house(revised=True)["modules"]}
        mid = house.ROOM_IDS["bedroom-a"]
        result = apply_transaction(state, make_transaction(
            state, [replace(state, revised[mid])], "window-1"))
        self.assertEqual(result.changed_modules, (mid,))
        self.assertEqual(result.state.project_revision, 2)
        self.assertEqual(compiled_sha(result.state), REVISED_SHA)
        untouched = {k: v for k, v in result.state.modules.items() if k != mid}
        self.assertEqual(untouched, {k: v for k, v in state.modules.items() if k != mid})

    def test_projection_matches_independent_bomc_decode(self):
        state = four_room_state()
        view = project_view(state)
        decoded = independent_read(compile_document(state.document()).payload)
        mods = view["projection"]["modules"]
        faces = [(m, f) for m in mods for f in m["faces"]]
        self.assertEqual(len(faces), decoded["counts"]["faces"])
        self.assertEqual(sum(len(f["triangles"]) for _, f in faces), decoded["triangles"])
        self.assertEqual(len(mods), decoded["counts"]["meshes"])
        used = {(m["moduleId"], x["materialId"]) for m in mods for x in m["materials"]}
        self.assertEqual(len(used), decoded["counts"]["materials"])
        for index, module in enumerate(mods):
            theirs = decoded["meshPositions"][index]
            self.assertEqual([tuple(p) for p in module["positions"]], [tuple(p) for p in theirs])
        for (module, face), theirs in zip(faces, decoded["faces"]):
            self.assertEqual(len(face["triangles"]), theirs["triangles"])
            self.assertEqual(tuple(face["normal"]), theirs["normal"])
            self.assertEqual(face["label"], theirs["label"])
            pos = module["positions"]
            area = 0.0
            for a, b, c in face["triangles"]:
                u = [pos[b][i] - pos[a][i] for i in range(3)]
                w = [pos[c][i] - pos[a][i] for i in range(3)]
                cross = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
                self.assertGreater(sum(x * y for x, y in zip(cross, face["normal"])), 0)
                area += math.sqrt(sum(x * x for x in cross)) / 2
            self.assertTrue(math.isclose(area, theirs["area"], rel_tol=1e-7, abs_tol=1e-7))

    def test_face_ids_unique_stable_and_labels_not_used_as_ids(self):
        view = project_view(four_room_state())
        ids = [f["faceId"] for m in view["projection"]["modules"] for f in m["faces"]]
        self.assertEqual(len(ids), len(set(ids)))
        labels = [f["label"] for m in view["projection"]["modules"] for f in m["faces"]]
        self.assertLess(len(set(labels)), len(labels), "semantic labels are reused and must not be IDs")
        self.assertTrue(all(re.fullmatch(r"house/level/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+", i) for i in ids))
        self.assertEqual(ids, [f["faceId"] for m in project_view(four_room_state())["projection"]["modules"]
                               for f in m["faces"]])

    def test_localized_edit_keeps_other_face_ids_and_triangles(self):
        state = four_room_state()
        before = {m["moduleId"]: m for m in project_view(state)["projection"]["modules"]}
        revised = {m["moduleId"]: m for m in house.build_house(revised=True)["modules"]}
        mid = house.ROOM_IDS["bedroom-a"]
        after_state = apply_transaction(state, make_transaction(
            state, [replace(state, revised[mid])], "window-2")).state
        after = {m["moduleId"]: m for m in project_view(after_state)["projection"]["modules"]}
        self.assertEqual(set(before), set(after))
        for key, module in before.items():
            if key != mid:
                self.assertEqual(module, after[key], key)
        self.assertEqual([f["faceId"] for f in before[mid]["faces"]],
                         [f["faceId"] for f in after[mid]["faces"]])
        self.assertNotEqual(before[mid]["positions"], after[mid]["positions"])

    def test_view_hashes_cover_exact_bytes_and_match_schema(self):
        state = four_room_state()
        view = project_view(state)
        self.assertEqual(view["canonicalIrSha256"], hashlib.sha256(ops.canonical_ir_json(state)).hexdigest())
        self.assertEqual(view["projectionSha256"], hashlib.sha256(ops.projection_json(state)).hexdigest())
        schema = json.loads((ROOT / "schemas/draft-view-v1.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(view)
        self.assertEqual(json.dumps(project_view(state), sort_keys=True), json.dumps(view, sort_keys=True))


class AtomicReciprocalSeam(unittest.TestCase):
    """Fails under the old one-module-only design: a half seam must never commit."""

    def setUp(self):
        self.before, self.after = connected_pair()
        self.state = apply_transaction(EMPTY_STATE, make_transaction(
            EMPTY_STATE, [create(m) for m in self.before.values()], "pair-1")).state
        self.start = snapshot(self.state)

    def reject(self, changes, key):
        with self.assertRaises(OperationError):
            apply_transaction(self.state, make_transaction(self.state, changes, key))
        self.assertEqual(snapshot(self.state), self.start, "rejected transaction mutated state")

    def test_either_half_alone_is_rejected(self):
        self.reject([replace(self.state, self.after["living"])], "half-a")
        self.reject([replace(self.state, self.after["bedroom-a"])], "half-b")

    def test_both_ports_without_owner_or_with_two_owners_rejected(self):
        both = {k: copy.deepcopy(v) for k, v in self.after.items()}
        no_owner = {k: dict(v, ownedSeams=[]) for k, v in both.items()}
        self.reject([replace(self.state, m) for m in no_owner.values()], "no-owner")
        two = copy.deepcopy(both)
        two["bedroom-a"]["ownedSeams"] = [dict(copy.deepcopy(both["living"]["ownedSeams"][0]),
                                               ownerModuleId=two["bedroom-a"]["moduleId"])]
        self.reject([replace(self.state, m) for m in two.values()], "two-owners")

    def test_full_transaction_is_one_revision_and_bytes_unchanged(self):
        result = apply_transaction(self.state, make_transaction(
            self.state, [replace(self.state, m) for m in self.after.values()], "pair-2"))
        self.assertEqual(result.state.project_revision, self.state.project_revision + 1)
        self.assertEqual(len(assemble(result.state.document()["modules"]).seams), 1)
        direct = compile_document({"schemaVersion": "1.0.0",
                                   "modules": sorted(self.after.values(), key=lambda m: m["moduleId"])})
        self.assertEqual(compiled_sha(result.state), direct.sha256)
        self.assertEqual(self.start, snapshot(self.state), "input state must stay immutable")

    def test_removing_a_seam_participant_alone_is_rejected_but_pair_is_allowed(self):
        connected = apply_transaction(self.state, make_transaction(
            self.state, [replace(self.state, m) for m in self.after.values()], "pair-3")).state
        start = snapshot(connected)
        mid = self.after["living"]["moduleId"]
        with self.assertRaisesRegex(OperationError, "still referenced"):
            apply_transaction(connected, make_transaction(connected, [
                {"op": "remove_module", "moduleId": mid, "expectedModuleRevision": 2}], "rm-1"))
        self.assertEqual(snapshot(connected), start)
        both = [{"op": "remove_module", "moduleId": m["moduleId"], "expectedModuleRevision": 2}
                for m in self.after.values()]
        gone = apply_transaction(connected, make_transaction(connected, both, "rm-2")).state
        self.assertEqual(gone.modules, {})
        self.assertEqual(project_view(gone)["projection"]["modules"], [])


class Rejections(unittest.TestCase):
    def setUp(self):
        self.state = four_room_state()
        self.start = snapshot(self.state)
        self.bed = self.state.modules[house.ROOM_IDS["bedroom-a"]]

    def reject(self, txn, pattern=None):
        with self.assertRaisesRegex(OperationError, pattern or ""):
            apply_transaction(self.state, txn)
        self.assertEqual(snapshot(self.state), self.start)

    def txn(self, changes, key="n-1", **extra):
        return dict(make_transaction(self.state, changes, key), **extra)

    def edited(self, fn):
        m = copy.deepcopy(self.bed)
        fn(m)
        m["revision"] += 1
        return replace(self.state, m)

    def test_schema_rejections(self):
        good = self.edited(lambda m: None)
        for bad, pattern in [
            (self.txn([dict(good, op="delete_everything")]), "schema"),
            (self.txn([dict(good, extra=1)]), "schema"),
            (self.txn([]), "schema"),
            (self.txn([good] * 9), "schema"),
            (dict(self.txn([good]), schemaVersion="draft-operation-v2"), "schema"),
            (dict(self.txn([good]), baseProjectRevision=-1), "schema"),
            ({k: v for k, v in self.txn([good]).items() if k != "idempotencyKey"}, "schema"),
            (self.txn([good], key="has space"), "schema"),
        ]:
            self.reject(bad, pattern)

    def test_nonfinite_numbers_and_duplicate_keys(self):
        bad = self.edited(lambda m: m["operations"][1].__setitem__("height", float("nan")))
        self.reject(self.txn([bad]), "non-finite")
        for payload in (b'{"a":NaN}', b'{"a":1,"a":2}', b"\xff", b"{"):
            with self.assertRaises(OperationError):
                ops.parse_transaction(payload)
        with self.assertRaises(OperationError):
            ops.parse_transaction(b" " * (ops.MAX_REQUEST_BYTES + 1))

    def test_missing_seam_owner_and_invalid_references(self):
        self.reject(self.txn([self.edited(lambda m: m.__setitem__("ownedSeams", [])),
                              ]), "assembly rejected")
        livingid = house.ROOM_IDS["living"]
        living = copy.deepcopy(self.state.modules[livingid])
        living["ownedSeams"] = [s for s in living["ownedSeams"] if s["seamId"] != "living-a"]
        living["revision"] += 1
        self.reject(self.txn([replace(self.state, living)]), "no owner|assembly")
        self.reject(self.txn([self.edited(lambda m: m["dependencies"].append(
            {"moduleId": "house/level/ghost", "minRevision": 0}))]), "not in the assembly")
        self.reject(self.txn([self.edited(lambda m: m["operations"][-1].__setitem__(
            "targetWallOpId", "wall-nowhere"))]), "nonexistent wall|target|reject")
        self.reject(self.txn([self.edited(lambda m: m["ports"][0].__setitem__(
            "peer", {"moduleId": "house/level/ghost", "portId": "x"}))]), "assembly")
        self.reject(self.txn([self.edited(lambda m: m["operations"][0].__setitem__("materialId", "nope"))]))

    def test_revision_cas_and_idempotency(self):
        stale = dict(self.txn([self.edited(lambda m: None)]), baseProjectRevision=0)
        self.reject(stale, "stale baseProjectRevision")
        change = self.edited(lambda m: None)
        change["expectedModuleRevision"] = 9
        self.reject(self.txn([change]), "stale expectedModuleRevision")
        wrong = copy.deepcopy(self.bed)  # same revision, not +1
        self.reject(self.txn([replace(self.state, wrong)]), "replacement revision")
        self.reject(self.txn([dict(self.edited(lambda m: None), moduleId=house.ROOM_IDS["bath"])]),
                    "different moduleId")
        new = house._room("bath", False)
        new["moduleId"] = "house/level/second"
        dup = self.txn([create(new), create(new)])
        self.reject(dup, "duplicate moduleId")
        self.reject(self.txn([dict(create(new), expectedModuleRevision=3)]), "must be null")

        request = self.txn([self.edited(lambda m: None)], "same-key")
        first = apply_transaction(self.state, request)
        again = apply_transaction(first.state, copy.deepcopy(request))  # exact retry after commit
        self.assertTrue(again.replayed)
        self.assertIs(again.state, first.state)
        self.assertEqual(again.state.project_revision, self.state.project_revision + 1)
        other = self.txn([self.edited(lambda m: m["operations"][1].__setitem__("height", 2.9))],
                         "same-key")
        with self.assertRaisesRegex(OperationError, "idempotencyKey reused"):
            apply_transaction(first.state, other)

    def test_remove_missing_and_dependents(self):
        self.reject(self.txn([{"op": "remove_module", "moduleId": "house/level/ghost",
                               "expectedModuleRevision": 1}]), "does not exist")
        self.reject(self.txn([{"op": "remove_module", "moduleId": house.ROOM_IDS["living"],
                               "expectedModuleRevision": 1}]), "still referenced")
        roof = {"op": "remove_module", "moduleId": "house/level/roof", "expectedModuleRevision": 1}
        removed = apply_transaction(self.state, self.txn([roof], "roof-rm")).state
        self.assertNotIn("house/level/roof", removed.modules)

    def test_size_caps_unchanged(self):
        huge = self.edited(lambda m: m.__setitem__("provenance", dict(m["provenance"], note="x" * 70_000)))
        self.reject(self.txn([huge]), "64 KiB|schema|assembly")
        self.assertEqual((ops.MAX_CHANGES, ops.MAX_REQUEST_BYTES, ops.MAX_MODULE_BYTES, ops.MAX_PROJECT_BYTES),
                         (8, 262144, 65536, 2097152))
        self.assertEqual((writer_v12.MAX_INPUT_BYTES, writer_v12.MAX_OUTPUT_BYTES), (1_000_000, 2_000_000))
        self.assertEqual((semantic_v12.MAX_FACES, semantic_v12.MAX_VERTICES, semantic_v12.MAX_TRIANGLES,
                          semantic_v12.MAX_MATERIALS, semantic_v12.MAX_STRINGS,
                          semantic_v12.MAX_SOURCE_OPERATIONS),
                         (4096, 8192, 20000, 254, 254, 128))

    def test_compiler_limit_is_enforced_not_raised(self):
        # 130 distinct floors exceed the 128-operation compile budget: rejected, never truncated.
        m = copy.deepcopy(self.bed)
        for i in range(130):
            m = ops.add_floor(m, f"extra-{i}", [[0, 0], [1, 0], [1, 1]], 0.1, 0.0, "flooring")
        m["revision"] = self.bed["revision"] + 1
        self.reject(self.txn([replace(self.state, m)]), "budget|rejected|schema")


def empty_module(mid, parent=None, transform=dag.IDENTITY):
    return {"schemaVersion": "1.0.0", "moduleId": mid, "parentId": parent, "revision": 0,
            "localFrame": {"unit": "m", "handedness": "right", "upAxis": "+Z", "forwardAxis": "+Y",
                           "transform": list(transform)},
            "bounds": {"min": [0, 0, 0], "max": [0, 0, 0]}, "operations": [], "materials": [],
            "ports": [], "ownedSeams": [], "dependencies": [],
            "provenance": {"origin": "synthetic", "generator": "se01-test"}}


FLOOR = {"materialId": "flooring", "rgba": [185, 176, 158, 255], "opacity": 1, "semanticRole": "floor"}
PLASTER = {"materialId": "plaster", "rgba": [233, 232, 226, 255], "opacity": 1, "semanticRole": "wall"}


class TypedHelpers(unittest.TestCase):
    def build(self, transform=dag.IDENTITY, parent=None, mid="lab/annex/hall"):
        state = EMPTY_STATE
        base = empty_module(mid, parent, transform)
        state = apply_transaction(state, make_transaction(state, [create(base)], "seed")).state
        steps = [
            {"tool": "add_floor", "moduleId": mid, "op_id": "floor",
             "footprint": [[0, 0], [4, 0], [4, 1], [1, 1], [1, 3], [0, 3]],  # concave L
             "thickness": 0.15, "elevation": 0, "material_id": "flooring", "material": FLOOR},
            {"tool": "add_wall", "moduleId": mid, "op_id": "wall-south", "path": [[0, 0], [4, 0]],
             "thickness": 0.15, "height": 2.8, "base_elevation": 0, "material_id": "plaster",
             "material": PLASTER},
            {"tool": "add_wall", "moduleId": mid, "op_id": "wall-west", "path": [[0, 0], [0, 3]],
             "thickness": 0.15, "height": 2.8, "base_elevation": 0, "material_id": "plaster"},
            {"tool": "add_opening", "moduleId": mid, "op_id": "door", "target_wall_op_id": "wall-south",
             "offset": 0.5, "width": 0.9, "height": 2.1, "sill_height": 0, "opening_type": "door"},
            {"tool": "add_opening", "moduleId": mid, "op_id": "win", "target_wall_op_id": "wall-west",
             "offset": 1.0, "width": 1.0, "height": 1.0, "sill_height": 0.9, "opening_type": "window"},
        ]
        for n, call in enumerate(steps):
            change = ops.lower_helper(state, call)
            self.assertEqual(change["op"], "replace_module")
            state = apply_transaction(state, make_transaction(state, [change], f"step-{n}")).state
        return state

    def test_helpers_build_concave_floor_walls_and_real_cutouts(self):
        state = self.build()
        view = project_view(state)
        faces = {f["faceId"]: f for f in view["projection"]["modules"][0]["faces"]}
        roles = {f["role"] for f in faces.values()}
        self.assertTrue({"floor", "wall", "door", "window"} <= roles)
        self.assertTrue(all(len(f["triangles"]) >= 1 for f in faces.values()))
        decoded = independent_read(compile_document(state.document()).payload)
        self.assertEqual(decoded["counts"]["faces"], len(faces))
        self.assertGreater(len([f for f in faces if "/floor/" in f]), 0)
        concave = [f for f in faces.values() if f["opId"] == "floor" and f["faceKey"] == "top"][0]
        self.assertGreater(len(concave["triangles"]), 2, "L-shaped floor needs more than a box proxy")

    def test_mirrored_and_nested_transforms_apply_once(self):
        outer = dag.compose(dag.translation(10, -2, 0), dag.mirror("x"))
        inner = dag.compose(dag.rotation_z(90), dag.translation(1, 2, 0))
        parent = empty_module("lab/annex", None, outer)
        base = EMPTY_STATE
        base = apply_transaction(base, make_transaction(base, [create(parent)], "p")).state
        child = empty_module("lab/annex/hall", "lab/annex", inner)
        state = apply_transaction(base, make_transaction(base, [create(child)], "c")).state
        mid = "lab/annex/hall"
        for n, call in enumerate([
            {"tool": "add_floor", "moduleId": mid, "op_id": "floor", "footprint": [[0, 0], [4, 0], [4, 3], [0, 3]],
             "thickness": 0.15, "elevation": 0, "material_id": "flooring", "material": FLOOR},
            {"tool": "add_wall", "moduleId": mid, "op_id": "wall", "path": [[0, 0], [4, 0]], "thickness": 0.15,
             "height": 2.8, "base_elevation": 0, "material_id": "flooring"}]):
            state = apply_transaction(state, make_transaction(
                state, [ops.lower_helper(state, call)], f"s{n}")).state
        module = project_view(state)["projection"]["modules"][0]
        expected = dag.compose(outer, inner)
        for got, want in zip(module["worldTransform"], expected):
            self.assertAlmostEqual(got, want)
        world = [dag.apply_point(tuple(module["worldTransform"]), tuple(p)) for p in module["positions"]]
        decoded = independent_read(compile_document(state.document()).payload)
        lo = [min(p[i] for p in world) for i in range(3)]
        hi = [max(p[i] for p in world) for i in range(3)]
        for got, want in zip(lo + hi, decoded["bounds"]):
            self.assertAlmostEqual(got, want, places=9)
        self.assertTrue(dag.is_mirrored(expected) != dag.is_mirrored(inner))

    def test_helper_rejections_leave_input_unchanged(self):
        state = self.build()
        mid = "lab/annex/hall"
        before = json.dumps(state.modules, sort_keys=True)
        for call in [
            {"tool": "add_floor", "moduleId": mid, "op_id": "floor", "footprint": [[0, 0], [1, 0], [1, 1]],
             "thickness": 0.1, "elevation": 0, "material_id": "flooring"},            # duplicate opId
            {"tool": "add_wall", "moduleId": mid, "op_id": "w2", "path": [[0, 0], [1, 0]], "thickness": 0.1,
             "height": 2, "base_elevation": 0, "material_id": "nope"},               # unknown material
            {"tool": "add_opening", "moduleId": mid, "op_id": "o2", "target_wall_op_id": "floor",
             "offset": 0, "width": 1, "height": 1, "sill_height": 0, "opening_type": "door"},
            {"tool": "update_operation", "moduleId": mid, "op_id": "floor", "kind": "wall-run"},
            {"tool": "update_operation", "moduleId": "lab/annex/none", "op_id": "x", "height": 1},
            {"tool": "run_shell", "moduleId": mid},
            {"tool": "add_wall", "moduleId": mid, "op_id": "w3", "bogus": 1},
        ]:
            with self.assertRaises(OperationError, msg=call["tool"]):
                ops.lower_helper(state, call)
        with self.assertRaises(OperationError):  # opening wider than the wall run
            ops.lower_helper(state, {
                "tool": "add_opening", "moduleId": mid, "op_id": "huge", "target_wall_op_id": "wall-south",
                "offset": 3.9, "width": 5, "height": 1, "sill_height": 0, "opening_type": "window"})
        self.assertEqual(json.dumps(state.modules, sort_keys=True), before)

    def test_update_operation_changes_geometry_and_revision(self):
        state = self.build()
        mid = "lab/annex/hall"
        before = {f["faceId"] for f in project_view(state)["projection"]["modules"][0]["faces"]}
        change = ops.lower_helper(state, {"tool": "update_operation", "moduleId": mid, "op_id": "win",
                                          "width": 1.2})
        new = apply_transaction(state, make_transaction(state, [change], "upd")).state
        self.assertEqual(new.modules[mid]["revision"], state.modules[mid]["revision"] + 1)
        after = {f["faceId"] for f in project_view(new)["projection"]["modules"][0]["faces"]}
        self.assertEqual(before, after, "face IDs must be stable across a parametric edit")
        self.assertNotEqual(compiled_sha(state), compiled_sha(new))

    def test_deterministic_replay_from_same_state(self):
        a, b = self.build(), self.build()
        self.assertEqual(project_view(a), project_view(b))
        self.assertEqual(compiled_sha(a), compiled_sha(b))


class SharedProjection(unittest.TestCase):
    def test_compiler_and_live_view_share_one_implementation(self):
        self.assertIs(semantic_v12._shape_faces, projection._shape_faces)
        self.assertIs(semantic_v12.GeometryEncodingError, projection.GeometryEncodingError)
        self.assertIs(semantic_v12.mesh_intermediate, projection.mesh_intermediate)
        self.assertIs(semantic_v12.collect_module_faces, projection.collect_module_faces)

    def test_no_second_triangulator_or_box_proxy(self):
        users = []
        for path in list((ROOT / "core").rglob("*.py")) + list((ROOT / "bomc").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if re.search(r"\btriangulate_face\b", text) and path.name not in ("triangulation.py",):
                users.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(sorted(users), ["core/project/projection.py"])
        source = (ROOT / "core/project/operations.py").read_text(encoding="utf-8")
        for banned in ("eval(", "exec(", "subprocess", "os.system", "__import__", "pickle"):
            self.assertNotIn(banned, source)

    def test_view_schema_rejects_bad_projection(self):
        schema = Draft202012Validator(json.loads((ROOT / "schemas/draft-view-v1.schema.json").read_text()))
        view = project_view(four_room_state())
        for mutate in (lambda v: v.__setitem__("schemaVersion", "x"),
                       lambda v: v["projection"]["modules"][0]["positions"][0].append(1.0),
                       lambda v: v.__setitem__("canonicalIrSha256", "zz"),
                       lambda v: v["projection"]["modules"][0]["faces"][0].__setitem__("triangles", [])):
            broken = copy.deepcopy(view)
            mutate(broken)
            self.assertFalse(schema.is_valid(broken))

    def test_operation_schema_is_valid_and_accepts_real_transaction(self):
        schema = json.loads((ROOT / "schemas/draft-operation-v1.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        doc = house.build_house()
        txn = make_transaction(EMPTY_STATE, [create(m) for m in doc["modules"]], "schema-ok")
        Draft202012Validator(schema).validate(txn)
        self.assertEqual(len(txn["changes"]), 5)


class OwnerEvidence(unittest.TestCase):
    def test_evidence_matches_pinned_expected_hashes(self):
        from examples import se01_evidence as ev
        parts = ev.build()
        r, _files = ev.receipt(parts)
        self.assertEqual(ev.check(r, ROOT / "docs/stable/owner-handoff/se01-expected.json"), [])
        self.assertEqual(r["baseline"]["bomcSha256"], BASELINE_SHA)
        self.assertEqual(r["revised"]["bomcSha256"], REVISED_SHA)
        self.assertEqual(r["gates"]["owner_windows_face_id_triangle_hash_review"], "NOT_RUN")

    def test_evidence_check_fails_closed_on_tampered_expectation(self):
        import tempfile
        from examples import se01_evidence as ev
        r, _ = ev.receipt(ev.build())
        expected = json.loads((ROOT / "docs/stable/owner-handoff/se01-expected.json").read_text())
        expected["baseline"]["projectionSha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(expected))
            self.assertTrue(ev.check(r, path))


if __name__ == "__main__":
    unittest.main()
