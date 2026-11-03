"""BMB-021 Builder-side semantic certification: committed goldens, strict reader, corruption matrix.

Everything here runs against the Builder's own compiler and its own strict reader.
It does NOT execute the original Editor E4 or Model-Eval loaders (private repositories,
NOT_RUN) and proves nothing about section 241 handling by those consumers.
"""
import json
import math
import os
import struct
import subprocess
import sys
import tracemalloc
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bomc.compiler.graph_to_bomc import CompileError, compile_document  # noqa: E402
from tests.interop import fixtures, goldens, mutate  # noqa: E402
from tests.interop.reader import ENTRY, HEADER, MAGIC, MAX_BYTES, Rejected, read  # noqa: E402

GOLDENS = ROOT / "tests" / "interop" / "goldens"
MATRIX = ROOT / "compatibility" / "bomc-1.2-matrix.json"
PINNED = {
    "concave-l-floor": "8ca1c7aa803b",
    "floor-front-back": "6d652bbd9410",
    "minimal-root": "f414a9260bb4",
    "mirrored-sheared-floors": "f026b5a76258",
    "nested-shared-definitions": "6e481586741a",
    "two-room-door-seam": "a21109c137b9",
}


def golden(name):
    return (GOLDENS / f"{name}.bomc").read_bytes()


def det(m):
    return (m[0] * (m[4] * m[8] - m[5] * m[7]) - m[3] * (m[1] * m[8] - m[2] * m[7])
            + m[6] * (m[1] * m[5] - m[2] * m[4]))


