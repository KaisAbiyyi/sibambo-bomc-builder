"""BMB-030 adversarial QA: seeded fuzzing, bad indices, CRC, compression bombs, path traversal, deep DAGs.

Every hostile input must be rejected with the target's documented typed error (a ValueError subclass, or the
storage/session error of the file layers) inside a time and memory budget. Anything else is a defect.
Deterministic: fixed seeds; BMB_FUZZ_ITERS raises the iteration counts. Synthetic data only.
"""
import contextlib
import copy
import io
import json
import os
import random
import shutil
import struct
import sys
import tempfile
import time
import tracemalloc
import unittest
import zlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import bmb_mcp  # noqa: E402
from agentctx import ContextProvider, SessionError, SessionStore, evidence, session as session_mod  # noqa: E402
from bomc.adapter.writer_v12 import encode_graph  # noqa: E402
from bomc.compiler.graph_to_bomc import compile_definition_graph, compile_document  # noqa: E402
from cli import bmb  # noqa: E402
from core.assembly import AssemblyError, assemble  # noqa: E402
from core.geometry import roof, semantics  # noqa: E402
from core.geometry.floor import build_floor_slab  # noqa: E402
from core.geometry.openings import build_wall_with_openings  # noqa: E402
from core.geometry.triangulation import triangulate_face  # noqa: E402
from core.geometry.wall import build_wall_run  # noqa: E402
from core.graph import dag  # noqa: E402
from core.storage import JournalStore, StorageError, journal as journal_mod  # noqa: E402
from core.validator import validate_assembly  # noqa: E402
from tests.interop import mutate  # noqa: E402
from tests.interop.reader import ENTRY, HEADER, Rejected, read  # noqa: E402
from tests.qa import harness as h  # noqa: E402
from tools.bomc_fixture_harness import InvalidBomc, inspect_container  # noqa: E402

N = h.ITERATIONS
GOLD = ROOT / "tests" / "interop" / "goldens"
TWO_ROOMS = json.loads((ROOT / "examples" / "module-ir-two-rooms.json").read_text())
FLOOR_DOC = json.loads((ROOT / "examples" / "bmb020-semantic-floor.json").read_text())
OPS = {o["opId"]: o for o in TWO_ROOMS["modules"][0]["operations"]}


def golden(name):
    return (GOLD / f"{name}.bomc").read_bytes()


class Fuzz(unittest.TestCase):
    def clean(self, target, doc, seed, allowed=(ValueError,), iterations=None, **limits):
        defects = h.run(target, doc, random.Random(seed), iterations or N, allowed, **limits)
        self.assertEqual(defects, [], "\n".join(h.describe(defects, 8)))


