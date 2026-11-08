"""Kais BMB-021 independent certification / corruption adversarial suite.

Runs against freshly compiled *real* geometry. No original consumer positives
can be inferred from these Builder-side tests.
"""
import copy
import hashlib
import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "interop"))
from kais_cases import REFERENCE, UNSUPPORTED, canonical_bytes, make_fixtures
from kais_reader import Reject, semantic_read
from bomc.compiler.graph_to_bomc import CompileError, compile_document

H = struct.Struct("<8sHHIIIQ")
E = struct.Struct("<HBBIIIII")


def source_sections(binary):
    _, _, _, _, _, count, start = H.unpack_from(binary)
    out = {}
    for i in range(count):
        sid, codec, flags, pos, size, raw, records, crc = E.unpack_from(binary, start + i*E.size)
        if codec != 0:
            raise AssertionError("builder fixture unexpectedly compressed")
        out[sid] = (bytes(binary[pos:pos+size]), records)
    return out


def repack(binary, additions=None, replacements=None):
    """Independent testing-only encoder for CRC-valid adversarial mutations."""
    rows = source_sections(binary)
    rows.update(additions or {})
    rows.update(replacements or {})
    pos = (H.size + len(rows)*E.size + 7) & ~7
    descriptor, body = bytearray(), bytearray()
    for sid, (payload, count) in sorted(rows.items()):
        descriptor += E.pack(sid, 0, 0, pos, len(payload), len(payload),
                             count, zlib.crc32(payload) & 0xffffffff)
        pos = (pos + len(payload) + 7) & ~7
    result = bytearray(H.pack(b"BOMC\r\n\x1a\n", 1, 2, 0x01020304, 0x11,
                              len(rows), H.size))
    result += descriptor
    for _, (payload, _) in sorted(rows.items()):
        result += b"\x00" * ((-len(result)) % 8)
        result += payload
    return bytes(result)


def changed_section(binary, section_id, change):
    rows = source_sections(binary)
    payload, count = rows[section_id]
    value = bytearray(payload)
    change(value)
    return repack(binary, replacements={section_id: (bytes(value), count)})


def changed_binary(binary, at, data):
    value = bytearray(binary)
    value[at:at+len(data)] = data
    return bytes(value)


def compressed_section(binary, section_id, declared=None, trim=0):
    """Independently repack one compressed section with fresh stored CRC."""
    sections = source_sections(binary)
    position = (H.size + E.size*len(sections) + 7) & ~7
    descriptors, pieces = bytearray(), []
    for sid, (original, count) in sorted(sections.items()):
        pack = zlib.compress(original, level=9) if sid == section_id else original
        if sid == section_id and trim:
            pack = pack[:-trim]
        raw_size = (len(original) if declared is None else declared) if sid == section_id else len(original)
        descriptors += E.pack(sid, 1 if sid == section_id else 0, 0, position,
                              len(pack), raw_size, count, zlib.crc32(pack) & 0xffffffff)
        pieces.append(pack)
        position = (position + len(pack) + 7) & ~7
    out = bytearray(H.pack(b"BOMC\r\n\x1a\n", 1, 2, 0x01020304, 0x11,
                           len(sections), 32)) + descriptors
    for part in pieces:
        out += bytes((-len(out)) % 8) + part
    return bytes(out)