class GoldenSuiteTests(unittest.TestCase):
    def test_committed_bytes_and_manifest_match_a_fresh_compile(self):
        goldens.check(GOLDENS)

    def test_binary_hashes_are_pinned(self):
        manifest = json.loads((GOLDENS / "manifest.json").read_text())
        self.assertEqual({f["name"]: f["sha256"][:12] for f in manifest["fixtures"]}, PINNED)
        for f in manifest["fixtures"]:
            self.assertEqual(goldens.sha256(golden(f["name"])), f["sha256"])
        # the two fixtures that PR #55 published as Actions artifacts
        full = {f["name"]: f["sha256"] for f in manifest["fixtures"]}
        self.assertEqual(full["floor-front-back"], "6d652bbd941059750dd2e26464d9c8104a1a8e827ef6f8e3328208a782f7ab8e")
        self.assertEqual(full["two-room-door-seam"], "a21109c137b943e5afc4a50776dcbf2eb3def36b93eaa63e951a9311ee46f632")

    def test_cold_processes_with_different_hash_seeds_reproduce_every_binary(self):
        code = ("import json,sys; sys.path.insert(0, %r); from tests.interop import goldens; "
                "print(json.dumps({n: goldens.sha256(b) for n, b in goldens.build_all().items()}))" % str(ROOT))
        want = {f["name"]: f["sha256"] for f in json.loads((GOLDENS / "manifest.json").read_text())["fixtures"]}
        for seed in ("1", "424242"):
            env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
            self.assertEqual(json.loads(out.stdout), want, msg=f"PYTHONHASHSEED={seed}")

    def test_every_golden_reads_with_the_pinned_semantics(self):
        for name in PINNED:
            with self.subTest(name):
                s = read(golden(name))
                self.assertEqual(sum(s["counts"].values()) > 0, True)
                self.assertEqual(s["counts"]["definitions"], s["counts"]["instances"])
        minimal, nested = read(golden("minimal-root")), read(golden("nested-shared-definitions"))
        self.assertEqual((minimal["sections"], minimal["counts"]["faces"]), ((1, 2, 11, 12, 13, 17, 20), 0))
        self.assertEqual(nested["counts"]["instances"], 8)          # root + wings + shared rooms occurrences
        self.assertEqual(nested["sections"], minimal["sections"])

    def test_front_back_materials_and_labels(self):
        s = read(golden("floor-front-back"))
        self.assertEqual((s["counts"]["faces"], s["triangles"], s["counts"]["materials"]), (6, 12, 2))
        self.assertEqual(s["colors"], [(145, 145, 145, 255), (190, 120, 80, 245)])      # concrete, finish (authored RGBA)
        self.assertEqual(s["opacity"], [65535, 58982])                                # 1.0 and 0.9 as uint16
        top = [f for f in s["faces"] if f["label"] == "Study floor top"]
        self.assertEqual(len(top), 1)
        self.assertEqual((top[0]["front"], top[0]["back"]), (1, 0))                    # front = finish, back = concrete
        self.assertTrue(math.isclose(top[0]["normal"][2], 1.0))
        self.assertEqual(sum(1 for f in s["faces"] if None not in (f["front"], f["back"]) and f["front"] != f["back"]), 1)

    def test_concave_face_is_a_single_planar_loop_triangulated_to_the_same_area(self):
        s = read(golden("concave-l-floor"))  # the reader already proves triangle area == loop area per face
        tops = [f for f in s["faces"] if f["normal"][2] > 0.99]
        self.assertEqual([f["loop"] for f in tops], [6])
        self.assertGreaterEqual(tops[0]["triangles"], 4)
        self.assertEqual(s["bounds"], (0.0, 0.0, 0.0, 4.0, 3.0, 0.2))

    def test_mirrored_and_sheared_transforms_survive_exactly_once(self):
        s = read(golden("mirrored-sheared-floors"))
        self.assertTrue(any(det(m) < 0 for m in s["transforms"]))           # the mirror
        self.assertIn((1.0, 0.0, 0.0, 0.25, 1.0, 0.0, 0.0, 0.0, 1.0, 3.0, 0.0, 0.0), s["transforms"])  # shear + offset
        self.assertEqual(s["bounds"], (-5.25, 0.0, 0.0, -3.0, 1.0, 0.2))     # recomputed from the instance chain
        nested = read(golden("nested-shared-definitions"))
        self.assertTrue(any(det(m) < 0 for m in nested["transforms"]))
        self.assertTrue(any(m[3] != 0.0 for m in nested["transforms"]))

    def test_door_cutout_and_single_owned_seam(self):
        s = read(golden("two-room-door-seam"))
        self.assertEqual((s["counts"]["meshes"], s["counts"]["faces"], s["triangles"]), (2, 58, 116))
        floors = [f for f in s["faces"] if f["normal"][2] > 0.99 and f["surface"] == 2]
        self.assertEqual(len(floors), 2)                                    # one slab top per room, shared wall emitted once
        ir = json.loads((ROOT / "examples" / "module-ir-two-rooms.json").read_text())
        ir["modules"][1]["ownedSeams"].append(dict(ir["modules"][0]["ownedSeams"][0], ownerModuleId=ir["modules"][1]["moduleId"]))
        with self.assertRaises(CompileError):
            compile_document(ir)                                            # a second owner of the same wall never compiles

    def test_unsupported_sources_fail_closed(self):
        for name, (doc, reason) in fixtures.unsupported_sources().items():
            with self.subTest(name, reason=reason):
                with self.assertRaises(CompileError):
                    compile_document(doc)

    def test_manifest_and_matrix_make_no_consumer_claims(self):
        manifest = json.loads((GOLDENS / "manifest.json").read_text())
        self.assertEqual(set(manifest["consumerStatus"].values()), {"NOT_RUN"})
        matrix = json.loads(MATRIX.read_text())
        block = matrix["builderSideCertification"]
        self.assertEqual(block["status"], "PASS_BUILDER_SIDE_ONLY")
        self.assertEqual({f["name"]: f["sha256"] for f in block["fixtures"]},
                         {f["name"]: f["sha256"] for f in manifest["fixtures"]})
        self.assertEqual(set(block["consumerPairings"].values()), {"NOT_RUN"})
        case = next(c for c in matrix["cases"] if c["id"] == "BUILDER12_ANY")
        self.assertEqual(case["status"], "NOT_RUN")
        self.assertEqual(manifest["unsupportedByBuilderSource"], block["unsupportedByBuilderSource"])


