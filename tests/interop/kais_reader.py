"""Kais BMB-021 independent, bounded BOMC 1.2 *semantic* decoder.

Original work against BMB-001's published wire contract. This decoder neither
imports the production writer nor calls BMB-020's test reader. It certifies only
the strict Builder solid-geometry profile, NOT original Editor/Model-Eval.
All byte offsets are validated before dereferencing untrusted data.
"""
from __future__ import annotations

import hashlib
import math
import struct
import zlib

HEADER = struct.Struct("<8sHHIIIQ")
ENTRY = struct.Struct("<HBBIIIII")
MAGIC = b"BOMC\r\n\x1a\n"
BASE = {1, 2, 11, 12, 13, 17, 20}
GEOMETRY = {5, 6, 7, 8, 9}
ALLOWED = BASE | GEOMETRY | {3}
MAX_BYTES = 2_000_000
MAX_COUNT = 16_384


class Reject(ValueError):
    """Unsafe or incompatible BOMC input: reject without partial semantics."""


def require(predicate, reason):
    if not predicate:
        raise Reject(reason)


def read_at(fmt, raw, offset=0):
    try:
        return struct.unpack_from(fmt, raw, offset)
    except (struct.error, OverflowError) as exc:
        raise Reject("truncated field: " + str(exc)) from exc


def take(raw, start, length):
    require(start >= 0 and length >= 0 and start + length <= len(raw),
            "out-of-bounds slice")
    return raw[start:start + length]