class StructuredInputFuzzTests(Fuzz):
    """Hostile Module IR and primitive parameters reach only typed errors."""

    def test_assemble(self):
        self.clean(lambda d: assemble(d["modules"]), TWO_ROOMS, 1, (AssemblyError,))

    def test_validate_assembly_never_raises(self):
        self.clean(lambda d: validate_assembly(d["modules"]), TWO_ROOMS, 2, ())

    def test_compile_document(self):
        self.clean(compile_document, TWO_ROOMS, 3)
        self.clean(compile_document, FLOOR_DOC, 4)

    def test_face_semantics_validation(self):
        self.clean(semantics.validate_module_faces, FLOOR_DOC["modules"][0], 5)

    def test_floor_wall_opening(self):
        self.clean(build_floor_slab, OPS["floor-1"], 6)
        self.clean(build_wall_run, OPS["east-wall"], 7)
        self.clean(lambda d: build_wall_with_openings(d["wall"], [d["door"]]),
                   {"wall": OPS["east-wall"], "door": OPS["door-1"]}, 8, (ValueError, KeyError))  # KeyError: harness deletes our own wrapper keys

    def test_roof_ceiling_stair_triangulation(self):
        shell = {"kind": "roof-shell", "opId": "r", "footprint": [[0, 0], [6, 0], [6, 4], [0, 4]], "profile": "gable",
                 "eaveElevation": 3, "thickness": 0.2, "rise": 1.5, "ridgeAxis": "x"}
        self.clean(roof.build_roof_shell, shell, 9)
        self.clean(roof.build_ceiling_shell, dict(shell, kind="ceiling-shell", profile="flat", rise=0, ridgeAxis=None), 10)
        self.clean(roof.build_stair_flight, {"kind": "stair-flight", "opId": "s", "origin": [0, 0, 0.2], "direction": "+x",
                                              "width": 1, "treadDepth": 0.3, "riserHeight": 0.16, "stepCount": 4}, 11)
        face = {"v": [[0, 0, 0], [6, 0, 0], [6, 6, 0], [0, 6, 0]], "holes": [[[1, 1, 0], [2, 1, 0], [2, 2, 0], [1, 2, 0]]],
                "n": [0, 0, 1]}
        self.clean(lambda d: triangulate_face(d["v"], holes=d["holes"], normal=d["n"]), face, 12, (ValueError, KeyError))

    def test_writer_graph(self):
        graph = {"schemaVersion": "bmb-writer-graph-v1", "name": "x", "nodes": [
            {"id": "root", "kind": "root", "name": "r", "parentId": None, "transform": list(dag.IDENTITY)},
            {"id": "g1", "kind": "group", "name": "g", "parentId": "root", "transform": list(dag.translation(1, 2, 3))}]}
        self.clean(encode_graph, graph, 13)

    def test_definition_graph_api_with_hostile_arguments(self):
        rng, bad = random.Random(14), []
        names = ["a", "b", "c", "d"]
        for it in range(N):
            graph = dag.DefinitionGraph()
            try:
                for _ in range(rng.randrange(1, 12)):
                    pick = lambda: rng.choice(names + [rng.choice(h.JUNK)])  # noqa: E731
                    matrix = lambda: rng.choice([dag.IDENTITY, dag.mirror("x"), rng.choice(h.JUNK),  # noqa: E731
                                                 [rng.choice(h.JUNK) for _ in range(16)], list(dag.IDENTITY)[:15]])
                    kind = rng.randrange(6)
                    if kind == 0:
                        graph.add_definition(pick())
                    elif kind == 1:
                        graph.add_instance(pick(), pick(), pick(), matrix())
                    elif kind == 2:
                        graph.set_transform(pick(), pick(), matrix())
                    elif kind == 3:
                        graph.remove_instance(pick(), pick())
                    elif kind == 4:
                        graph.instances(pick())
                    else:
                        graph.world_transforms(pick())
            except dag.GraphError:
                pass
            except BaseException as exc:  # noqa: BLE001
                bad.append((it, type(exc).__name__, str(exc)[:60]))
        self.assertEqual(bad[:5], [])

    def test_deeply_nested_values_in_every_field_are_typed_rejections(self):
        for depth in (50, 1500, 30_000):
            for build in (h.deep_list, h.deep_dict):
                for trail in (("provenance",), ("operations", 0, "footprint"), ("materials", 0, "rgba"),
                              ("faceAnnotations",), ("bounds", "min"), ("localFrame", "transform")):
                    doc = copy.deepcopy(FLOOR_DOC)
                    node = doc["modules"][0]
                    for key in trail[:-1]:
                        node = node[key]
                    node[trail[-1]] = build(depth)
                    with self.subTest(depth=depth, shape=build.__name__, field=trail):
                        for target in (compile_document, lambda d: assemble(d["modules"]),
                                       lambda d: semantics.validate_module_faces(d["modules"][0])):
                            try:
                                with h.budget(5, 96):
                                    target(doc)
                            except ValueError:
                                pass                      # typed rejection
                            except BaseException as exc:  # noqa: BLE001
                                self.fail(f"{type(exc).__name__}: {str(exc)[:80]}")
                            else:
                                self.assertLessEqual(depth, 50)   # beyond a sane depth nothing may be accepted

    def test_huge_integers_and_non_json_numbers_are_rejected_not_overflowed(self):
        for big in (10 ** 400, -10 ** 400, 2 ** 1024):
            for key, value in (("thickness", big), ("height", big), ("baseElevation", big), ("offset", big)):
                op = copy.deepcopy(OPS["east-wall"] if key != "offset" else OPS["door-1"])
                op[key] = value
                with self.subTest(key=key):
                    with self.assertRaises(ValueError):
                        build_wall_run(op) if key != "offset" else build_wall_with_openings(OPS["east-wall"], [op])

    def test_decode_authored_module_bytes(self):
        rng, good = random.Random(15), json.dumps(FLOOR_DOC["modules"][0]).encode()
        bad = {}
        for i in range(N):
            data = bytearray(good)
            for _ in range(rng.randrange(1, 6)):
                data[rng.randrange(len(data))] = rng.randrange(256)
            if rng.random() < 0.3:
                data = bytearray(h.deep_json(rng.choice((50, 2000, 50_000))).encode())
            try:
                with h.budget(5):
                    semantics.decode_authored_module(bytes(data))
            except semantics.SemanticFaceError:
                pass
            except BaseException as exc:  # noqa: BLE001
                bad.setdefault(type(exc).__name__, i)
        self.assertEqual(bad, {})


def dependency_chain(n, forward=True):
    """n modules; module i depends on i-1 (forward) or i+1 (reversed, so sorted traversal recurses deepest)."""
    mods = []
    for i in range(n):
        m = evidence._module(f"chain/m-{i:04d}", at=(i * 3, 0, 0), parent="chain/g", walls=False)
        dep = i - 1 if forward else i + 1
        if 0 <= dep < n:
            m["dependencies"] = [{"moduleId": f"chain/m-{dep:04d}", "minRevision": 0}]
        mods.append(m)
    return mods


def parent_chain(n, forward=True):
    mods = []
    for i in range(n):
        parent = (f"pc/m-{i - 1:04d}" if i else "pc/g") if forward else (f"pc/m-{i + 1:04d}" if i < n - 1 else "pc/g")
        mods.append(evidence._module(f"pc/m-{i:04d}", at=(1, 0, 0), parent=parent, walls=False))
    return mods