def rejected(testcase, payload, label, needle=None):
    with testcase.subTest(label):
        with testcase.assertRaises(Rejected) as ctx:
            read(payload)
        if needle:
            testcase.assertIn(needle, str(ctx.exception))


class ContainerCorruptionTests(unittest.TestCase):
    def setUp(self):
        self.base = golden("floor-front-back")
        self.room = golden("two-room-door-seam")

    def test_untouched_files_and_identity_rebuild_are_accepted(self):
        for payload in (self.base, self.room):
            read(payload)
            self.assertEqual(mutate.rebuild(payload, lambda m: None), payload)

    def test_header_fields(self):
        b = self.base
        for label, payload, needle in [
            ("magic", mutate.patch(b, 0, b"WRNG"), "magic"),
            ("version 1.1", mutate.patch(b, 10, struct.pack("<H", 1)), "version"),
            ("version 1.3", mutate.patch(b, 10, struct.pack("<H", 3)), "version"),
            ("version 2.0", mutate.patch(b, 8, struct.pack("<H", 2)), "version"),
            ("endian marker", mutate.patch(b, 12, struct.pack("<I", 0x04030201)), "endian"),
            ("unknown flag", mutate.patch(b, 16, struct.pack("<I", 0x80000011)), "flags"),
            ("no flags", mutate.patch(b, 16, struct.pack("<I", 0)), "flags"),
            ("count zero", mutate.patch(b, 20, struct.pack("<I", 0)), "directory"),
            ("count too large", mutate.patch(b, 20, struct.pack("<I", 4096)), "directory"),
            ("count past the file", mutate.patch(b, 20, struct.pack("<I", 100)), None),
            ("directory offset", mutate.patch(b, 24, struct.pack("<Q", 40)), "directory"),
        ]:
            rejected(self, payload, label, needle)

    def test_directory_entries(self):
        b = self.base
        for index in range(HEADER.unpack_from(b)[5]):
            at = HEADER.size + index * ENTRY.size
            rejected(self, mutate.patch(b, at + 2, b"\x02"), f"codec 2 in entry {index}")
            rejected(self, mutate.patch(b, at + 2, b"\x01"), f"deflate in entry {index}", "compression")
            rejected(self, mutate.patch(b, at + 3, b"\x01"), f"section flags in entry {index}")
            rejected(self, mutate.patch(b, at + 12, struct.pack("<I", 0x7fffffff)), f"raw size in entry {index}")
            rejected(self, mutate.patch(b, at + 16, struct.pack("<I", 0x7fffffff)), f"item count in entry {index}")
            rejected(self, mutate.patch(b, at + 20, struct.pack("<I", 0)), f"CRC in entry {index}", "CRC")
            rejected(self, mutate.patch(b, at + 4, struct.pack("<I", len(b) + 8)), f"offset past the file in entry {index}")
            rejected(self, mutate.patch(b, at + 8, struct.pack("<I", 0xffffffff)), f"stored size in entry {index}")
        first = ENTRY.unpack_from(b, HEADER.size)
        rejected(self, mutate.patch(b, HEADER.size + 4, struct.pack("<I", first[3] + 1)), "misaligned offset")
        rejected(self, mutate.patch(b, HEADER.size + 4, struct.pack("<I", HEADER.size)), "payload inside the directory")
        second = ENTRY.unpack_from(b, HEADER.size + ENTRY.size)
        rejected(self, mutate.patch(b, HEADER.size + ENTRY.size + 4, struct.pack("<I", first[3])), "overlapping payloads")
        rejected(self, mutate.patch(b, HEADER.size + ENTRY.size, struct.pack("<H", ENTRY.unpack_from(b, HEADER.size)[0])),
                 "duplicate section id")
        self.assertGreater(second[0], first[0])

    def test_payload_corruption_without_crc_repair(self):
        for payload in (self.base, self.room):
            for index in range(HEADER.unpack_from(payload)[5]):
                sid, _, _, offset, stored, *_ = ENTRY.unpack_from(payload, HEADER.size + index * ENTRY.size)
                for at in (offset, offset + stored // 2, offset + stored - 1):
                    rejected(self, mutate.patch(payload, at, bytes([payload[at] ^ 0x5a])), f"section {sid} byte {at}", "CRC")

    def test_truncation_at_every_length_and_trailing_bytes(self):
        for cut in range(len(self.base)):
            with self.subTest(cut=cut):
                with self.assertRaises(Rejected):
                    read(self.base[:cut])
        for extra in (b"\0", b"\0" * 7, b"junk", b"\xff" * 4096):
            rejected(self, self.base + extra, f"{len(extra)} trailing bytes", "trailing")

    def test_unknown_and_foreign_sections(self):
        def add(sid, data, items=1):
            return mutate.rebuild(self.base, lambda m: m["entries"].append(
                {"id": sid, "codec": 0, "flags": 0, "items": items, "data": data, "crc": None}))

        def insert(sid, data):
            def edit(m):
                m["entries"].append({"id": sid, "codec": 0, "flags": 0, "items": 1, "data": data, "crc": None})
                m["entries"].sort(key=lambda e: e["id"])
            return mutate.rebuild(self.base, edit)

        for sid in (4, 10, 14, 15, 16, 18, 19, 21, 99, 240):
            rejected(self, insert(sid, b"opaque"), f"unknown section {sid}", "outside the Builder profile")
        # the Editor authoring envelope is not part of the Builder profile: well-formed-looking and malformed forms alike
        for label, data in [("empty", b""), ("garbage", b"\xde\xad\xbe\xef" * 8), ("truncated length", struct.pack("<I", 1 << 30)),
                            ("json", b'{"graph": []}'), ("zlib bomb", zlib.compress(b"\0" * 1_000_000))]:
            rejected(self, insert(241, data), f"section 241 ({label})", "outside the Builder profile")
        rejected(self, add(241, b"x"), "section 241 out of order")

    def test_missing_sections(self):
        for sid in (1, 2, 11, 12, 13, 17, 20):
            payload = mutate.rebuild(self.base, lambda m, sid=sid: m["entries"].__setitem__(
                slice(None), [e for e in m["entries"] if e["id"] != sid]))
            rejected(self, payload, f"missing required section {sid}")
        for sid in (5, 6, 7, 8, 9):
            payload = mutate.rebuild(self.base, lambda m, sid=sid: m["entries"].__setitem__(
                slice(None), [e for e in m["entries"] if e["id"] != sid]))
            rejected(self, payload, f"geometry section {sid} alone missing", "together")
        payload = mutate.rebuild(self.base, lambda m: m["entries"].__setitem__(
            slice(None), [e for e in m["entries"] if e["id"] != 3]))
        rejected(self, payload, "materials counted but section 3 missing")

    def test_unsorted_sections(self):
        payload = mutate.rebuild(self.base, lambda m: m["entries"].reverse())
        rejected(self, payload, "descending section order", "ascending")

    def test_expansion_bomb_is_rejected_without_allocating(self):
        bomb = zlib.compress(b"\0" * (64 * 1024 * 1024), 9)

        def edit(m):
            for e in m["entries"]:
                if e["id"] == 7:
                    e.update(codec=1, data=bomb, raw=64 * 1024 * 1024)
        payload = mutate.rebuild(self.base, edit)
        tracemalloc.start()
        try:
            rejected(self, payload, "deflate bomb declared as 64 MiB", "compression")
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 8 * 1024 * 1024)

    def test_size_budget(self):
        rejected(self, self.base + b"\0" * (MAX_BYTES + 1 - len(self.base)), "input over the byte budget", "budget")
        rejected(self, b"", "empty input")
        rejected(self, MAGIC, "magic only")


