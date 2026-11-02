"""BMB-011 assembly merge and seam ownership tests: synthetic data only."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.assembly import (  # noqa: E402
    AssemblyError, DuplicateOwnershipError, assemble, merge_assemblies)
from core.graph import dag  # noqa: E402

LIV, HALL, BATH = "house/floor-1/living", "house/floor-1/hall", "house/floor-1/bath"


def port(pid, peer, seam, normal, at, width=0.9, height=2.1, turn=0):
    """Port frame convention: +Y is the width direction, +Z the height; both tangent to `normal`."""
    return {"portId": pid, "kind": "doorway", "normal": list(normal),
            "localTransform": list(dag.compose(dag.translation(*at), dag.rotation_z(turn))), "width": width, "height": height,
            "peer": {"moduleId": peer[0], "portId": peer[1]} if peer else None, "seamId": seam}


def module(mid, at=(0, 0, 0), parent="house/floor-1", ports=(), seams=(), deps=(), revision=1, transform=None, ops=("east-wall",)):
    return {"schemaVersion": "1.0.0", "moduleId": mid, "parentId": parent, "revision": revision,
            "localFrame": {"unit": "m", "handedness": "right", "upAxis": "+Z", "forwardAxis": "+Y",
                           "transform": list(transform or dag.translation(*at))},
            "bounds": {"min": [0, 0, 0], "max": [1, 1, 1]}, "materials": [],
            "operations": [{"kind": "wall-run", "opId": o} for o in ops],
            "ports": list(ports), "ownedSeams": list(seams),
            "dependencies": [{"moduleId": d, "minRevision": r} for d, r in deps],
            "provenance": {"origin": "synthetic"}}


def seam(sid, owner, other, op="east-wall"):
    return {"seamId": sid, "ownerModuleId": owner, "participants": [owner, other], "surfaceOpId": op}


def _rotation_x(degrees):
    import math
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return (1.0, 0.0, 0.0, 0.0, 0.0, c, -s, 0.0, 0.0, s, c, 0.0, 0.0, 0.0, 0.0, 1.0)


def pair():
    """living (0..4) owns the east seam shared with hall (4..6)."""
    liv = module(LIV, ports=[port("hall-door", (HALL, "living-door"), "east", (1, 0, 0), (4, 1, 0))],
                 seams=[seam("east", LIV, HALL)])
    hall = module(HALL, at=(4, 0, 0), ports=[port("living-door", (LIV, "hall-door"), "east", (-1, 0, 0), (0, 1, 0))],
                  deps=[(LIV, 1)], revision=0)
    return liv, hall


def chain():
    liv, hall = pair()
    hall["ports"].append(port("bath-door", (BATH, "hall-door"), "north", (0, 1, 0), (1, 3, 0), turn=90))
    hall["ownedSeams"].append(seam("north", HALL, BATH))
    bath = module(BATH, at=(4, 3, 0), ports=[port("hall-door", (HALL, "bath-door"), "north", (0, -1, 0), (1, 0, 0), turn=90)],
                  deps=[(HALL, 0)], revision=0)
    return [bath, hall, liv]


class MergeTests(unittest.TestCase):
    def test_example_ir_assembles(self):
        ir = json.loads((ROOT / "examples" / "module-ir-two-rooms.json").read_text())
        a = assemble(ir["modules"])
        self.assertEqual(a.order, (LIV, HALL))
        self.assertEqual([(s.seam_id, s.owner, s.participants) for s in a.seams],
                         [("east-shared", LIV, (HALL, LIV))])
        self.assertEqual(a.neighbours(HALL), [LIV])

    def test_three_modules_one_graph_with_single_owner_per_seam(self):
        a = assemble(chain())
        self.assertEqual(a.order, (LIV, HALL, BATH))
        self.assertEqual({s.seam_id: s.owner for s in a.seams}, {"east": LIV, "north": HALL})
        self.assertEqual(a.neighbours(HALL), [BATH, LIV])
        self.assertEqual([s.seam_id for s in a.owned_by(HALL)], ["north"])
        self.assertEqual(len(a.seams_of(HALL)), 2)

    def test_result_is_independent_of_input_order_and_detached(self):
        mods = chain()
        first = assemble(mods)
        again = assemble(list(reversed(mods)))
        self.assertEqual((first.order, first.seams, first.world_transforms), (again.order, again.seams, again.world_transforms))
        self.assertEqual(list(first.modules), sorted(first.modules))
        mods[0]["revision"] = 99
        self.assertEqual(first.modules[BATH]["revision"], 0)

    def test_nested_parent_transforms_compose(self):
        liv, hall = pair()
        grp = module("house/floor-1", parent=None, at=(10, 20, 0), ports=[], ops=())
        liv["parentId"] = hall["parentId"] = "house/floor-1"
        a = assemble([grp, liv, hall])  # the group is a module: both rooms move by (10,20,0) together
        self.assertEqual(a.world_transforms[LIV][3:12:4], (10.0, 20.0, 0.0))
        self.assertEqual(a.world_transforms[HALL][3:12:4], (14.0, 20.0, 0.0))

    def test_mirrored_module_keeps_ports_consistent(self):
        liv, hall = pair()
        # mirror the hall about x at its own origin: local +x runs west, so its port at local (-2, 1) faces +x in world
        hall["localFrame"]["transform"] = list(dag.compose(dag.translation(6, 0, 0), dag.mirror("x")))
        hall["ports"][0]["localTransform"] = list(dag.translation(2, 1, 0))
        hall["ports"][0]["normal"] = [1, 0, 0]  # mirrored into world -x, opposite to living's +x
        a = assemble([liv, hall])
        self.assertEqual(len(a.seams), 1)
        hall["ports"][0]["normal"] = [-1, 0, 0]  # now world +x: not opposite
        with self.assertRaises(AssemblyError):
            assemble([liv, hall])

    def test_rotated_module_normals_follow_the_frame(self):
        liv, hall = pair()
        hall["localFrame"]["transform"] = list(dag.compose(dag.translation(4, 0, 0), dag.rotation_z(90)))
        # local port frame: origin (1, 0, 0), +Y (width) along local -x so it is tangent to the local normal +y
        hall["ports"][0]["localTransform"] = list(dag.compose(dag.translation(1, 0, 0), dag.rotation_z(90)))
        hall["ports"][0]["normal"] = [0, 1, 0]                                 # rotates to world -x
        self.assertEqual(len(assemble([liv, hall]).seams), 1)
        hall["ports"][0]["normal"] = [0, -1, 0]
        with self.assertRaises(AssemblyError):
            assemble([liv, hall])

    def test_sheared_parent_uses_inverse_transpose_for_normals_and_forward_for_tangents(self):
        k = 0.5
        group = module("house/floor-1", parent=None, transform=dag.shear_xy(k), ports=[], ops=())
        liv, hall = pair()
        a = assemble([group, liv, hall])  # world normals (1,-k,0) and (-1,k,0), tangents (k,1,0): still perpendicular
        self.assertEqual(len(a.seams), 1)
        hall["ports"][0]["normal"] = [-1, 0.5, 0]                              # no longer opposite once sheared
        with self.assertRaises(AssemblyError):
            assemble([group, liv, hall])

    def test_world_space_span_includes_scale_of_module_frames(self):
        liv, hall = pair()
        liv["localFrame"]["transform"] = list(dag.scale(1, 2, 1))              # living's 0.9 m opening is 1.8 m in the assembly
        hall["localFrame"]["transform"] = list(dag.translation(4, 1, 0))      # frames still coincide at (4, 2, 0)
        with self.assertRaises(AssemblyError):
            assemble([liv, hall])                                              # 1.8 m against 0.9 m
        hall["ports"][0]["width"] = 1.8
        self.assertEqual(len(assemble([liv, hall]).seams), 1)
        hall["ports"][0]["width"] = 1.8005                                     # inside the 1 mm tolerance
        self.assertEqual(len(assemble([liv, hall]).seams), 1)
        hall["ports"][0]["width"] = 1.802
        with self.assertRaises(AssemblyError):
            assemble([liv, hall])

    def test_nonuniform_scaled_group_keeps_spans_consistent(self):
        group = module("house/floor-1", parent=None, transform=dag.scale(1, 2, 3), ports=[], ops=())
        liv, hall = pair()
        a = assemble([group, liv, hall])                                       # both spans scale by the same factors
        self.assertEqual(len(a.seams), 1)
        hall["ports"][0]["height"] = 2.0                                       # 2.0 vs 2.1 local height
        with self.assertRaises(AssemblyError):
            assemble([group, liv, hall])

    def test_span_mismatch_under_shear(self):
        k = 0.5
        group = module("house/floor-1", parent=None, transform=dag.shear_xy(k), ports=[], ops=())
        liv, hall = pair()
        hall["ports"][0]["localTransform"] = list(dag.compose(dag.translation(0, 1, 0), dag.scale(1, 1.5, 1)))
        with self.assertRaises(AssemblyError):
            assemble([group, liv, hall])                                       # hall's frame stretches its width by 1.5
        hall["ports"][0]["width"] = 0.6                                        # 0.6 * 1.5 = 0.9
        self.assertEqual(len(assemble([group, liv, hall]).seams), 1)

    def test_operation_count_matches_the_schema_limit(self):
        liv, hall = pair()
        liv["operations"] = [{"kind": "wall-run", "opId": "east-wall"}] + \
            [{"kind": "wall-run", "opId": f"op-{i}"} for i in range(9999)]
        self.assertEqual(len(assemble([liv, hall]).seams), 1)                  # 10 000 operations
        liv["operations"].append({"kind": "wall-run", "opId": "op-extra"})
        with self.assertRaises(AssemblyError):
            assemble([liv, hall])                                              # 10 001

    def test_peer_frame_rotated_about_the_normal_is_rejected(self):
        liv, hall = pair()
        hall["ports"][0]["localTransform"] = list(dag.compose(dag.translation(0, 1, 0), _rotation_x(90)))
        # same origin, width, height and normal, but its width/height axes are swapped
        self.bad(liv, hall)
        hall["ports"][0]["localTransform"] = list(dag.compose(dag.translation(0, 1, 0), _rotation_x(180)))
        self.assertEqual(len(assemble([liv, hall]).seams), 1)                   # 180 degrees keeps the span lines

    def test_port_frame_axes_must_be_tangent_to_the_normal(self):
        liv, hall = pair()
        hall["ports"][0]["localTransform"] = list(dag.compose(dag.translation(0, 1, 0), dag.rotation_z(45)))
        self.bad(liv, hall)

    def bad(self, *mods):
        with self.assertRaises(AssemblyError):
            assemble(list(mods))

    def test_merge_assemblies_disjoint_union(self):
        left = assemble(list(pair()))
        other = [module("tower/floor-1/a", parent="tower/floor-1"), module("tower/floor-1/b", parent="tower/floor-1")]
        right = assemble(other)
        both = merge_assemblies(left, right)
        self.assertEqual(sorted(both.modules), sorted([LIV, HALL, "tower/floor-1/a", "tower/floor-1/b"]))
        self.assertEqual(both.seams, left.seams)
        with self.assertRaises(AssemblyError):
            merge_assemblies(left, left)
        with self.assertRaises(AssemblyError):
            merge_assemblies()


class MalformedInputTests(unittest.TestCase):
    JUNK = ([], {}, None, "x", 1.5, True, [[]], {"a": [1]}, -1, "", [1, 2], 10 ** 400)

    def paths(self, node, trail=()):
        yield trail
        if isinstance(node, dict):
            for k, v in node.items():
                yield from self.paths(v, trail + (k,))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from self.paths(v, trail + (i,))

    def test_every_leaf_replaced_by_junk_raises_only_assembly_error(self):
        base = chain()
        checked = 0
        for mi in range(len(base)):
            for trail in self.paths(base[mi]):
                if not trail:
                    continue
                for junk in self.JUNK:
                    mods = copy.deepcopy(base)
                    node = mods[mi]
                    for key in trail[:-1]:
                        node = node[key]
                    node[trail[-1]] = junk
                    try:
                        assemble(mods)
                    except AssemblyError:
                        pass
                    checked += 1
        self.assertGreater(checked, 1000)

    def test_unhashable_nested_values_are_assembly_errors(self):
        liv, hall = pair()
        liv["ownedSeams"][0]["participants"] = [[1], [2]]
        with self.assertRaises(AssemblyError):
            assemble([liv, hall])
        liv, hall = pair()
        liv["operations"][0]["opId"] = ["east-wall"]
        with self.assertRaises(AssemblyError):
            assemble([liv, hall])
        liv, hall = pair()
        liv["ownedSeams"][0]["surfaceOpId"] = ["east-wall"]
        with self.assertRaises(AssemblyError):
            assemble([liv, hall])

    def test_composed_singular_world_transform_is_an_assembly_error(self):
        thin = dag.scale(1e-4, 1, 1)  # valid alone (det 1e-4), singular once three are composed (1e-12)
        a = module("g/a", parent=None, transform=thin, ports=[], ops=())
        b = module("g/b", parent="g/a", transform=thin, ports=[], ops=())
        c = module("g/c", parent="g/b", transform=thin, ports=[], ops=())
        assemble([a, b])
        with self.assertRaises(AssemblyError):
            assemble([a, b, c])
        huge = dag.scale(1e5, 1, 1)
        with self.assertRaises(AssemblyError):
            assemble([module("g/x", parent=None, transform=huge, ports=[], ops=()),
                      module("g/y", parent="g/x", transform=huge, ports=[], ops=())])


class OwnershipTests(unittest.TestCase):
    def bad(self, mods, exc=AssemblyError):
        with self.assertRaises(exc):
            assemble(mods)

    def test_both_participants_claiming_the_wall_is_rejected(self):
        liv, hall = pair()
        hall["ownedSeams"].append(seam("east", HALL, LIV))
        self.bad([liv, hall], DuplicateOwnershipError)

    def test_no_owner_is_rejected(self):
        liv, hall = pair()
        liv["ownedSeams"] = []
        self.bad([liv, hall])

    def test_ownership_must_be_declared_by_the_owner_and_a_participant(self):
        liv, hall = pair()
        liv["ownedSeams"][0]["ownerModuleId"] = HALL                       # claims for someone else
        self.bad([liv, hall])
        liv, hall = pair()
        liv["ownedSeams"][0]["participants"] = [HALL, BATH]                # owner not a participant
        self.bad([liv, hall])
        liv, hall = pair()
        liv["ownedSeams"][0]["participants"] = [LIV, BATH]                 # wrong other side
        self.bad([liv, hall, module(BATH, at=(0, 9, 0))])

    def test_seam_surface_and_participants_must_exist(self):
        liv, hall = pair()
        liv["ownedSeams"][0]["surfaceOpId"] = "missing-wall"
        self.bad([liv, hall])
        liv, hall = pair()
        liv["ownedSeams"][0]["participants"] = [LIV, "house/floor-9/ghost"]
        self.bad([liv, hall])
        liv, hall = pair()
        liv["ownedSeams"][0]["participants"] = [LIV, LIV]
        self.bad([liv, hall])

    def test_orphan_and_duplicate_seams_are_rejected(self):
        liv, hall = pair()
        liv["ownedSeams"].append(seam("spare", LIV, HALL))
        self.bad([liv, hall])
        liv, hall = pair()
        liv["ownedSeams"].append(seam("east", LIV, HALL))
        self.bad([liv, hall])

    def test_peers_must_name_the_same_seam(self):
        liv, hall = pair()
        hall["ports"][0]["seamId"] = "west"
        self.bad([liv, hall])

    def test_third_module_cannot_own_the_seam(self):
        liv, hall = pair()
        liv["ownedSeams"] = []
        third = module(BATH, at=(0, 9, 0), seams=[seam("east", BATH, LIV)])
        self.bad([liv, hall, third])


class PortTests(unittest.TestCase):
    def bad(self, mutate):
        liv, hall = pair()
        mutate(liv, hall)
        with self.assertRaises(AssemblyError):
            assemble([liv, hall])

    def test_peer_problems(self):
        self.bad(lambda l, h: h["ports"][0]["peer"].update(portId="nope"))
        self.bad(lambda l, h: h["ports"][0]["peer"].update(moduleId=BATH))
        self.bad(lambda l, h: h.update(ports=[]))                                   # no point back
        self.bad(lambda l, h: l["ports"][0]["peer"].update(moduleId=LIV, portId="hall-door"))  # self
        self.bad(lambda l, h: l["ports"][0].update(peer=None))                      # peer without seam link
        self.bad(lambda l, h: l["ports"][0].update(seamId=None))
        self.bad(lambda l, h: l["ports"][0].update(width=0))

    def test_geometry_agreement_in_world_space(self):
        self.bad(lambda l, h: h["ports"][0].update(normal=[1, 0, 0]))               # same direction
        self.bad(lambda l, h: h["ports"][0].update(normal=[0, 0, 0]))
        self.bad(lambda l, h: h["ports"][0].update(normal=[-1, 0.01, 0]))           # slightly off axis
        self.bad(lambda l, h: h["localFrame"].update(transform=list(dag.translation(4, 0.5, 0))))  # frames apart
        self.bad(lambda l, h: h["ports"][0].update(width=1.2))
        self.bad(lambda l, h: h["ports"][0].update(height=2.5))
        self.bad(lambda l, h: h["ports"][0].update(normal=[-1, 0]))

    def test_duplicate_port_ids(self):
        self.bad(lambda l, h: l["ports"].append(copy.deepcopy(l["ports"][0])))


class LinkTests(unittest.TestCase):
    def bad(self, mods):
        with self.assertRaises(AssemblyError):
            assemble(mods)

    def test_identity_rules(self):
        liv, hall = pair()
        self.bad([liv, hall, copy.deepcopy(liv)])
        self.bad([])
        self.bad("modules")
        self.bad([liv, "x"])
        self.bad([dict(liv, moduleId="Bad")])
        self.bad([dict(liv, schemaVersion="2.0.0"), hall])
        self.bad([dict(liv, revision=-1), hall])
        self.bad([dict(liv, revision=True), hall])
        self.bad([dict(liv, parentId=LIV), hall])
        self.bad([dict(liv, extra=float("nan")), hall])

    def test_dependencies(self):
        liv, hall = pair()
        hall["dependencies"] = [{"moduleId": LIV, "minRevision": 2}]          # stale
        self.bad([liv, hall])
        liv, hall = pair()
        hall["dependencies"] = [{"moduleId": "house/floor-9/ghost", "minRevision": 0}]
        self.bad([liv, hall])
        liv, hall = pair()
        hall["dependencies"] = [{"moduleId": HALL, "minRevision": 0}]
        self.bad([liv, hall])
        liv, hall = pair()
        liv["dependencies"] = [{"moduleId": HALL, "minRevision": 0}]          # living <-> hall cycle
        self.bad([liv, hall])
        liv, hall = pair()
        hall["dependencies"] = [{"moduleId": LIV, "minRevision": 1}] * 2
        self.bad([liv, hall])

    def test_parent_cycle_and_bad_transform(self):
        a = module("g/a", parent="g/b", ports=[], ops=())
        b = module("g/b", parent="g/a", ports=[], ops=())
        self.bad([a, b])
        liv, hall = pair()
        hall["localFrame"]["transform"] = list(dag.scale(0, 1, 1))
        self.bad([liv, hall])

    def test_parent_depth_budget(self):
        mods = [module(f"g/m{i}", parent=f"g/m{i + 1}" if i < 40 else None, ports=[], ops=()) for i in range(41)]
        self.bad(mods)


if __name__ == "__main__":
    unittest.main()