def var_column(raw, count):
    require(count <= MAX_COUNT * 8, "varuint item budget")
    output, cursor = [], 0
    for _ in range(count):
        value = 0
        begin = cursor
        for j in range(5):
            require(cursor < len(raw), "truncated varuint")
            item = raw[cursor]
            cursor += 1
            value |= (item & 127) << (7 * j)
            if item < 128:
                require(value <= 0xffffffff and
                        cursor - begin == max(1, (value.bit_length() + 6) // 7),
                        "noncanonical/overflowed varuint")
                output.append(value)
                break
        else:
            raise Reject("varuint too long")
    require(cursor == len(raw), "trailing varuint bytes")
    return output


def delta_column(raw, count, vertex_count):
    values = []
    last = 0
    for word in var_column(raw, count):
        last += (word >> 1) if word % 2 == 0 else -(word >> 1) - 1
        require(0 <= last < vertex_count, "out-of-range geometry vertex index")
        values.append(last)
    return values


def index_list(raw, at, n, limit, nullable=False):
    vals = list(take(raw, at, n))
    for v in vals:
        require((v == 255 and nullable) or v < limit, "invalid table reference")
    return vals


def container(blob):
    require(isinstance(blob, bytes) and HEADER.size <= len(blob) <= MAX_BYTES,
            "container byte budget / short header")
    magic, maj, minor, endian, flags, n, directory = read_at(HEADER.format, blob)
    require(magic == MAGIC and (maj, minor) == (1, 2), "invalid magic/version")
    require(endian == 0x01020304 and flags == 0x11, "unsupported endian/flags")
    require(0 < n <= 64 and directory == 32, "invalid section directory")
    end = directory + ENTRY.size * n
    require(end <= len(blob), "truncated directory")
    entries = {}
    intervals = []
    previous = -1
    expanded_sum = 0
    for i in range(n):
        sid, codec, section_flags, offset, stored, raw_len, count, crc = read_at(
            ENTRY.format, blob, directory + ENTRY.size * i)
        require(sid in ALLOWED and sid > previous, "unknown/duplicate/unsorted section")
        previous = sid
        require(section_flags == 0 and codec in (0, 1), "unsupported descriptor codec/flags")
        require(stored <= MAX_BYTES and raw_len <= MAX_BYTES and count <= MAX_COUNT,
                "section allocation budget")
        require(offset % 8 == 0 and offset >= end and offset + stored <= len(blob),
                "section misaligned/overflows directory/file")
        require(stored > 0, "empty section payload")
        intervals.append((offset, offset + stored))
        packed = take(blob, offset, stored)
        require(zlib.crc32(packed) & 0xffffffff == crc, "stored CRC mismatch")
        if codec == 0:
            require(stored == raw_len, "uncompressed size mismatch")
            value = packed
        else:
            try:
                dec = zlib.decompressobj()
                value = dec.decompress(packed, raw_len + 1)
                require(len(value) == raw_len and dec.eof and
                        not dec.unconsumed_tail and not dec.unused_data and
                        not dec.flush(), "invalid compressed stream/expansion")
            except zlib.error as exc:
                raise Reject("invalid zlib compressed payload") from exc
        expanded_sum += len(value)
        require(expanded_sum <= MAX_BYTES, "total expansion budget")
        entries[sid] = (count, value)
    intervals.sort()
    require(all(a[1] <= b[0] for a, b in zip(intervals, intervals[1:])),
            "overlapping section ranges")
    require(BASE <= entries.keys(), "missing mandatory semantic section")
    seen_geo = GEOMETRY & entries.keys()
    require(not seen_geo or seen_geo == GEOMETRY, "incomplete geometry section set")
    return entries


def strings(payload, declared):
    require(len(payload) >= 16 and payload[:4] == b"\x01\x00\x00\x00",
            "invalid string block")
    count, byte_len = read_at("<II", payload, 4)
    require(count == declared and count <= 254 and 12 + 4 * (count + 1) <= len(payload),
            "string-count / offset budget")
    offsets = read_at("<" + "I" * (count + 1), payload, 12)
    raw = payload[12 + 4 * (count + 1):]
    require(len(raw) == byte_len and offsets[0] == 0 and offsets[-1] == byte_len,
            "invalid string length")
    require(all(a <= b for a, b in zip(offsets, offsets[1:])),
            "string offsets unsorted")
    try:
        names = [raw[offsets[i]:offsets[i+1]].decode("utf-8") for i in range(count)]
    except UnicodeDecodeError as exc:
        raise Reject("invalid UTF-8 string") from exc
    require(names == sorted(set(names)), "string dictionary not canonical")
    return names


def material_table(payload, n, names):
    require(len(payload) == 8 + n * 75 and payload[:4] == b"\x02\x01\x01\x00" and
            read_at("<I", payload, 4)[0] == n, "invalid material v2 record")
    ids = index_list(payload, 8, n, len(names))
    ref = index_list(payload, 8 + n, n, len(names))
    rgba_start = 8 + 2 * n
    rgbas = [list(take(payload, rgba_start + 4 * i, 4)) for i in range(n)]
    opacity_start = rgba_start + n * 4
    opacity = list(read_at("<" + "H" * n, payload, opacity_start)) if n else []
    require(all(ids[i] == ref[i] for i in range(n)), "material name mismatch")
    return [{"name": names[ids[i]], "rgba": rgbas[i],
             "opacityU16": opacity[i]} for i in range(n)]


def signed_area(vs):
    s = [0., 0., 0.]
    for a, b in zip(vs, vs[1:] + vs[:1]):
        s[0] += (a[1] - b[1]) * (a[2] + b[2])
        s[1] += (a[2] - b[2]) * (a[0] + b[0])
        s[2] += (a[0] - b[0]) * (a[1] + b[1])
    return s


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def transform(v, p):
    return (v[0] * p[0] + v[3] * p[1] + v[6] * p[2] + v[9],
            v[1] * p[0] + v[4] * p[1] + v[7] * p[2] + v[10],
            v[2] * p[0] + v[5] * p[1] + v[8] * p[2] + v[11])


def semantic_read(blob):
    sections = container(blob)
    model = sections[1][1]
    require(len(model) == 94 and model[:4] == b"\x01\x01\x01\x05",
            "unsupported MODEL profile")
    bbox = read_at("<6d", model, 8)
    require(all(math.isfinite(v) and abs(v) <= 1e6 for v in bbox),
            "invalid model bounds")
    mc = read_at("<9I", model, 56)
    labels = strings(sections[2][1], sections[2][0])
    for idx, sid in ((0, 3), (2, 5), (3, 6), (4, 11), (5, 12), (6, 13)):
        require(mc[idx] == sections.get(sid, (0,))[0], "MODEL count/section mismatch")
    require(mc[1] == mc[7] == mc[8] == 0, "unsupported tags/visual/UV")
    geom = mc[2] > 0
    require(geom == (5 in sections), "geometry status mismatch")
    require(mc[3] <= 4096 and mc[2] <= 128, "geometry record budget")
    materials = material_table(sections[3][1], mc[0], labels) if 3 in sections else []
    require(mc[0] == len(materials), "material count mismatch")
    defs_raw, dc = sections[11][1], sections[11][0]
    require(defs_raw[:4] == b"\x01\x01\x01\x00" and
            len(defs_raw) == 8 + 3 * dc and read_at("<I", defs_raw, 4)[0] == dc,
            "unsupported DEFINITIONS block")
    definition_name = index_list(defs_raw, 8, dc, len(labels))
    definition_mesh = index_list(defs_raw, 8 + 2 * dc, dc, mc[2], nullable=True)
    definition_kinds = list(defs_raw[8 + dc:8 + 2 * dc])
    require(definition_kinds[0] == 1 and all(k == 3 for k in definition_kinds[1:]),
            "invalid definition hierarchy")
    ins_raw, ic = sections[12][1], sections[12][0]
    require(len(ins_raw) == 12 + 10 * ic and ins_raw[:4] == b"\x01\x01\x01\x01" and
            read_at("<I", ins_raw, 8)[0] == ic, "unsupported INSTANCES block")
    iname = index_list(ins_raw, 12, ic, len(labels))
    ikind = list(take(ins_raw, 12 + ic, ic))
    parent = index_list(ins_raw, 12 + 2 * ic, ic, ic, nullable=True)
    idef = index_list(ins_raw, 12 + 3 * ic, ic, dc)
    itrans = index_list(ins_raw, 12 + 4 * ic, ic, mc[6])
    require(parent[0] == 255 and all(0 <= parent[i] < i for i in range(1, ic)),
            "cycle or invalid parent tree")
    require(ikind[0] == 1 and all(k == 3 for k in ikind[1:]) and
            all(idef[i] == i for i in range(ic)), "invalid instance to definition relationship")
    xf_raw, tc = sections[13][1], sections[13][0]
    require(xf_raw[:4] == b"\x01\x01\x00\x00" and
            read_at("<II", xf_raw, 4) == (tc, tc * 96) and
            len(xf_raw) == 12 + tc * 96, "invalid TRANSFORMS")
    matrices = [read_at("<12d", xf_raw, 12 + 96 * i) for i in range(tc)]
    for matrix in matrices:
        require(all(math.isfinite(v) and abs(v) <= 1e6 for v in matrix),
                "nonfinite affine")
        a,b,c,d,e,f,g,h,i = matrix[:9]
        determinant = a * (e*i-f*h) - d * (b*i-c*h) + g * (b*f-c*e)
        require(abs(determinant) > 1e-12, "singular affine")
    coverage = read_at("<6I", sections[17][1])
    require(sections[17][0] == 1 and len(sections[17][1]) == 24,
            "invalid COVERAGE")
    require(sections[20][0] == 1 and len(sections[20][1]) == 76,
            "invalid ENCODING_CONTRACT")
    require(coverage == (mc[3], mc[3], 0, 0, 0, 0),
            "coverage fails actual face accounting")
    faces, meshes, vertex_total, triangle_total = [], [], 0, 0
    if geom:
        fr, fc = sections[6][1], sections[6][0]
        require(len(fr) >= 24 and fr[:4] == b"\x01\x01\x01\x01" and
                read_at("<I", fr, 4)[0] == fc, "invalid FACES block")
        face_count, loop_count, len_a, len_b, len_c = read_at("<5I", fr, 4)
        require(face_count == mc[3] and loop_count == fc, "FACES count mismatch")
        require(len(fr) >= 24 + 7*fc + len_a + len_b + len_c, "FACES column overflow")
        columns = [take(fr, 24 + k*fc, fc) for k in range(7)]
        cursor = 24 + 7 * fc
        nloops = var_column(take(fr, cursor, len_a), fc); cursor += len_a
        ntri = var_column(take(fr, cursor, len_b), fc); cursor += len_b
        nverts = var_column(take(fr, cursor, len_c), loop_count); cursor += len_c
        require(cursor == len(fr), "trailing face columns")
        require(all(i == 1 for i in nloops) and
                all(i >= 3 for i in nverts) and
                all(i and i % 3 == 0 for i in ntri),
                "invalid face/loop/triangle counts")
        normal_raw = sections[9][1]
        require(normal_raw[:4] == b"\x01\x03\x00\x00" and
                read_at("<II", normal_raw, 4) == (fc, fc*24) and
                len(normal_raw) == 12 + 24*fc, "invalid Float64 normals")
        normals = [read_at("<3d", normal_raw, 12+24*i) for i in range(fc)]
        require(all(all(math.isfinite(v) for v in n) and norm(n) > 1e-12
                    for n in normals), "invalid face normal")
        mesh_raw, mn = sections[5][1], sections[5][0]
        require(mesh_raw[:4] == b"\x01\x01\x00\x00" and
                read_at("<I", mesh_raw, 4)[0] == mn and
                len(mesh_raw) == 8+45*mn, "invalid MESHES")
        owner = index_list(mesh_raw, 8, mn, dc)
        cols = [read_at("<" + "I"*mn, mesh_raw, 8 + mn + 4*mn*j)
                for j in range(11)]
        require(len(set(owner)) == mn and
                all(definition_mesh[d] == j for j, d in enumerate(owner)),
                "inconsistent definition/mesh references")
        pos_raw, topo_raw = sections[7][1], sections[8][1]
        face_seen = []
        for j in range(mn):
            vcount, first_face, nf = cols[0][j], cols[1][j], cols[2][j]
            require(3 <= vcount <= 8192 and 0 < nf <= 4096 and
                    first_face + nf <= fc, "invalid mesh face/vertex count")
            face_seen.extend(range(first_face, first_face+nf))
            po, pl, to, tl = [cols[k][j] for k in (5,6,7,8)]
            pb, tb = take(pos_raw, po, pl), take(topo_raw, to, tl)
            require(pb[:4] == b"\x01\x01\x00\x00" and
                    read_at("<II", pb, 4) == (vcount, 24*vcount) and
                    len(pb) == 60+vcount*24, "invalid POSITIONS block")
            verts = [read_at("<3d", pb, 60+24*k) for k in range(vcount)]
            require(all(math.isfinite(v) and abs(v) <= 1e6 for p in verts for v in p),
                    "nonfinite/out-of-budget positions")
            require(tb[:4] == b"\x01\x00\x00\x00" and len(tb) >= 20,
                    "invalid TOPOLOGY header")
            lc, tc2, lb, trb = read_at("<4I", tb, 4)
            require(len(tb) == 20+lb+trb, "topology sizes")
            loops = delta_column(take(tb, 20, lb), lc, vcount)
            triangles = delta_column(take(tb, 20+lb, trb), tc2, vcount)
            require(sum(nverts[first_face:first_face+nf]) == lc and
                    sum(ntri[first_face:first_face+nf]) == tc2,
                    "topology loop/triangle counts disagree")
            lpos = tpos = 0
            for i in range(first_face, first_face+nf):
                length = nverts[i]
                ring = [verts[v] for v in loops[lpos:lpos+length]]
                lpos += length
                normal = normals[i]
                vector_area = signed_area(ring)
                require(dot(vector_area, normal) > 1e-10,
                        "face winding/normal disagreement")
                fan = triangles[tpos:tpos+ntri[i]]
                tpos += ntri[i]
                tri_area = 0.
                for t in range(0, len(fan), 3):
                    a,b,c = [verts[x] for x in fan[t:t+3]]
                    ar = cross(tuple(b[k]-a[k] for k in range(3)),
                               tuple(c[k]-a[k] for k in range(3)))
                    require(dot(ar, normal) > 1e-12,
                            "triangle reversed/degenerate")
                    tri_area += norm(ar)*.5
                require(math.isclose(tri_area, norm(vector_area)*.5,
                                     rel_tol=1e-7, abs_tol=1e-7),
                        "face triangulation does not cover ring")
                front, back, lab = [columns[k][i] for k in (3,4,6)]
                require(front == 255 or front < len(materials), "front material reference")
                require(back == 255 or back < len(materials), "back material reference")
                require(lab < len(labels), "face semantic label")
                faces.append({"label": labels[lab], "surface": columns[0][i],
                              "role": columns[2][i], "front": None if front==255 else materials[front]["name"],
                              "back": None if back==255 else materials[back]["name"],
                              "ring": ring, "triangleCount": len(fan)//3})
                triangle_total += len(fan)//3
            require(lpos == lc and tpos == tc2, "topology leftover indices")
            vertex_total += vcount
            meshes.append({"definition": labels[definition_name[owner[j]]],
                           "owner": owner[j], "vertices": verts, "faceCount": nf})
        require(sorted(face_seen) == list(range(fc)), "face rows not exactly assigned")
    else:
        require(mc[3] == mc[0] == 0 and (3 not in sections),
                "metadata profile cannot secretly carry materials/faces")
    world = []
    for i in range(ic):
        mesh_index = definition_mesh[idef[i]]
        if mesh_index == 255:
            continue
        path = []
        cursor = i
        while cursor != 255:
            path.append(matrices[itrans[cursor]])
            cursor = parent[cursor]
            require(len(path) <= ic, "cyclic parent path")
        for p in meshes[mesh_index]["vertices"]:
            for matrix in path:
                p = transform(matrix, p)
            world.append(p)
    if world:
        computed = [min(p[k] for p in world) for k in range(3)] + [
            max(p[k] for p in world) for k in range(3)]
        require(all(math.isclose(x, y, abs_tol=1e-8, rel_tol=1e-8)
                    for x, y in zip(computed, bbox)), "world bounds disagree with MODEL")
    else:
        require(all(v == 0 for v in bbox), "empty geometry has nonzero bounds")
    return {
        "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob),
        "sections": sorted(sections), "sectionInventory": {
            str(s): {"count": n, "sha256": hashlib.sha256(p).hexdigest(),
                     "size": len(p)} for s, (n, p) in sections.items()},
        "materialCount": len(materials), "materials": materials,
        "meshCount": len(meshes), "faceCount": len(faces),
        "triangleCount": triangle_total, "vertexCount": vertex_total,
        "coverage": list(coverage), "bounds": list(bbox),
        "definitions": [labels[x] for x in definition_name],
        "instances": [{"name": labels[iname[i]],
                       "parent": None if parent[i] == 255 else labels[iname[parent[i]]],
                       "definition": labels[definition_name[idef[i]]],
                       "transform": list(matrices[itrans[i]])} for i in range(ic)],
        "faces": faces,
    }