class DeepGraphTests(unittest.TestCase):
    def test_a_dependency_chain_as_deep_as_the_module_cap_assembles_in_either_order(self):
        for forward in (True, False):
            with self.subTest(forward=forward):
                with h.budget(5, 96):
                    result = assemble(dependency_chain(1024, forward))
                self.assertEqual(len(result.order), 1024)
                self.assertEqual(result.order[0], "chain/m-0000" if forward else "chain/m-1023")  # dependencies first
                with h.budget(10, 128):
                    self.assertTrue(validate_assembly(dependency_chain(1024, forward)).ok)

    def test_a_cycle_at_the_end_of_a_very_deep_chain_is_still_a_typed_error(self):
        mods = dependency_chain(1024, forward=False)
        mods[-1]["dependencies"] = [{"moduleId": "chain/m-0000", "minRevision": 0}]
        with h.budget(5, 96):
            with self.assertRaises(AssemblyError) as ctx:
                assemble(mods)
        self.assertIn("dependency cycle", str(ctx.exception))
        report = validate_assembly(mods)
        self.assertFalse(report.ok)

    def test_parent_chains_deeper_than_the_budget_are_rejected_in_both_orders(self):
        for forward in (True, False):
            for n in (31, 32, 33, 1024):
                with self.subTest(forward=forward, n=n):
                    try:
                        with h.budget(5, 96):
                            assemble(parent_chain(n, forward))
                    except AssemblyError as exc:
                        self.assertGreater(n, 31)
                        self.assertIn("deeper than", str(exc)) if not forward else None
                    except BaseException as exc:  # noqa: BLE001
                        self.fail(f"{type(exc).__name__}: {exc}")

    def test_wide_and_deep_definition_graphs_hit_budgets_not_memory_or_time(self):
        graph = dag.DefinitionGraph()
        for i in range(dag.MAX_DEFINITIONS):
            graph.add_definition(f"d-{i:03d}")
        for i in range(dag.MAX_DEFINITIONS - 1):  # a chain 256 deep
            graph.add_instance(f"d-{i:03d}", "next", f"d-{i + 1:03d}")
        with h.budget(5, 96):
            with self.assertRaises(dag.GraphError):
                graph.world_transforms("d-000")                       # depth budget
        fan = dag.DefinitionGraph()
        for name in ("top", "mid", "leaf"):
            fan.add_definition(name)
        for i in range(dag.MAX_INSTANCES_PER_DEFINITION):
            fan.add_instance("top", f"m-{i:03d}", "mid")
            fan.add_instance("mid", f"l-{i:03d}", "leaf")
        with h.budget(10, 128):
            with self.assertRaises(dag.GraphError):
                fan.world_transforms("top")                            # 65 536 expanded instances > 10 000
            with self.assertRaises(ValueError):
                compile_definition_graph(fan, "top")                   # writer node budget, not an allocation spike

    def test_every_definition_cycle_shape_is_detected(self):
        graph = dag.DefinitionGraph()
        for name in ("a", "b", "c"):
            graph.add_definition(name)
        graph.add_instance("a", "i", "b")
        graph.add_instance("b", "i", "c")
        for owner, target in (("c", "a"), ("c", "b"), ("c", "c"), ("b", "a")):
            with self.assertRaises(dag.CycleError):
                graph.add_instance(owner, "back", target)
        self.assertIsNone(graph.find_cycle())