def floats(*values):
    return struct.pack("<%dd" % len(values), *values)


def string_table(d, reverse=False, duplicate=False):
    count, size = struct.unpack_from("<II", d, 4)
    offsets = struct.unpack_from("<%dI" % (count + 1), d, 12)
    blob = bytes(d[12 + 4 * (count + 1):])
    names = [blob[offsets[i]:offsets[i + 1]] for i in range(count)]
    if reverse:
        names.reverse()
    if duplicate:
        names[1] = names[0]
    new, at = [0], 0
    for n in names:
        at += len(n)
        new.append(at)
    d[:] = struct.pack("<4BII", 1, 0, 0, 0, count, at) + struct.pack("<%dI" % (count + 1), *new) + b"".join(names)


def owner_of_mesh(d):
    """Index (in a definition table) of the byte that references the mesh."""
    n = struct.unpack_from("<I", d, 4)[0]
    return next(8 + 2 * n + k for k in range(n) if d[8 + 2 * n + k] != 255)


# (label, section, mutation) against floor-front-back: 6 faces, 1 mesh, 8 vertices, 2 materials
SEMANTIC_CASES = [
    ("model: face count +1", 1, lambda d: d.__setitem__(slice(68, 72), struct.pack("<I", 7))),
    ("model: material count +1", 1, lambda d: d.__setitem__(slice(56, 60), struct.pack("<I", 3))),
    ("model: mesh count +1", 1, lambda d: d.__setitem__(slice(64, 68), struct.pack("<I", 2))),
    ("model: instance count +1", 1, lambda d: d.__setitem__(slice(76, 80), struct.pack("<I", 4))),
    ("model: unused count non-zero", 1, lambda d: d.__setitem__(slice(60, 64), struct.pack("<I", 1))),
    ("model: bounds NaN", 1, lambda d: d.__setitem__(slice(8, 16), floats(math.nan))),
    ("model: bounds inverted", 1, lambda d: d.__setitem__(slice(8, 16), floats(50.0))),
    ("model: bounds do not match the geometry", 1, lambda d: d.__setitem__(slice(8, 16), floats(-1.0))),
    ("model: title out of range", 1, lambda d: d.__setitem__(93, 200)),
    ("model: first name slot not empty", 1, lambda d: d.__setitem__(92, 0)),
    ("model: wrong length", 1, lambda d: d.append(0)),
    ("strings: invalid utf-8", 2, lambda d: d.__setitem__(-1, 0xff)),
    ("strings: offsets not monotonic", 2, lambda d: d.__setitem__(slice(16, 20), struct.pack("<I", 9999))),
    ("strings: size field wrong", 2, lambda d: d.__setitem__(slice(8, 12), struct.pack("<I", 1))),
    ("strings: reversed order", 2, lambda d: string_table(d, reverse=True)),
    ("strings: duplicate entry", 2, lambda d: string_table(d, duplicate=True)),
    ("materials: header", 3, lambda d: d.__setitem__(0, 1)),
    ("materials: name out of range", 3, lambda d: d.__setitem__(8, 200)),
    ("materials: names disagree", 3, lambda d: d.__setitem__(10, d[10] ^ 1)),
    ("materials: texture present", 3, lambda d: d.__setitem__(8 + 2 * 2 + 4 * 2 + 2 * 2, 0)),
    ("materials: colorize non-zero", 3, lambda d: d.__setitem__(len(d) - 1, 1)),
    ("meshes: wrong table length", 5, lambda d: d.append(0)),
    ("meshes: definition out of range", 5, lambda d: d.__setitem__(8, 200)),
    ("meshes: face start", 5, lambda d: d.__setitem__(slice(13 + 4, 13 + 8), struct.pack("<I", 1))),
    ("meshes: face length", 5, lambda d: d.__setitem__(slice(13 + 4, 13 + 8), struct.pack("<I", 9))),
    ("meshes: vertex count", 5, lambda d: d.__setitem__(slice(9, 13), struct.pack("<I", 9))),
    ("faces: material out of range", 6, lambda d: d.__setitem__(24 + 3 * 6, 200)),
    ("faces: back material out of range", 6, lambda d: d.__setitem__(24 + 4 * 6, 200)),
    ("faces: tag set", 6, lambda d: d.__setitem__(24 + 5 * 6, 0)),
    ("faces: label out of range", 6, lambda d: d.__setitem__(24 + 6 * 6, 200)),
    ("faces: flag set", 6, lambda d: d.__setitem__(24 + 6, 1)),
    ("faces: header total loops", 6, lambda d: d.__setitem__(slice(9, 13), struct.pack("<I", 5))),
    ("faces: loop count not one", 6, lambda d: d.__setitem__(24 + 7 * 6, 2)),
    ("faces: trailing byte", 6, lambda d: d.append(0)),
    ("positions: NaN", 7, lambda d: d.__setitem__(slice(60, 68), floats(math.nan))),
    ("positions: infinity", 7, lambda d: d.__setitem__(slice(60, 68), floats(math.inf))),
    ("positions: out of range", 7, lambda d: d.__setitem__(slice(60, 68), floats(1e300))),
    ("positions: count", 7, lambda d: d.__setitem__(slice(4, 8), struct.pack("<I", 9))),
    ("positions: bounds block not zero", 7, lambda d: d.__setitem__(20, 1)),
    ("positions: trailing byte", 7, lambda d: d.append(0)),
    ("topology: vertex index out of range", 8, lambda d: d.__setitem__(20, 0x7e)),
    ("topology: header lengths", 8, lambda d: d.__setitem__(slice(12, 16), struct.pack("<I", 1))),
    ("topology: truncated varint", 8, lambda d: d.__setitem__(slice(20, 21), b"\x80")),
    ("topology: degenerate triangle", 8, lambda d: d.__setitem__(len(d) - 1, 0)),
    ("normals: first face flipped", 9, lambda d: d.__setitem__(slice(12, 36), floats(*(-v for v in struct.unpack_from("<3d", d, 12))))),
    ("normals: not unit", 9, lambda d: d.__setitem__(slice(12 + 16, 12 + 24), floats(2.0))),
    ("normals: NaN", 9, lambda d: d.__setitem__(slice(12, 20), floats(math.nan))),
    ("normals: codec", 9, lambda d: d.__setitem__(1, 1)),
    ("definitions: second root", 11, lambda d: d.__setitem__(8 + 3 + 1, 1)),
    ("definitions: name out of range", 11, lambda d: d.__setitem__(8, 200)),
    ("definitions: mesh reference out of range", 11, lambda d: d.__setitem__(owner_of_mesh(d), 9)),
    ("definitions: mesh reference removed", 11, lambda d: d.__setitem__(owner_of_mesh(d), 255)),
    ("instances: parent cycle", 12, lambda d: d.__setitem__(12 + 2 * 3, 1)),
    ("instances: parent out of range", 12, lambda d: d.__setitem__(12 + 2 * 3 + 1, 200)),
    ("instances: definition index", 12, lambda d: d.__setitem__(12 + 3 * 3, 2)),
    ("instances: transform index", 12, lambda d: d.__setitem__(12 + 4 * 3, 2)),
    ("instances: flag column", 12, lambda d: d.__setitem__(12 + 7 * 3, 0)),
    ("instances: second flag column", 12, lambda d: d.__setitem__(12 + 8 * 3, 1)),
    ("transforms: singular", 13, lambda d: d.__setitem__(slice(12, 12 + 96), floats(*([0.0] * 12)))),
    ("transforms: NaN", 13, lambda d: d.__setitem__(slice(12, 20), floats(math.nan))),
    ("transforms: huge", 13, lambda d: d.__setitem__(slice(12 + 72, 12 + 80), floats(1e9))),
    ("transforms: count", 13, lambda d: d.__setitem__(slice(4, 8), struct.pack("<I", 2))),
    ("transforms: moves the geometry out of the bounds", 13, lambda d: d.__setitem__(slice(12 + 96 + 72, 12 + 96 + 80), floats(5.0))),
    ("coverage: eligible", 17, lambda d: d.__setitem__(slice(0, 4), struct.pack("<I", 5))),
    ("coverage: fallback", 17, lambda d: d.__setitem__(slice(8, 12), struct.pack("<I", 1))),
    ("contract: revision", 20, lambda d: d.__setitem__(0, 2)),
    ("contract: exact budget", 20, lambda d: d.__setitem__(30, 1)),
]


