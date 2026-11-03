"""Independent BOMC wire readback and nonempty semantic acceptance for BMB-020.

All fixtures synthetic. The reader here parses binary primitives independently
of the writer, cross-checks geometry records and numerical area/orientation.
This is NOT a substitute for original Editor/Model-Eval consumer certification.
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
from bomc.adapter.writer_v12 import HEADER, ENTRY
from bomc.compiler.graph_to_bomc import CompileError, compile_document
from core.graph import dag
from tools.bomc_fixture_harness import inspect_container


def module(mid="house/floor/a", parent="house/floor", transform=None):
    return {
        "schemaVersion": "1.0.0", "moduleId": mid, "parentId": parent,
        "revision": 1,
        "localFrame": {
            "unit": "m", "handedness": "right", "upAxis": "+Z",
            "forwardAxis": "+Y", "transform": list(transform or dag.IDENTITY)},
        "bounds": {"min": [0, 0, 0], "max": [5, 4, 3]},
        "operations": [], "materials": [], "ports": [],
        "ownedSeams": [], "dependencies": [],
        "provenance": {"origin": "synthetic", "generator": "bmb020-tests"},
    }


def floor(mid="house/floor/a", transform=None):
    m = module(mid, transform=transform)
    m["operations"] = [{
        "kind": "floor-slab", "opId": "slab", "role": "floor",
        "materialId": "base", "footprint": [[0, 0], [2, 0], [2, 1], [0, 1]],
        "thickness": 0.2, "elevation": 0}]
    m["materials"] = [
        {"materialId": "base", "rgba": [140, 135, 130, 255],
         "opacity": 1, "semanticRole": "floor"},
        {"materialId": "paint", "rgba": [200, 50, 35, 240],
         "opacity": 0.8, "semanticRole": "floor"},
    ]
    m["faceAnnotations"] = [{
        "opId": "slab", "faceKey": "top", "role": "floor",
        "frontMaterialId": "paint", "backMaterialId": "base",
        "label": "Floor top: independent front/back"}]
    return m


def wall_with_door():
    m = module()
    m["operations"] = [
        {"kind": "wall-run", "opId": "wall", "role": "wall",
         "path": [[0, 0], [4, 0]], "thickness": 0.20,
         "height": 3.0, "baseElevation": 0.0},
        {"kind": "opening-cut", "opId": "door", "targetWallOpId": "wall",
         "offset": 1.0, "width": 1.0, "height": 2.2,
         "sillHeight": 0, "openingType": "door"},
    ]
    return m


def _var(blob, cursor):
    value, shift = 0, 0
    for _ in range(5):
        if cursor >= len(blob):
            raise AssertionError("varuint truncated")
        x = blob[cursor]
        cursor += 1
        value |= (x & 127) << shift
        if x < 128:
            return value, cursor
        shift += 7
    raise AssertionError("varuint overlong")


def _deltas(blob, count):
    vals, last, at = [], 0, 0
    for _ in range(count):
        z, at = _var(blob, at)
        last += (z >> 1) if not z & 1 else -(z >> 1) - 1
        vals.append(last)
    if at != len(blob):
        raise AssertionError("trailing topology varints")
    return vals


def _refs(data, count):
    return [None if v == 255 else v for v in data[:count]]


def _newell(points):
    out = [0.0, 0.0, 0.0]
    for p, q in zip(points, points[1:] + points[:1]):
        for j in range(3):
            out[j] += (p[(j + 1) % 3] - q[(j + 1) % 3]) * (
                p[(j + 2) % 3] + q[(j + 2) % 3])
    return out


def independent_read(payload):
    inspect_container(payload)
    sections = {}
    _, major, minor, marker, flags, n, offset = HEADER.unpack_from(payload)
    assert (major, minor, marker, flags, offset) == (1, 2, 0x01020304, 0x11, 32)
    for i in range(n):
        sid, codec, section_flags, start, stored, raw, count, checksum = ENTRY.unpack_from(
            payload, 32 + 24 * i)
        part = payload[start:start + stored]
        assert codec == section_flags == 0 and stored == raw
        assert (zlib.crc32(part) & 0xffffffff) == checksum
        assert sid not in sections
        sections[sid] = (count, part)
    model = sections[1][1]
    counts = struct.unpack_from("<9I", model, 56)
    bounds = struct.unpack_from("<6d", model, 8)
    assert all(math.isfinite(v) for v in bounds)
    assert counts[2] == sections[5][0] and counts[3] == sections[6][0]
    assert counts[4] == sections[11][0] and counts[5] == sections[12][0]
    assert counts[6] == sections[13][0]
    text = sections[2][1]
    size = struct.unpack_from("<I", text, 8)[0]
    string_count = sections[2][0]
    byte_count = struct.unpack_from("<I", text, 8)[0]
    offsets = struct.unpack_from("<" + "I" * (string_count + 1), text, 12)
    blob = text[12 + 4 * (string_count + 1):]
    assert len(blob) == byte_count and offsets[-1] == byte_count
    strings = [blob[offsets[i]:offsets[i+1]].decode("utf8") for i in range(string_count)]
    assert strings == sorted(set(strings))

    matcount = counts[0]
    if matcount:
        materials = sections[3][1]
        assert materials[:4] == bytes((2, 1, 1, 0))
        assert struct.unpack_from("<I", materials, 4)[0] == matcount
        mnames = _refs(materials[8:], matcount)
        colors_at = 8 + matcount * 2
        colors = [tuple(materials[colors_at+4*i:colors_at+4*(i+1)])
                  for i in range(matcount)]
        assert all(0 <= idx < len(strings) for idx in mnames)
        assert len(materials) == 8 + matcount * (2 + 4 + 2 + 1 + 4 + 4 + 1 + 1 + 24 + 32)
    else:
        assert 3 not in sections
        colors = []

    face_data = sections[6][1]
    version, mw, tw, sw, fcount, total_loops, a, b, c = struct.unpack_from("<4BIIIII", face_data)
    assert (version, mw, tw, sw) == (1, 1, 1, 1)
    assert fcount == counts[3] and total_loops == fcount
    off = 24
    surfaces = list(face_data[off:off+fcount]); off += fcount
    flags = list(face_data[off:off+fcount]); off += fcount
    roles = list(face_data[off:off+fcount]); off += fcount
    fronts = _refs(face_data[off:], fcount); off += fcount
    backs = _refs(face_data[off:], fcount); off += fcount
    tags = _refs(face_data[off:], fcount); off += fcount
    labels = _refs(face_data[off:], fcount); off += fcount
    assert all(f == 0 for f in flags) and all(x is None for x in tags)
    assert all(0 <= idx < matcount for idx in fronts + backs if idx is not None)
    assert all(0 <= idx < len(strings) for idx in labels if idx is not None)
    def decode_column(size, n):
        nonlocal off
        begin, end = off, off+size
        vals, cursor = [], 0
        for _ in range(n):
            value, cursor = _var(face_data[begin:end], cursor)
            vals.append(value)
        assert cursor == size
        off = end
        return vals
    loop_counts = decode_column(a, fcount)
    triangle_counts = decode_column(b, fcount)
    lengths = decode_column(c, total_loops)
    assert all(v == 1 for v in loop_counts)
    assert all(v >= 3 for v in lengths)
    assert all(v > 0 and v % 3 == 0 for v in triangle_counts)
    assert off == len(face_data)

    mesh_data = sections[5][1]
    mcount = sections[5][0]
    assert mesh_data[:4] == bytes((1, 1, 0, 0))
    assert struct.unpack_from("<I", mesh_data, 4)[0] == mcount
    defs = _refs(mesh_data[8:], mcount)
    columns = [
        struct.unpack_from("<" + "I" * mcount, mesh_data, 8 + mcount + 4*j*mcount)
        for j in range(11)
    ]
    normal_data = sections[9][1]
    assert normal_data[:4] == bytes((1, 3, 0, 0))
    assert struct.unpack_from("<II", normal_data, 4) == (fcount, 24*fcount)
    normals = list(struct.unpack_from("<" + "d" * (3*fcount), normal_data, 12))
    faces, mesh_bounds, total_triangles = [], [], 0
    for mesh in range(mcount):
        vcount = columns[0][mesh]
        fstart, flen = columns[1][mesh], columns[2][mesh]
        po, pl, to, tl = [columns[i][mesh] for i in (5,6,7,8)]
        ps = sections[7][1][po:po+pl]
        ts = sections[8][1][to:to+tl]
        assert ps[:4] == bytes((1,1,0,0))
        assert struct.unpack_from("<II", ps, 4) == (vcount, 24*vcount)
        verts = [struct.unpack_from("<3d", ps, 60+24*j) for j in range(vcount)]
        assert len(ps) == 60 + 24*vcount
        assert all(all(math.isfinite(v) for v in p) for p in verts)
        assert ts[:4] == bytes((1,0,0,0))
        lcount, tcount, ll, tlbytes = struct.unpack_from("<4I", ts, 4)
        assert len(ts) == 20 + ll + tlbytes
        loops = _deltas(ts[20:20+ll], lcount)
        tris = _deltas(ts[20+ll:], tcount)
        assert all(0 <= k < vcount for k in loops + tris)
        assert sum(lengths[fstart:fstart+flen]) == lcount
        assert sum(triangle_counts[fstart:fstart+flen]) == tcount
        at_l, at_t = 0, 0
        for f in range(fstart, fstart+flen):
            ring = [verts[k] for k in loops[at_l:at_l+lengths[f]]]
            idx = tris[at_t:at_t+triangle_counts[f]]
            at_l += lengths[f]
            at_t += triangle_counts[f]
            normal = normals[3*f:3*f+3]
            nv = _newell(ring)
            assert sum(a*b for a,b in zip(nv,normal)) > 1e-9
            area = math.sqrt(sum(x*x for x in nv)) / 2
            tri_area = 0.0
            for i in range(0,len(idx),3):
                p,q,r = (verts[idx[i+j]] for j in range(3))
                a = [q[t]-p[t] for t in range(3)]
                b = [r[t]-p[t] for t in range(3)]
                cross = (a[1]*b[2]-a[2]*b[1],
                         a[2]*b[0]-a[0]*b[2],
                         a[0]*b[1]-a[1]*b[0])
                assert sum(cross[j]*normal[j] for j in range(3)) > 0
                tri_area += math.sqrt(sum(x*x for x in cross))/2
                total_triangles += 1
            assert math.isclose(tri_area, area, rel_tol=1e-7, abs_tol=1e-7)
            faces.append({"surface": surfaces[f], "role": roles[f],
                          "front": fronts[f], "back": backs[f],
                          "label": strings[labels[f]], "normal": normal,
                          "ring": ring, "triangleCount": len(idx)//3})
        assert at_l == len(loops) and at_t == len(tris)
        mesh_bounds.append({"definition":defs[mesh], "positions":verts})
    coverage = struct.unpack("<6I", sections[17][1])
    assert coverage == (fcount, fcount, 0, 0, 0, 0)
    assert len(faces) == fcount and total_triangles > 0
    assert len(set(m["definition"] for m in mesh_bounds)) == mcount
    transforms = sections[13][1]
    assert transforms[:4] == bytes((1,1,0,0))
    tcount, tlength = struct.unpack_from("<II", transforms, 4)
    assert tcount == counts[6] and tlength == 96*tcount
    matrices = [struct.unpack_from("<12d", transforms, 12+96*i)
                for i in range(tcount)]
    return {"counts":counts, "coverage":coverage, "bounds":bounds,
            "strings":strings, "faces":faces, "mesh":mesh_bounds,
            "colors":colors, "transforms":matrices,
            "triangles":total_triangles, "sections":tuple(sorted(sections))}


class GeometryReadback(unittest.TestCase):
    def test_real_floor_face_loop_material_and_coverage(self):
        m = floor()
        binary = compile_document({"schemaVersion":"1.0.0","modules":[m]})
        parsed = independent_read(binary.payload)
        self.assertTrue(binary.receipt()["geometrySemanticsValid"])
        self.assertEqual(parsed["coverage"], tuple(binary.coverage))
        self.assertEqual(len(parsed["faces"]), 6)
        self.assertEqual(parsed["counts"][0:4], (2,0,1,6))
        self.assertEqual(parsed["bounds"], (0,0,0,2,1,0.2))
        self.assertEqual(parsed["triangles"], 12)
        painted = [f for f in parsed["faces"] if f["label"] == "Floor top: independent front/back"]
        self.assertEqual(len(painted), 1)
        self.assertNotEqual(painted[0]["front"], painted[0]["back"])
        self.assertEqual(painted[0]["surface"], 2)
        self.assertEqual(painted[0]["role"], 2)
        self.assertEqual(binary.receipt()["materialCount"], 2)
        self.assertIn(9, parsed["sections"])

    def test_wall_real_cutout_and_shared_wall_example(self):
        wall = wall_with_door()
        result = independent_read(compile_document({
            "schemaVersion":"1.0.0","modules":[wall]}).payload)
        cut = [f for f in result["faces"] if "/cut-" in f["label"]]
        inserts = [f for f in result["faces"] if "/insert-" in f["label"]]
        self.assertGreater(len(cut), 10)
        self.assertGreater(len(inserts), 5)
        self.assertTrue(any(f["role"] == 7 for f in inserts))
        # Front/back wall surfaces cannot cover doorway interior.
        for f in cut:
            ring = f["ring"]
            if all(abs(v[1]-0.1) < 1e-8 or abs(v[1]+0.1) < 1e-8 for v in ring):
                centre = [sum(p[k] for p in ring) / len(ring) for k in range(3)]
                self.assertFalse(1 < centre[0] < 2 and 0 < centre[2] < 2.2)

        fixture = json.loads((ROOT/"examples/module-ir-two-rooms.json").read_text())
        output = compile_document(fixture)
        readback = independent_read(output.payload)
        self.assertEqual(readback["counts"][2], 2)  # two actual meshes, no duplicate owner mesh
        self.assertGreater(readback["counts"][3], 15)
        self.assertEqual(output.coverage[0], readback["counts"][3])

    def test_order_independence_transforms_and_cold_process(self):
        a = floor()
        b = floor("house/floor/b", transform=dag.compose(dag.translation(4,3,0),
                                                         dag.shear_xy(0.3)))
        original = {"schemaVersion":"1.0.0","modules":[b,a]}
        changed = copy.deepcopy(original)
        changed["modules"].reverse()
        for m in changed["modules"]:
            m["materials"].reverse()
            m["faceAnnotations"].reverse()
        first, second = compile_document(original), compile_document(changed)
        self.assertEqual(first.payload,second.payload)
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/"in.json"
            src.write_text(json.dumps(original),encoding="utf8")
            receipts=[]
            blobs=[]
            for j in range(2):
                dest=Path(tmp)/f"run{j}.bomc"
                run=subprocess.run([sys.executable,"-m","bomc.compiler.graph_to_bomc",
                    "--input",str(src),"--output",str(dest)],cwd=ROOT,
                    check=True,capture_output=True,text=True)
                receipts.append(json.loads(run.stdout))
                blobs.append(dest.read_bytes())
            self.assertEqual(blobs[0],blobs[1])
            self.assertEqual(receipts[0],receipts[1])
            self.assertEqual(receipts[0]["sha256"],hashlib.sha256(blobs[0]).hexdigest())
            parsed=independent_read(blobs[0])
            self.assertEqual(parsed["counts"][2:4],(2,12))
            self.assertEqual(parsed["coverage"],(12,12,0,0,0,0))
            self.assertEqual(parsed["triangles"],24)

    def test_nested_mirror_shear_and_operation_permutation(self):
        from core.assembly import assemble
        from bomc.compiler.graph_to_bomc import compile_assembly
        parent = module("house/floor", parent=None, transform=dag.mirror("x"))
        parent["bounds"] = {"min": [0,0,0], "max": [0,0,0]}
        child = floor(transform=dag.compose(dag.translation(3,0,0), dag.shear_xy(0.25)))
        child["parentId"] = parent["moduleId"]
        doc = {"schemaVersion":"1.0.0", "modules":[parent, child]}
        compiled = compile_document(doc)
        readback = independent_read(compiled.payload)
        self.assertEqual(readback["bounds"], (-5.25,0.0,0.0,-3.0,1.0,0.2))
        self.assertIn((-1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0),
                      readback["transforms"])
        self.assertIn((1.0,0.0,0.0,0.25,1.0,0.0,0.0,0.0,1.0,3.0,0.0,0.0),
                      readback["transforms"])
        assembly = assemble(doc["modules"])
        assembly.world_transforms[child["moduleId"]] = tuple(dag.IDENTITY)
        with self.assertRaisesRegex(CompileError, "assembly proof"):
            compile_assembly(assembly)

        cut = wall_with_door()
        first = compile_document({"schemaVersion":"1.0.0","modules":[cut]})
        cut["operations"].reverse()
        second = compile_document({"schemaVersion":"1.0.0","modules":[cut]})
        self.assertEqual(first.payload,second.payload)

    def test_large_json_budget_prevents_allocating_full_binary(self):
        big = floor()
        big["provenance"]["note"] = "x" * (1_000_000 + 1)
        with self.assertRaisesRegex(CompileError, "byte budget"):
            compile_document({"schemaVersion":"1.0.0","modules":[big]})

    def test_reject_lossy_missing_refs_bad_geometry_and_keep_previous(self):
        base=floor()
        failures = []
        bad=copy.deepcopy(base);bad["operations"][0]["footprint"]=[[0,0],[2,0],[1,0]]
        failures.append(bad)
        bad=copy.deepcopy(base);bad["materials"][0]["materialId"]="missing"
        failures.append(bad)
        bad=copy.deepcopy(base);bad["faceAnnotations"][0]["frontMaterialId"]="missing"
        failures.append(bad)
        bad=copy.deepcopy(base);bad["operations"][0]["holes"]=[[[0,0],[1,0],[0,1]]]
        failures.append(bad)
        bad=copy.deepcopy(base);bad["operations"][0]["thickness"]=float("nan")
        failures.append(bad)
        bad=copy.deepcopy(base);bad["operations"].append({"kind":"stair","opId":"stair"})
        failures.append(bad)
        for item in failures:
            with self.subTest(item=item["operations"]):
                with self.assertRaises(CompileError):
                    compile_document({"schemaVersion":"1.0.0","modules":[item]})
        with tempfile.TemporaryDirectory() as tmp:
            source,dest=Path(tmp)/"source.json",Path(tmp)/"output.bomc"
            dest.write_bytes(b"OLD_VERIFIED_ARTIFACT")
            source.write_text(json.dumps({"schemaVersion":"1.0.0","modules":[failures[0]]}))
            run=subprocess.run([sys.executable,"-m","bomc.compiler.graph_to_bomc",
                                "--input",str(source),"--output",str(dest)],
                               cwd=ROOT,capture_output=True,text=True)
            self.assertEqual(run.returncode,2)
            self.assertEqual(dest.read_bytes(),b"OLD_VERIFIED_ARTIFACT")
            self.assertFalse(any(p.name.startswith(".bmb020-") for p in Path(tmp).iterdir()))


if __name__ == "__main__":
    unittest.main()