class BomcBytesTests(Fuzz):
    names = ("floor-front-back", "two-room-door-seam", "minimal-root", "wall-window-cutout", "mirrored-sheared-floors")

    def damage(self, rng, blob):
        kind = rng.randrange(6)
        if kind == 0:
            data = bytearray(blob)
            for _ in range(rng.randrange(1, 8)):
                data[rng.randrange(len(data))] = rng.randrange(256)
            return bytes(data)
        if kind == 1:
            return blob[:rng.randrange(len(blob) + 1)]
        if kind == 2:                                        # payload damage with the CRC repaired
            sid = rng.choice([e["id"] for e in mutate.parse(blob)["entries"]])

            def change(d):
                for _ in range(rng.randrange(1, 6)):
                    if d:
                        d[rng.randrange(len(d))] = rng.randrange(256)
            return mutate.edit_section(blob, sid, change)
        if kind == 3:                                        # directory field damage
            data = bytearray(blob)
            n = HEADER.unpack_from(blob)[5]
            data[HEADER.size + rng.randrange(n) * ENTRY.size + rng.randrange(ENTRY.size)] = rng.randrange(256)
            return bytes(data)
        if kind == 4:                                        # deflate with lying sizes
            def edit(model):
                e = rng.choice(model["entries"])
                raw = e["data"]
                payload = raw if rng.random() < 0.5 else b"\0" * rng.choice((1 << 10, 1 << 20, 1 << 26))
                e.update(codec=1, data=zlib.compress(payload), raw=rng.choice((len(raw), len(raw) + 1, 1 << 20, 1 << 31, 0xFFFFFFFF)))
            return mutate.rebuild(blob, edit)
        data = bytearray(blob)
        data[8:12] = rng.randbytes(4)
        return bytes(data)

    def test_readers_reject_everything_with_their_typed_error(self):
        rng, bad, started = random.Random(31), {}, 0
        blobs = {n: golden(n) for n in self.names}
        for i in range(N * 3):
            data = self.damage(rng, blobs[rng.choice(self.names)])
            for tag, fn, allowed in (("reader", read, Rejected), ("container", inspect_container, InvalidBomc)):
                try:
                    with h.budget(2):
                        fn(data)
                except allowed:
                    pass
                except BaseException as exc:  # noqa: BLE001
                    bad.setdefault((tag, type(exc).__name__), (i, str(exc)[:70]))
        self.assertEqual(bad, {})

    def test_compression_bombs_are_refused_without_inflating(self):
        base = golden("floor-front-back")
        for megabytes in (1, 64, 512):
            for lie in ("honest", "small", "huge"):
                stream = zlib.compress(b"\0" * (megabytes << 20), 9)

                def edit(model, stream=stream, megabytes=megabytes, lie=lie):
                    e = next(x for x in model["entries"] if x["id"] == 7)
                    e.update(codec=1, data=stream, raw={"honest": megabytes << 20, "small": 64, "huge": 0xFFFFFFFF}[lie])
                payload = mutate.rebuild(base, edit)
                with self.subTest(megabytes=megabytes, lie=lie):
                    with h.budget(3, 8):                            # a bomb must not be inflated into memory
                        with self.assertRaises(Rejected):           # the Builder profile has no compression at all
                            read(payload)
                    within_budget = megabytes == 1 and lie == "honest"   # 1 MiB expands inside the 2 MiB container budget
                    with h.budget(3, 8):
                        if within_budget:
                            inspect_container(payload)
                        else:
                            with self.assertRaises(InvalidBomc):
                                inspect_container(payload)

    def test_bad_zlib_streams_are_typed_rejections(self):
        base = golden("floor-front-back")
        good = zlib.compress(b"\0" * 4096)
        for label, stream in (("truncated", good[:-4]), ("corrupt", good[:5] + b"\xff" * 8 + good[13:]), ("trailing", good + b"junk"),
                              ("empty", b""), ("raw garbage", b"\x78\x9c" + b"\xde\xad" * 50)):
            def edit(model, stream=stream):
                e = next(x for x in model["entries"] if x["id"] == 7)
                e.update(codec=1, data=stream, raw=4096)
            with self.subTest(label):
                with self.assertRaises(InvalidBomc):
                    inspect_container(mutate.rebuild(base, edit))

    def test_bad_indices_in_every_table_are_rejected(self):
        """Boundary values written over each fixed-width field of the index-bearing sections (CRC repaired)."""
        base, rejected, accepted = golden("two-room-door-seam"), 0, 0
        values = (0, 1, 0x7F, 0x80, 0xFE, 0xFF, 0x100, 0xFFFF, 0x10000, 0x7FFFFFFF, 0xFFFFFFFF)
        for sid in (5, 6, 8, 11, 12, 13):
            size = len(next(e for e in mutate.parse(base)["entries"] if e["id"] == sid)["data"])
            for at in range(0, min(size, 240)):
                for value in values[:6] if at % 4 else values:
                    def change(d, at=at, value=value):
                        width = 1 if value <= 0xFF else 4
                        if at + width <= len(d):
                            d[at:at + width] = value.to_bytes(width, "little")
                    mutated = mutate.edit_section(base, sid, change)
                    try:
                        with h.budget(2):
                            read(mutated)
                        accepted += 1
                    except Rejected:
                        rejected += 1
        self.assertGreater(rejected, 1500)
        self.assertLess(accepted, rejected)                      # most index damage is invalid; benign rewrites may remain valid

    def test_crc_damage_is_always_caught(self):
        base = golden("two-room-door-seam")
        for entry in range(HEADER.unpack_from(base)[5]):
            sid, _, _, offset, stored, *_ = ENTRY.unpack_from(base, HEADER.size + entry * ENTRY.size)
            for at in range(offset, offset + stored, max(1, stored // 40)):
                damaged = mutate.patch(base, at, bytes([base[at] ^ 0xA5]))
                with self.assertRaises(Rejected):
                    read(damaged)
                with self.assertRaises(InvalidBomc):
                    inspect_container(damaged)


class StorageFileFuzzTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def journal_fixture(self):
        store = JournalStore.open(self.base / "j")
        store.create_module("a/b")
        store.apply("a/b", 0, "k1", [{"op": "add", "id": "w", "data": {"h": 1}}, {"op": "add", "id": "x", "data": {"t": [1, 2]}}])
        store.apply("a/b", 1, "k2", [{"op": "replace", "id": "w", "data": {"h": 2}}])
        store.rollback("a/b", 2, "rb", 1)
        return (self.base / "j" / "modules" / "a__b" / "journal.jsonl").read_bytes()

    @staticmethod
    def rechain(entries):
        prev, out = journal_mod.GENESIS, []
        for e in entries:
            e = copy.deepcopy(e)
            e["prev"] = prev
            e["hash"] = journal_mod._digest(e)
            prev = e["hash"]
            out.append(journal_mod._canonical(e).encode())
        return b"\n".join(out) + b"\n"

    def test_journal_files(self):
        good = self.journal_fixture()
        lines = [json.loads(x) for x in good.split(b"\n")[:-1]]
        rng, bad = random.Random(41), {}
        for i in range(N):
            kind = rng.randrange(4)
            if kind == 0:
                data = bytearray(good)
                for _ in range(rng.randrange(1, 6)):
                    pos = rng.randrange(len(data))
                    op = rng.randrange(3)
                    if op == 0:
                        data[pos] = rng.randrange(256)
                    elif op == 1:
                        del data[pos:pos + rng.randrange(1, 40)]
                    else:
                        data[pos:pos] = rng.randbytes(rng.randrange(1, 40))
                data = bytes(data)
            elif kind == 1:
                data = good[:rng.randrange(len(good))]
            elif kind == 2:                                   # structure damage with every hash re-chained
                entries = copy.deepcopy(lines)
                at = rng.randrange(len(entries))
                entries[at] = h.mutate(entries[at], rng)
                try:
                    data = self.rechain(entries)
                except (TypeError, ValueError, RecursionError):
                    continue
            else:                                             # deep nesting inside an otherwise valid-looking line
                data = good + h.deep_json(rng.choice((100, 1500, 20_000, 200_000))).encode() + b"\n"
            root = self.base / f"case-{i}"
            target = root / "modules" / "a__b"
            target.mkdir(parents=True)
            (target / "journal.jsonl").write_bytes(data)
            try:
                with h.budget(5):
                    JournalStore.open(root)
            except StorageError:
                pass
            except BaseException as exc:  # noqa: BLE001
                bad.setdefault(type(exc).__name__, (i, kind, str(exc)[:60]))
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(bad, {})

    def test_session_files(self):
        store = JournalStore.open(self.base / "sj")
        store.create_module("a/b")
        sessions = SessionStore(self.base / "s")
        sessions.create("x1").checkpoint(ContextProvider(store))
        good = sessions.path("x1").read_bytes()
        lines = [json.loads(x) for x in good.split(b"\n")[:-1]]

        def rechain(entries):
            prev, out = session_mod.GENESIS, []
            for e in entries:
                e = copy.deepcopy(e)
                e["prev"], e["hash"] = prev, None
                e["hash"] = session_mod._entry_hash(e)
                prev = e["hash"]
                out.append(session_mod.canonical(e).encode())
            return b"\n".join(out) + b"\n"

        rng, bad = random.Random(42), {}
        for i in range(N):
            kind = rng.randrange(4)
            if kind == 0:
                data = bytearray(good)
                for _ in range(rng.randrange(1, 6)):
                    data[rng.randrange(len(data))] = rng.randrange(256)
                data = bytes(data)
            elif kind == 1:
                data = good[:rng.randrange(len(good))]
            elif kind == 2:
                entries = copy.deepcopy(lines)
                at = rng.randrange(len(entries))
                entries[at] = h.mutate(entries[at], rng)
                try:
                    data = rechain(entries)
                except (TypeError, ValueError, RecursionError):
                    continue
            else:
                data = good + h.deep_json(rng.choice((100, 1500, 20_000, 60_000))).encode() + b"\n"
            case = SessionStore(self.base / f"c{i}")
            case.root.mkdir(parents=True)
            os.chmod(case.root, 0o700)
            (case.root / "x1.jsonl").write_bytes(data)
            os.chmod(case.root / "x1.jsonl", 0o600)
            try:
                with h.budget(5):
                    case.open("x1")
            except SessionError:
                pass
            except BaseException as exc:  # noqa: BLE001
                bad.setdefault(type(exc).__name__, (i, kind, str(exc)[:60]))
            shutil.rmtree(case.root.parent, ignore_errors=True)
        self.assertEqual(bad, {})

    def test_oversize_files_and_entry_counts_are_refused_before_parsing(self):
        good = self.journal_fixture()
        root = self.base / "big"
        target = root / "modules" / "a__b"
        target.mkdir(parents=True)
        path = target / "journal.jsonl"
        path.write_bytes(good)
        with mock.patch.object(journal_mod, "MAX_FILE_BYTES", len(good) - 1):
            with self.assertRaises(StorageError):
                JournalStore.open(root)
        with mock.patch.object(journal_mod, "MAX_ENTRIES", 1):
            with self.assertRaises(StorageError):
                JournalStore.open(root)
        with mock.patch.object(journal_mod, "MAX_LINE_BYTES", 10):
            with self.assertRaises(StorageError):
                JournalStore.open(root)


HOSTILE_IDS = (
    "../x", "..\\x", "a/../b", "a/./b", "/etc/passwd", "C:\\Windows\\x", "\\\\server\\share\\x", "a//b", "a/b/", "/a/b",
    "a/b\n", "a/b\r", "a/b\x00", "a/b ", "a/b.", "a/b:stream", "a／b", "ａ/ｂ", "%2e%2e/x", "a/%2e%2e/b", "A/B", "a/B",
    "a\\b", "~/x", "a/b/../../..", "x" * 5000, "", " ", "\t", "a/\u202eb", "a/b\ud800", "..", ".", "a/..", "CON", "nul",
)
WINDOWS_DEVICES = ("con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt9", "CON", "Nul")


class PathTraversalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.outer = Path(self._tmp.name)
        self.root = self.outer / "project"
        self.root.mkdir(mode=0o700)

    def listing(self):
        return sorted(p.relative_to(self.outer).as_posix() for p in self.outer.rglob("*"))

    def assertContained(self):
        outside = [e for e in self.listing() if e != "project" and not e.startswith("project/")]
        self.assertEqual(outside, [], "something was created outside the project root")

    def test_module_and_key_ids_never_escape_the_project_root(self):
        from core.identity.store import BLOCK_ID_PATTERN, KEY_PATTERN, MODULE_ID_PATTERN
        store = JournalStore.open(self.root)
        store.create_module("safe/mod")
        provider = ContextProvider(store)
        for hostile in HOSTILE_IDS:
            with self.subTest(hostile=repr(hostile)[:40]):
                self.assertIsNone(MODULE_ID_PATTERN.match(hostile))     # the corpus holds no valid module id
                for call in (lambda: store.create_module(hostile),
                             lambda: store.apply(hostile, 0, "k", [{"op": "add", "id": "b", "data": {}}]),
                             lambda: store.rollback(hostile, 1, "k", 0),
                             lambda: store.snapshot(hostile),
                             lambda: provider.module(hostile),
                             lambda: provider.manifest(cursor=hostile),
                             lambda: provider.revision_entries(hostile)):
                    with self.assertRaises(ValueError):
                        call()
                # key and block positions are never path components; a rejection must match their documented pattern
                for position, pattern, op in (("key", KEY_PATTERN, lambda s: store.apply("safe/mod", 99, s, [{"op": "add", "id": "b", "data": {}}])),
                                              ("block", BLOCK_ID_PATTERN, lambda s: store.apply("safe/mod", 99, "k", [{"op": "add", "id": s, "data": {}}]))):
                    try:
                        op(hostile)
                    except ValueError as exc:
                        if pattern.match(hostile):                      # valid shape: the only allowed error is the stale revision
                            self.assertIn("stale", str(exc))
                    else:
                        self.fail(f"{position} {hostile!r} was accepted at a stale revision")
        self.assertEqual(self.listing(), ["project", "project/modules", "project/modules/safe__mod", "project/modules/safe__mod/journal.jsonl"])
        self.assertContained()

    def test_session_ids_never_escape_and_never_name_windows_devices(self):
        sessions = SessionStore(self.root)
        before = self.listing()
        for hostile in HOSTILE_IDS + WINDOWS_DEVICES:
            with self.subTest(hostile=repr(hostile)[:40]):
                with self.assertRaises(SessionError):
                    sessions.create(hostile)
                with self.assertRaises(SessionError):
                    sessions.open(hostile)
                with self.assertRaises(SessionError):
                    sessions.path(hostile)
        self.assertEqual(self.listing(), before)
        sessions.create("com-1")                                     # ordinary look-alikes stay valid
        sessions.create("console")
        self.assertEqual(sorted(sessions.sessions()), ["com-1", "console"])

    def test_graph_and_assembly_ids_reject_traversal(self):
        graph = dag.DefinitionGraph()
        for hostile in HOSTILE_IDS:
            if dag.ID_PATTERN.match(hostile):
                continue                                             # a plain lowercase slug ("nul") is not a path component here
            with self.assertRaises(dag.GraphError):
                graph.add_definition(hostile)
        for hostile in HOSTILE_IDS:
            module = copy.deepcopy(TWO_ROOMS["modules"][1])
            module["moduleId"] = hostile
            with self.assertRaises(AssemblyError):
                assemble([module])

    def test_cli_arguments_cannot_name_other_paths(self):
        for hostile in HOSTILE_IDS:
            for argv in (["--root", str(self.root), "create", "--module-id", hostile],
                         ["--root", str(self.root), "inspect", "--module-id", hostile],
                         ["--root", str(self.root), "rollback", "--module-id", hostile, "--expected-revision", "1",
                          "--key", "k", "--to-revision", "0"]):
                out = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    try:
                        code = bmb.main(argv, io.BytesIO(b""))
                    except SystemExit:
                        continue
                reply = json.loads(out.getvalue()) if out.getvalue().strip() else {"ok": False}
                self.assertFalse(reply["ok"], (hostile, reply))
                self.assertNotEqual(reply.get("error", {}).get("code"), "INTERNAL_ERROR", (hostile, reply))
        self.assertContained()

    def test_mcp_tool_arguments_cannot_name_other_paths(self):
        for hostile in HOSTILE_IDS:
            for name, args in (("bmb_create_module", {"moduleId": hostile}), ("bmb_inspect_module", {"moduleId": hostile}),
                               ("bmb_edit_module", {"moduleId": hostile, "expectedRevision": 0, "idempotencyKey": "k",
                                                    "ops": [{"op": "add", "id": "b", "data": {}}]}),
                               ("bmb_validate_journals", {"moduleId": hostile})):
                with self.assertRaises(bmb_mcp.ToolFailure):
                    bmb_mcp._validate_args(name, args)


META = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "qa", "version": "1"}}