class SemanticCorruptionTests(unittest.TestCase):
    """Payload damage with every CRC repaired: only semantic validation can catch these."""

    def test_each_semantic_corruption_is_rejected(self):
        base = golden("floor-front-back")
        read(base)
        for label, sid, change in SEMANTIC_CASES:
            with self.subTest(label):
                payload = mutate.edit_section(base, sid, change)
                self.assertNotEqual(payload, base)
                with self.assertRaises(Rejected):
                    read(payload)

    def test_two_room_semantic_damage(self):
        base = golden("two-room-door-seam")
        for label, sid, change in [
            ("a mesh block overlaps the first", 5, lambda d: d.__setitem__(slice(10 + 8 * 5 + 4, 10 + 8 * 5 + 8), struct.pack("<I", 0))),
            ("padding between mesh blocks not zero", 7, lambda d: d.__setitem__(len(d) - 1, d[len(d) - 1] ^ 1)),
            ("a face front material points at nothing", 6, lambda d: d.__setitem__(24 + 3 * 58 + 10, 200)),
        ]:
            with self.subTest(label):
                try:
                    payload = mutate.edit_section(base, sid, change)
                except Exception:
                    self.skipTest("mutation not applicable")
                with self.assertRaises(Rejected):
                    read(payload)


class RobustnessSweepTests(unittest.TestCase):
    """Flip a byte everywhere (CRC repaired inside payloads): never anything but accept-with-a-different-model or reject."""

    def sweep(self, name, stride):
        blob = golden(name)
        base = goldens.summarize(blob)
        entries = mutate.parse(blob)["entries"]
        spans = [(*mutate.entry_offset(blob, e["id"]), e["id"]) for e in entries]
        table_end = HEADER.size + len(entries) * ENTRY.size
        unchanged_in_payload = []
        for pos in range(0, len(blob), stride):
            hit = next((s for s in spans if s[0] <= pos < s[0] + s[1]), None)
            if hit:
                start, _, sid = hit
                mutated = mutate.edit_section(blob, sid, lambda d, o=pos - start: d.__setitem__(o, d[o] ^ 0xFF))
            else:
                buffer = bytearray(blob)
                buffer[pos] ^= 0xFF
                mutated = bytes(buffer)
            try:
                summary = goldens.summarize(mutated)
            except Rejected:
                continue                                    # any other exception type escapes and fails the test
            if summary == base:
                unchanged_in_payload.append((pos, hit[2] if hit else None))
        # a byte change may only go unnoticed in alignment padding between sections
        self.assertEqual([p for p in unchanged_in_payload if p[1] is not None or p[0] < table_end], [], msg=name)

    def test_small_goldens(self):
        for name in ("minimal-root", "nested-shared-definitions", "floor-front-back", "concave-l-floor",
                     "mirrored-sheared-floors"):
            with self.subTest(name):
                self.sweep(name, 1)

    def test_two_room_golden_sampled(self):
        self.sweep("two-room-door-seam", 3)


if __name__ == "__main__":
    unittest.main()