class KaisSemantic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = make_fixtures()
        cls.outputs = {key: compile_document(doc).payload
                       for key, doc in cls.docs.items()}

    def test_independent_full_geometry_readback(self):
        for label, binary in self.outputs.items():
            with self.subTest(case=label):
                parsed = semantic_read(binary)
                expected = REFERENCE[label]
                for k, v in expected.items():
                    if k == "bounds":
                        for a, b in zip(parsed[k], v):
                            self.assertTrue(math.isclose(a, b, abs_tol=1e-9), (label, parsed[k], v))
                    else:
                        self.assertEqual(parsed[k], v, (label, k))
                self.assertEqual(parsed["coverage"],
                                 [parsed["faceCount"], parsed["faceCount"], 0, 0, 0, 0])
                self.assertGreater(parsed["vertexCount"], 0)
                self.assertGreater(parsed["triangleCount"], 0)
                self.assertEqual(parsed["sha256"], hashlib.sha256(binary).hexdigest())
                self.assertIn(5, parsed["sections"])
                self.assertIn(9, parsed["sections"])
                self.assertEqual(sum(f["triangleCount"] for f in parsed["faces"]),
                                 parsed["triangleCount"])

    def test_front_back_semantics_and_material_identity(self):
        read = semantic_read(self.outputs["minimal-solid"])
        faces = [f for f in read["faces"] if f["label"] == "Study floor top"]
        self.assertEqual(len(faces), 1)
        self.assertEqual(faces[0]["front"], "house/floor-1/study/finish")
        self.assertEqual(faces[0]["back"], "house/floor-1/study/concrete")
        self.assertEqual(faces[0]["surface"], 2)
        self.assertEqual(faces[0]["role"], 2)
        self.assertEqual({m["name"] for m in read["materials"]},
                         {faces[0]["front"], faces[0]["back"]})

    def test_door_and_window_are_cutouts_not_fake_surfaces(self):
        for key, cut_type in (("door-and-two-room", "door"),
                              ("window-cutout", "window")):
            with self.subTest(key=key):
                parsed = semantic_read(self.outputs[key])
                self.assertTrue(any("/cut-" in f["label"] for f in parsed["faces"]))
                self.assertTrue(any("/insert-" in f["label"] for f in parsed["faces"]))
                face_roles = {f["role"] for f in parsed["faces"]}
                self.assertIn(7 if cut_type == "door" else 6, face_roles)
                self.assertGreater(parsed["triangleCount"], 20)

    def test_affine_instance_path_and_world_bounds(self):
        read = semantic_read(self.outputs["nested-mirror-shear-nonuniform"])
        byname = {i["name"]: i for i in read["instances"]}
        child = byname["house/level-1/child"]
        parent = byname["house/level-1/root"]
        self.assertEqual(child["parent"], parent["name"])
        self.assertEqual(parent["transform"][0], -1)
        self.assertEqual(child["transform"][3], .25)
        self.assertEqual(child["transform"][4], 1.5)
        self.assertEqual(child["transform"][8], .75)
        self.assertEqual(child["transform"][9], 3)
        self.assertEqual(read["meshCount"], 1)

    def test_source_order_equivalence_uses_binary_sha_not_json(self):
        for key in ("door-and-two-room", "nested-mirror-shear-nonuniform"):
            doc = copy.deepcopy(self.docs[key])
            doc["modules"].reverse()
            for module in doc["modules"]:
                module["operations"].reverse()
                module["materials"].reverse()
                if "faceAnnotations" in module:
                    module["faceAnnotations"].reverse()
            candidate = compile_document(doc).payload
            self.assertEqual(hashlib.sha256(candidate).digest(),
                             hashlib.sha256(self.outputs[key]).digest(), key)
            self.assertEqual(candidate, self.outputs[key])

    def test_two_cold_processes_each_fixture_and_byte_SHA(self):
        for name, doc in self.docs.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                source = root/"synthetic.json"
                source.write_bytes(canonical_bytes(doc))
                outputs = []
                for i in range(2):
                    dst = root/f"cold-{i}.bomc"
                    run = subprocess.run([sys.executable, "-m", "bomc.compiler.graph_to_bomc",
                        "--input", str(source), "--output", str(dst)],
                        cwd=ROOT, capture_output=True, text=True, check=False)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    receipt = json.loads(run.stdout)
                    payload = dst.read_bytes()
                    self.assertEqual(receipt["sha256"], hashlib.sha256(payload).hexdigest())
                    self.assertEqual(receipt["sha256"], semantic_read(payload)["sha256"])
                    outputs.append((payload, receipt))
                self.assertEqual(outputs[0], outputs[1], name)
                self.assertEqual(outputs[0][0], self.outputs[name])

    def test_module_ir_unsupported_holes_fail_closed(self):
        bad = copy.deepcopy(self.docs["concave-solid"])
        bad["modules"][0]["operations"][0]["holes"] = [[[.25,.25],[.5,.25],[.5,.5]]]
        with self.assertRaises(CompileError):
            compile_document(bad)
        self.assertIn("concave-with-holes", UNSUPPORTED)

    def test_strict_reader_container_and_directory_adversarial(self):
        base = self.outputs["minimal-solid"]
        _, _, _, _, _, n, _ = H.unpack_from(base)
        first = E.unpack_from(base, 32)[3]
        candidates = {
            "version": changed_binary(base, 10, struct.pack("<H", 3)),
            "major": changed_binary(base, 8, struct.pack("<H", 2)),
            "endianness": changed_binary(base, 12, b"\x00\x00\x00\x00"),
            "unknown_flags": changed_binary(base, 16, struct.pack("<I", 0x80000011)),
            "unsupported_codec": changed_binary(base, 34, b"\x02"),
            "invalid_section_flags": changed_binary(base, 35, b"\x80"),
            "directory_count": changed_binary(base, 20, struct.pack("<I", 65)),
            "directory_offset": changed_binary(base, 24, struct.pack("<Q", 128)),
            "misaligned_section": changed_binary(base, 32+E.size+4, struct.pack("<I", first+1)),
            "section_overlap": changed_binary(base, 32+E.size+4, struct.pack("<I", first)),
            "invalid_raw_len": changed_binary(base, 32+12, struct.pack("<I", 2_000_001)),
            "truncated_end": base[:-10],
            "truncated_directory": base[:48],
            "corrupted_stored_crc": changed_binary(base, first, bytes([base[first] ^ 1])),
            "malformed_zlib": changed_binary(base, 34, b"\x01"),
            "short_binary": b"BOMC\r\n\x1a\n",
        }
        self.assertGreater(n, 8)
        for key, bad in candidates.items():
            with self.subTest(vector=key):
                with self.assertRaises(Reject):
                    semantic_read(bad)

    def test_semantic_corruption_with_correct_recomputed_crcs(self):
        base = self.outputs["minimal-solid"]
        malformed = {
            "geometry_index": changed_section(base, 8,
                lambda b: b.__setitem__(20, 255)),
            "face_count": changed_section(base, 6,
                lambda b: b.__setitem__(slice(4,8), struct.pack("<I", 300))),
            "model_coverage": changed_section(base, 17,
                lambda b: b.__setitem__(slice(0,4), struct.pack("<I", 999))),
            "bad_numeric": changed_section(base, 13,
                lambda b: b.__setitem__(slice(12,20), struct.pack("<d", float("nan")))),
        }
        # Crafted valid-CRC cycle in the actual INSTANCE parent column.
        rows = source_sections(base)
        ins, _ = rows[12]
        count = struct.unpack_from("<I", ins, 8)[0]
        self.assertGreater(count, 1)
        malformed["instance_parent_cycle"] = changed_section(base, 12,
            lambda b: b.__setitem__(12+2*count+1, 1))
        for key, bad in malformed.items():
            with self.subTest(vector=key):
                with self.assertRaises(Reject):
                    semantic_read(bad)

    def test_zlib_real_stream_bounded_decode_and_expansion_bomb(self):
        base = self.outputs["minimal-solid"]
        # Known legal compressed section is parsed semantically, not rejected
        # just because the writer normally chooses STORE.
        compressed = compressed_section(base, 2)
        normal, comp = semantic_read(base), semantic_read(compressed)
        for field in ("faceCount", "triangleCount", "vertexCount", "coverage",
                      "bounds", "materials", "faces", "instances"):
            self.assertEqual(normal[field], comp[field])
        # Valid compressed bytes, false small declared output: strict cap and
        # size mismatch must reject even with a recalculated stored CRC.
        with self.assertRaises(Reject):
            semantic_read(compressed_section(base, 2, declared=1))
        with self.assertRaises(Reject):
            semantic_read(compressed_section(base, 2, declared=2_000_001))
        with self.assertRaises(Reject):
            semantic_read(compressed_section(base, 2, trim=1))

    def test_crc_valid_winding_and_material_reference_mutations(self):
        base = self.outputs["minimal-solid"]
        face_count = semantic_read(base)["faceCount"]
        def invert_normal(raw):
            first = struct.unpack_from("<3d", raw, 12)
            struct.pack_into("<3d", raw, 12, *(-v for v in first))
        def bogus_material(raw):
            raw[24 + 3*face_count] = 254
        for kind, broken in {
            "reversed_normal": changed_section(base, 9, invert_normal),
            "bad_material_index": changed_section(base, 6, bogus_material),
        }.items():
            with self.subTest(kind=kind), self.assertRaises(Reject):
                semantic_read(broken)

    def test_section_241_unknown_and_budget_gate_reject_not_editor_claim(self):
        base = self.outputs["minimal-solid"]
        cases = {
            "unknown_249": repack(base, additions={249: (b"synthetic-unknown", 1)}),
            "malformed_editor_241": repack(base, additions={241: (b"BWEB-invalid-synthetic", 1)}),
        }
        for label, binary in cases.items():
            with self.subTest(vector=label):
                with self.assertRaises(Reject):
                    semantic_read(binary)
        # The above is the *Builder* strict reader; no original Editor method
        # ran, so this cannot assert the original Editor rejects section 241.

if __name__ == "__main__":
    unittest.main()