class ErrorMessageTests(unittest.TestCase):
    """A rejection message is built before the check it reports on, from the hostile value itself.

    `repr` of a very deeply nested value raises RecursionError, and where that happens depends on the platform's C
    stack: the 5 000-deep fuzz values passed on Linux and failed on Windows. 200 000 levels fail everywhere, so this
    test does not depend on the platform. Every entry point that names an id, key or role must answer with its typed
    error, and the message must stay short."""

    DEPTH = 200_000

    def deep(self):
        return h.deep_list(self.DEPTH)

    def typed(self, call, *errors):
        errors = errors or (ValueError,)
        with self.assertRaises(errors) as caught:
            call()
        self.assertLess(len(str(caught.exception)), 1000)

    def test_floor_and_wall_identifiers(self):
        for key in ("opId", "materialId", "role"):
            with self.subTest(key=key):
                self.typed(lambda: build_floor_slab(dict(OPS["floor-1"], **{key: self.deep()})))

    def test_assembly_and_graph_identifiers(self):
        deep = self.deep()
        self.typed(lambda: assemble([dict(TWO_ROOMS["modules"][0], moduleId=deep)]), AssemblyError)
        graph = dag.DefinitionGraph()
        graph.add_definition("a")
        for call in (lambda: graph.add_definition(deep), lambda: graph.add_instance(deep, "i", "a", dag.IDENTITY),
                     lambda: graph.add_instance("a", deep, "a", dag.IDENTITY), lambda: graph.instances(deep),
                     lambda: graph.world_transforms(deep), lambda: graph.remove_instance("a", deep)):
            self.typed(call, dag.GraphError)

    def test_journal_identity_and_session_identifiers(self):
        deep = self.deep()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir(mode=0o700)
            store = JournalStore.open(root)
            store.create_module("safe/mod")
            provider = ContextProvider(store)
            block = [{"op": "add", "id": "b", "data": {}}]
            for call in (lambda: store.create_module(deep), lambda: store.snapshot(deep), lambda: store.rollback(deep, 1, "k", 0),
                         lambda: store.apply(deep, 0, "k", block), lambda: store.apply("safe/mod", 0, deep, block),
                         lambda: store.apply("safe/mod", 0, "k", [{"op": "add", "id": deep, "data": {}}]),
                         lambda: store.apply("safe/mod", deep, "k", block), lambda: store.rollback("safe/mod", 1, "k", deep),
                         lambda: provider.module(deep), lambda: provider.revision_entries(deep)):
                self.typed(call)
            self.typed(lambda: SessionStore(root).path(deep))


class HarnessBudgetTests(unittest.TestCase):
    """The resource budgets must hold on every exit path, in particular when the target ends in a typed rejection
    (the common case for hostile input). The checks used to sit after the try/finally, so any exception skipped them."""

    def test_a_slow_typed_rejection_is_over_budget(self):
        with self.assertRaises(h.BudgetExceeded):
            with h.budget(seconds=0.001):
                time.sleep(0.05)
                raise ValueError("typed rejection")

    def test_an_allocating_typed_rejection_is_over_budget_and_tracing_is_restored(self):
        self.assertFalse(tracemalloc.is_tracing())
        with self.assertRaises(h.BudgetExceeded):
            with h.budget(seconds=30, peak_mb=1):
                blob = bytearray(8 * 1024 * 1024)
                raise ValueError("typed rejection")
        self.assertFalse(tracemalloc.is_tracing(), "the harness must leave tracemalloc as it found it")
        del blob

    def test_a_fast_typed_rejection_passes_through_unchanged(self):
        with self.assertRaises(ValueError) as caught:
            with h.budget(seconds=5, peak_mb=64):
                raise ValueError("typed rejection")
        self.assertEqual(str(caught.exception), "typed rejection")

    def test_a_fast_normal_return_is_accepted(self):
        with h.budget(seconds=5, peak_mb=64):
            sum(range(1000))

    def test_run_reports_an_over_budget_typed_rejection_as_a_defect(self):
        def slow(_doc):
            time.sleep(0.05)
            raise ValueError("typed rejection")

        def fast(_doc):
            raise ValueError("typed rejection")

        self.assertEqual([i for i, _ in h.run(slow, {"a": 1}, random.Random(0), 3, (ValueError,), seconds=0.001)], [0, 1, 2])
        self.assertTrue(all(isinstance(e, h.BudgetExceeded) for _, e in h.run(slow, {"a": 1}, random.Random(0), 3, (ValueError,), seconds=0.001)))
        self.assertEqual(h.run(fast, {"a": 1}, random.Random(0), 3, (ValueError,), seconds=5), [])

    def test_a_defect_that_is_also_over_budget_keeps_the_original_exception_in_the_chain(self):
        with self.assertRaises(h.BudgetExceeded) as caught:
            with h.budget(seconds=0.001):
                time.sleep(0.05)
                raise TypeError("a real defect")
        self.assertIsInstance(caught.exception.__context__, TypeError)


def rpc(method, params=None, ident=1):
    return {"jsonrpc": "2.0", "id": ident, "method": method, "params": dict({"_meta": META}, **(params or {}))}


class FrameFuzzTests(unittest.TestCase):
    """The stdio loop and the CLI never crash, never overrun the response cap and never leak an internal error."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "project"
        self.root.mkdir(mode=0o700)

    def serve(self, frames):
        out = io.BytesIO()
        with mock.patch.object(bmb_mcp, "_perform", return_value={"ok": True, "stub": True}):
            bmb_mcp.run(self.root, writes=True, reader=io.BytesIO(frames), writer=out)
        return [json.loads(line) for line in out.getvalue().splitlines()], out.getvalue()

    def test_mutated_requests_always_get_a_bounded_valid_reply(self):
        bases = [rpc("server/discover"), rpc("tools/list", ident=2),
                 rpc("tools/call", {"name": "bmb_edit_module", "arguments": {"moduleId": "a/b", "expectedRevision": 0,
                     "idempotencyKey": "k", "ops": [{"op": "add", "id": "w", "data": {"h": 1}}]}}, 3),
                 rpc("tools/call", {"name": "bmb_validate_assembly", "arguments": {"document": TWO_ROOMS}}, 4)]
        rng, frames, count = random.Random(51), [], 0
        for _ in range(N * 2):
            try:
                frames.append(json.dumps(h.mutate(rng.choice(bases), rng), allow_nan=False).encode() + b"\n")
            except (TypeError, ValueError, RecursionError):
                continue
            count += 1
        with h.budget(30, 192):
            replies, raw = self.serve(b"".join(frames))
        self.assertEqual(len(replies), len([f for f in frames if self.expects_reply(f)]))
        for line in raw.splitlines():
            self.assertLessEqual(len(line), bmb_mcp.MAX_RESPONSE)
        for reply in replies:
            self.assertEqual(reply["jsonrpc"], "2.0")
            self.assertTrue(("result" in reply) != ("error" in reply))

    @staticmethod
    def expects_reply(frame):
        try:
            packet = json.loads(frame)
        except ValueError:
            return True
        return not (isinstance(packet, dict) and packet.get("jsonrpc") == "2.0" and isinstance(packet.get("method"), str)
                    and "id" not in packet)

    def test_garbage_and_oversize_frames(self):
        rng = random.Random(52)
        garbage = [bytes(rng.randrange(256) for _ in range(rng.randrange(0, 600))).replace(b"\n", b" ") + b"\n"
                   for _ in range(200)]
        garbage += [h.deep_json(n).encode() + b"\n" for n in (10, 40, 1000, 100_000)]
        garbage += [b'{"jsonrpc":"2.0","id":1,"method":"x","params":' + h.deep_json(100_000).encode() + b"}\n", b"\n", b"{}\n", b"[]\n",
                    b"null\n", b'"x"\n', b"1\n"]
        with h.budget(20, 128):
            replies, raw = self.serve(b"".join(garbage))
        self.assertGreater(len(replies), 100)
        self.assertTrue(all("error" in r for r in replies))
        oversize = b'{"jsonrpc":"2.0","id":1,"method":"x","params":{"p":"' + b"x" * (bmb_mcp.MAX_FRAME + 10) + b'"}}\n'
        replies, _ = self.serve(oversize + json.dumps(rpc("tools/list")).encode() + b"\n")
        self.assertEqual([r["error"]["code"] for r in replies], [-32600])      # closes the stream, nothing after it runs
        replies, _ = self.serve(json.dumps(rpc("tools/list")).encode())          # no terminating newline
        self.assertEqual([r["error"]["code"] for r in replies], [-32600])

    def test_a_huge_unsupported_version_echo_cannot_overrun_the_response_cap(self):
        meta = dict(META, **{"io.modelcontextprotocol/protocolVersion": "v" * (bmb_mcp.MAX_FRAME - 700)})
        frame = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}}).encode() + b"\n"
        self.assertLessEqual(len(frame), bmb_mcp.MAX_FRAME)
        replies, raw = self.serve(frame)
        self.assertLessEqual(len(raw.splitlines()[0]), bmb_mcp.MAX_RESPONSE)
        self.assertEqual(len(replies), 1)

    def test_cli_never_reports_an_internal_error_for_hostile_input(self):
        root = self.root / "cli"
        root.mkdir(mode=0o700)

        def call(argv, payload):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = bmb.main(argv, io.BytesIO(payload))
            return code, json.loads(out.getvalue())

        self.assertTrue(call(["--root", str(root), "create", "--module-id", "a/b"], b"")[1]["ok"])
        rng, internal = random.Random(53), []
        for i in range(N):
            kind = rng.randrange(3)
            if kind == 0:
                try:
                    payload = json.dumps(h.mutate({"ops": [{"op": "add", "id": "w1", "data": {"h": 1}}], "minRevisions": {}}, rng),
                                         allow_nan=True).encode()
                except (TypeError, ValueError, RecursionError):
                    continue
                argv = ["--root", str(root), "edit", "--module-id", "a/b", "--expected-revision", "0", "--key", f"k{i}"]
            elif kind == 1:
                try:
                    payload = json.dumps(h.mutate(TWO_ROOMS, rng)).encode()
                except (TypeError, ValueError, RecursionError):
                    continue
                argv = ["validate", "--assembly-stdin"]
            else:
                payload = rng.randbytes(rng.randrange(0, 300)) if rng.random() < 0.7 else h.deep_json(rng.choice((50, 5000, 90_000))).encode()
                argv = ["--root", str(root), "edit", "--module-id", "a/b", "--expected-revision", "0", "--key", "kk"]
            with h.budget(5):
                code, reply = call(argv, payload)
            if not reply["ok"] and reply["error"]["code"] == "INTERNAL_ERROR":
                internal.append(i)
        self.assertEqual(internal, [])


if __name__ == "__main__":
    unittest.main()
