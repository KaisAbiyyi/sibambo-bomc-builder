"""BMB-021: strict reader for the Builder BOMC 1.2 profile, independent of the writers.

It decodes bytes with its own parsing code (no import of the writers' encoders)
and rejects everything outside the profile: any rejection raises `Rejected`.
It is a Builder-owned oracle, NOT the original Editor E4 or Model-Eval loaders;
passing it never counts as a consumer pairing.
"""
from __future__ import annotations

import hashlib
import math
import struct
import zlib

MAGIC = b"BOMC\r\n\x1a\n"
HEADER = struct.Struct("<8sHHIIIQ")
ENTRY = struct.Struct("<HBBIIIII")
PROFILE_FLAGS = 0x11
REQUIRED = frozenset({1, 2, 11, 12, 13, 17, 20})
GEOMETRY = frozenset({5, 6, 7, 8, 9})
PROFILE = REQUIRED | GEOMETRY | {3}        # anything else, including Editor section 241, is rejected
MAX_BYTES = 2 * 1024 * 1024
MAX_SECTIONS = 32
MAX_ITEMS = 100_000
CONTRACT = struct.pack("<HBBQddQddddBBBBI", 1, 1, 0, 0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 1, 1, 1, 1, 1)
LOW_LEVEL = (struct.error, IndexError, ValueError, UnicodeDecodeError, OverflowError,
             ZeroDivisionError, KeyError, TypeError)


class Rejected(ValueError):
    """The bytes are not a valid Builder-profile BOMC 1.2 file."""


def need(ok: bool, why: str) -> None:
    if not ok:
        raise Rejected(why)


def read(payload: bytes) -> dict:
    """Decode and fully validate; return a deterministic summary."""
    try:
        return _read(bytes(payload))
    except Rejected:
        raise
    except LOW_LEVEL as exc:
        raise Rejected(f"malformed payload: {type(exc).__name__}: {exc}") from exc


def _align8(n: int) -> int:
    return (n + 7) & ~7


def _varuint(blob: bytes, cursor: int) -> tuple[int, int]:
    """Unsigned LEB128, canonical only: at most 5 bytes, value < 2**32, no redundant trailing zero group.

    The repository's contract documents name the codec ("delta-varint") but do not state whether
    non-minimal encodings are permitted, so this is a Builder-profile policy: the Builder writers
    only ever emit minimal forms, and this reader refuses anything else rather than guessing.
    What other consumers do with non-minimal forms is NOT_RUN.
    """
    value = shift = 0
    for index in range(5):
        need(cursor < len(blob), "varuint truncated")
        byte = blob[cursor]
        cursor += 1
        value |= (byte & 127) << shift
        if byte < 128:
            need(not (index and byte == 0), "non-canonical (overlong) varuint")
            need(value <= 0xFFFFFFFF, "varuint overflows 32 bits")
            return value, cursor
        shift += 7
    raise Rejected("varuint unterminated or longer than 5 bytes")


def _column(blob: bytes, count: int) -> list[int]:
    out, cursor = [], 0
    for _ in range(count):
        value, cursor = _varuint(blob, cursor)
        out.append(value)
    need(cursor == len(blob), "column length mismatch")
    return out


def _deltas(blob: bytes, count: int) -> list[int]:
    out, cursor, last = [], 0, 0
    for _ in range(count):
        zig, cursor = _varuint(blob, cursor)
        last += (zig >> 1) if not zig & 1 else -((zig + 1) >> 1)
        out.append(last)
    need(cursor == len(blob), "delta column length mismatch")
    return out


def _refs(data: bytes, count: int) -> list[int | None]:
    need(len(data) >= count, "reference column truncated")
    return [None if b == 255 else b for b in data[:count]]


def _newell(ring: list[tuple[float, float, float]]) -> list[float]:
    out = [0.0, 0.0, 0.0]
    for p, q in zip(ring, ring[1:] + ring[:1]):
        for j in range(3):
            out[j] += (p[(j + 1) % 3] - q[(j + 1) % 3]) * (p[(j + 2) % 3] + q[(j + 2) % 3])
    return out


def _container(data: bytes) -> dict[int, tuple[int, bytes]]:
    need(HEADER.size <= len(data) <= MAX_BYTES, "size outside the budget")
    magic, major, minor, endian, flags, count, directory = HEADER.unpack_from(data)
    need(magic == MAGIC, "bad magic")
    need((major, minor) == (1, 2), "unsupported version")
    need(endian == 0x01020304, "bad endian marker")
    need(flags == PROFILE_FLAGS, "unsupported header flags")
    need(1 <= count <= MAX_SECTIONS and directory == HEADER.size, "bad directory header")
    table_end = directory + count * ENTRY.size
    need(table_end <= len(data), "truncated directory")
    sections: dict[int, tuple[int, bytes]] = {}
    spans, last, end_of_data = [], -1, 0
    for i in range(count):
        sid, codec, sflags, offset, stored, raw, items, crc = ENTRY.unpack_from(data, directory + i * ENTRY.size)
        need(sid > last, "sections not strictly ascending")
        last = sid
        need(sid in PROFILE, f"section {sid} is outside the Builder profile")
        need(codec == 0 and sflags == 0 and stored == raw, "compression or section flags are not part of the profile")
        need(offset % 8 == 0 and offset >= _align8(table_end) and offset + stored <= len(data), "section bounds or alignment")
        need(items <= MAX_ITEMS, "item count budget")
        part = data[offset:offset + stored]
        need(zlib.crc32(part) & 0xffffffff == crc, f"section {sid} CRC mismatch")
        spans.append((offset, offset + stored))
        end_of_data = max(end_of_data, offset + stored)
        sections[sid] = (items, part)
    spans.sort()
    need(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), "overlapping sections")
    need(len(data) == end_of_data, "trailing bytes after the last section")
    need(REQUIRED <= set(sections), "missing required section")
    need(set(sections) & GEOMETRY in (set(), set(GEOMETRY)), "geometry sections must appear together")
    return sections


def _read(data: bytes) -> dict:
    sections = _container(data)
    # 2 STRINGS
    items, text = sections[2]
    need(len(text) >= 12 and text[:4] == bytes((1, 0, 0, 0)), "bad string table header")
    count, size = struct.unpack_from("<II", text, 4)
    need(count == items, "string count mismatch")
    offsets = struct.unpack_from("<" + "I" * (count + 1), text, 12)
    blob = text[12 + 4 * (count + 1):]
    need(len(blob) == size and offsets[0] == 0 and offsets[-1] == size
         and all(a <= b for a, b in zip(offsets, offsets[1:])), "bad string offsets")
    strings = [blob[offsets[i]:offsets[i + 1]].decode("utf-8") for i in range(count)]
    need(strings == sorted(set(strings)), "strings must be unique and sorted")

    # 1 MODEL
    _, model = sections[1]
    need(len(model) >= 92 and model[0] == 1 and model[1] == 1 and model[3] == 5, "bad model header")
    width = model[2]
    need(width in (1, 2, 4) and len(model) == 92 + 2 * width, "bad model length")
    bounds = struct.unpack_from("<6d", model, 8)
    need(all(math.isfinite(v) for v in bounds) and all(bounds[i] <= bounds[i + 3] for i in range(3)), "bad bounds")
    materials, unused1, meshes, faces, defs, instances, transforms, unused2, unused3 = struct.unpack_from("<9I", model, 56)
    need(unused1 == unused2 == unused3 == 0, "model counts outside the profile are not zero")
    need(sections[1][0] == sections[17][0] == sections[20][0] == 1, "singleton sections must have one item")
    need(model[4:8] == bytes(4) and model[92] == 255, "bad model header tail or name slot")
    title = model[93]
    need(title < count, "model title reference out of range")
    need(sections[3][0] == materials if 3 in sections else materials == 0, "material section item count")
    need(defs == sections[11][0] and instances == sections[12][0] and transforms == sections[13][0],
         "definition, instance or transform count mismatch")
    need(sections[17][1] == struct.pack("<6I", *_coverage(sections, faces)) , "coverage does not match the face table")
    need(sections[20][1] == CONTRACT, "encoding contract is not the pinned zero-error profile")

    # 13 TRANSFORMS
    items, tdata = sections[13]
    need(len(tdata) >= 12 and tdata[:4] == bytes((1, 1, 0, 0)), "bad transform header")
    tcount, tlength = struct.unpack_from("<II", tdata, 4)
    need(tcount == items == transforms and tlength == 96 * tcount and len(tdata) == 12 + tlength, "bad transform length")
    matrices = [struct.unpack_from("<12d", tdata, 12 + 96 * i) for i in range(tcount)]
    for m in matrices:
        need(all(math.isfinite(v) and abs(v) <= 1e6 for v in m), "non-finite or huge transform")
        # 12 doubles = three column vectors of the linear part, then the translation
        det = (m[0] * (m[4] * m[8] - m[5] * m[7]) - m[3] * (m[1] * m[8] - m[2] * m[7])
               + m[6] * (m[1] * m[5] - m[2] * m[4]))
        need(abs(det) > 1e-9, "singular transform")

    nodes = _nodes(sections, count, defs, instances)
    summary = {"sections": tuple(sorted(sections)), "bounds": bounds, "strings": strings, "nodes": [strings[i] for i in nodes["names"]],
               "counts": {"materials": materials, "meshes": meshes, "faces": faces, "definitions": defs,
                          "instances": instances, "transforms": transforms},
               "transforms": matrices, "faces": [], "colors": [], "triangles": 0}
    if not GEOMETRY & set(sections):
        need(materials == meshes == faces == 0 and 3 not in sections, "counts without geometry sections")
        need(all(v == 0.0 for v in bounds), "bounds without geometry")
        need(all(r is None for r in nodes["meshRefs"]), "mesh reference without geometry sections")
        return summary
    _geometry(sections, summary, strings, materials, meshes, faces)
    _check_nodes_and_bounds(summary, nodes, matrices, meshes, bounds)
    return summary


def _coverage(sections, faces):
    return (faces, faces, 0, 0, 0, 0)


def _geometry(sections, summary, strings, materials, meshes, faces):
    need(meshes > 0 and faces > 0, "geometry sections without meshes or faces")
    if materials:
        need(3 in sections, "materials counted but section 3 missing")
        mdata = sections[3][1]
        need(mdata[:4] == bytes((2, 1, 1, 0)) and struct.unpack_from("<I", mdata, 4)[0] == materials, "bad material table")
        need(len(mdata) == 8 + materials * (2 + 4 + 2 + 1 + 4 + 4 + 1 + 1 + 24 + 32), "bad material length")
        at = 8
        names = _refs(mdata[at:], materials); at += materials
        again = _refs(mdata[at:], materials); at += materials
        need(names == again and all(n is not None and n < len(strings) for n in names), "material name out of range")
        summary["colors"] = [tuple(mdata[at + 4 * i:at + 4 * i + 4]) for i in range(materials)]; at += 4 * materials
        opacity = struct.unpack_from("<" + "H" * materials, mdata, at); at += 2 * materials
        summary["opacity"] = list(opacity)
        need(all(b == 255 for b in mdata[at:at + materials]), "texture reference present"); at += materials
        need(not any(mdata[at:]), "texture size, type, colorize or hash fields are not part of the profile")
    else:
        need(3 not in sections, "section 3 present without materials")

    fdata = sections[6][1]
    need(len(fdata) >= 24, "face table truncated")
    version, mw, tw, sw, fcount, total_loops, a, b, c = struct.unpack_from("<4BIIIII", fdata)
    need((version, mw, tw, sw) == (1, 1, 1, 1) and fcount == faces == sections[6][0] and total_loops == fcount,
         "bad face table header")
    off = 24
    columns = []
    for _ in range(7):
        columns.append(fdata[off:off + fcount])
        need(len(columns[-1]) == fcount, "face column truncated")
        off += fcount
    surfaces, flags, roles = (list(columns[0]), list(columns[1]), list(columns[2]))
    fronts, backs, tags, labels = (_refs(col, fcount) for col in columns[3:])
    need(all(f == 0 for f in flags) and all(t is None for t in tags), "unsupported face flags or tags")
    need(all(x is None or x < materials for x in fronts + backs), "material reference out of range")
    need(all(x is None or x < len(strings) for x in labels), "label reference out of range")
    parts = []
    for size, n in ((a, fcount), (b, fcount), (c, total_loops)):
        parts.append(_column(fdata[off:off + size], n))
        off += size
    need(off == len(fdata), "face table length mismatch")
    loop_counts, triangle_counts, lengths = parts
    need(all(v == 1 for v in loop_counts) and all(v >= 3 for v in lengths)
         and all(v > 0 and v % 3 == 0 for v in triangle_counts), "bad loop or triangle counts")

    need(sections[7][0] == sections[8][0] == meshes and sections[9][0] == faces, "geometry section item counts")
    mesh = sections[5][1]
    need(mesh[:4] == bytes((1, 1, 0, 0)) and struct.unpack_from("<I", mesh, 4)[0] == meshes == sections[5][0], "bad mesh table")
    need(len(mesh) == 8 + meshes + 44 * meshes, "bad mesh table length")
    defs = _refs(mesh[8:], meshes)
    cols = [struct.unpack_from("<" + "I" * meshes, mesh, 8 + meshes + 4 * j * meshes) for j in range(11)]
    need(not any(cols[3]) and not any(cols[4]) and not any(cols[9]) and not any(cols[10]),
         "mesh table columns outside the profile are not zero")
    ndata = sections[9][1]
    need(ndata[:4] == bytes((1, 3, 0, 0)) and struct.unpack_from("<II", ndata, 4) == (fcount, 24 * fcount)
         and len(ndata) == 12 + 24 * fcount, "bad normal table")
    normals = list(struct.unpack_from("<" + "d" * (3 * fcount), ndata, 12))
    need(all(math.isfinite(v) for v in normals), "non-finite normal")
    covered, total_triangles = 0, 0
    digest, mesh_vertices = hashlib.sha256(), []
    used = {7: bytearray(len(sections[7][1])), 8: bytearray(len(sections[8][1]))}
    digest.update(ndata)
    for mi in range(meshes):
        vcount, fstart, flen = cols[0][mi], cols[1][mi], cols[2][mi]
        po, pl, to, tl = (cols[i][mi] for i in (5, 6, 7, 8))
        need(fstart == covered and fstart + flen <= fcount, "faces not partitioned across meshes")
        covered += flen
        ps, ts = sections[7][1][po:po + pl], sections[8][1][to:to + tl]
        for sid, at, size in ((7, po, pl), (8, to, tl)):
            need(at + size <= len(used[sid]) and not any(used[sid][at:at + size]), "mesh blocks overlap or leave the section")
            used[sid][at:at + size] = b"\x01" * size
        need(len(ps) == pl == 60 + 24 * vcount and ps[:4] == bytes((1, 1, 0, 0))
             and struct.unpack_from("<II", ps, 4) == (vcount, 24 * vcount), "bad position table")
        need(not any(ps[12:60]), "position block bounds are not part of the profile")
        verts = [struct.unpack_from("<3d", ps, 60 + 24 * j) for j in range(vcount)]
        need(all(math.isfinite(v) and abs(v) <= 1e6 for p in verts for v in p), "non-finite position")
        need(len(ts) == tl and len(ts) >= 20 and ts[:4] == bytes((1, 0, 0, 0)), "bad topology table")
        lcount, tcount, ll, tlb = struct.unpack_from("<4I", ts, 4)
        need(len(ts) == 20 + ll + tlb, "topology length mismatch")
        loops, tris = _deltas(ts[20:20 + ll], lcount), _deltas(ts[20 + ll:], tcount)
        need(all(0 <= k < vcount for k in loops + tris), "vertex index out of range")
        digest.update(struct.pack("<I", mi) + ps[60:] + struct.pack("<%dI" % (len(loops) + len(tris)), *(loops + tris)))
        mesh_vertices.append(verts)
        need(sum(lengths[fstart:fstart + flen]) == lcount and sum(triangle_counts[fstart:fstart + flen]) == tcount,
             "loop or triangle totals mismatch")
        at_l = at_t = 0
        for f in range(fstart, fstart + flen):
            ring = [verts[k] for k in loops[at_l:at_l + lengths[f]]]
            idx = tris[at_t:at_t + triangle_counts[f]]
            at_l, at_t = at_l + lengths[f], at_t + triangle_counts[f]
            normal = normals[3 * f:3 * f + 3]
            need(math.isclose(math.sqrt(sum(x * x for x in normal)), 1.0, abs_tol=1e-9), "normal is not a unit vector")
            newell = _newell(ring)
            need(sum(x * y for x, y in zip(newell, normal)) > 1e-9, "loop winding disagrees with the normal")
            area, tri_area = math.sqrt(sum(x * x for x in newell)) / 2, 0.0
            for i in range(0, len(idx), 3):
                p, q, r = (verts[idx[i + j]] for j in range(3))
                u = [q[t] - p[t] for t in range(3)]
                w = [r[t] - p[t] for t in range(3)]
                cross = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
                need(sum(cross[j] * normal[j] for j in range(3)) > 0, "triangle winding disagrees with the normal")
                tri_area += math.sqrt(sum(x * x for x in cross)) / 2
                total_triangles += 1
            need(math.isclose(tri_area, area, rel_tol=1e-7, abs_tol=1e-7), "triangles do not tile the face loop")
            summary["faces"].append({"surface": surfaces[f], "role": roles[f], "front": fronts[f], "back": backs[f],
                                     "label": strings[labels[f]] if labels[f] is not None else None,
                                     "normal": tuple(normal), "loop": len(ring), "triangles": len(idx) // 3, "area": area,
                                     "mesh": mi})
        need(at_l == len(loops) and at_t == len(tris), "unconsumed topology")
    need(covered == fcount, "meshes do not cover every face")
    for sid, marks in used.items():  # bytes between mesh blocks are alignment padding and must be zero; none trails
        need(all(m or b == 0 for m, b in zip(marks, sections[sid][1])), f"section {sid} has non-zero bytes outside mesh blocks")
        need(bool(marks) and marks[-1] == 1, f"section {sid} has trailing bytes after the last mesh block")
    need(len({d for d in defs}) == meshes, "meshes must reference distinct definitions")
    summary["triangles"] = total_triangles
    summary["meshDefinitions"] = defs
    summary["meshPositions"] = mesh_vertices
    summary["geometryDigest"] = digest.hexdigest()
    summary["meshVertices"] = [cols[0][i] for i in range(meshes)]


def _nodes(sections, string_count, defs, instances):
    """Definitions (11) and instances (12): single-byte-index profile, one instance per definition."""
    _, ddata = sections[11]
    n = defs
    need(n >= 1 and len(ddata) == 8 + 3 * n and ddata[:4] == bytes((1, 1, 1, 0))
         and struct.unpack_from("<I", ddata, 4)[0] == n, "bad definition table")
    names = list(ddata[8:8 + n])
    kinds = list(ddata[8 + n:8 + 2 * n])
    refs = _refs(ddata[8 + 2 * n:], n)
    need(all(x < string_count for x in names), "definition name out of range")
    need(kinds == [1] + [3] * (n - 1), "definition kinds must be one root followed by groups")
    _, idata = sections[12]
    need(instances == n and len(idata) == 12 + 10 * n and idata[:8] == bytes((1, 1, 1, 1, 1, 1, 0, 0))
         and struct.unpack_from("<I", idata, 8)[0] == n, "bad instance table")
    at = 12
    cols = []
    for _ in range(5):
        cols.append(list(idata[at:at + n]))
        at += n
    iname, ikind, parent, definition, transform = cols
    need(iname == names and ikind == kinds, "instances must mirror their definitions")
    need(definition == list(range(n)) and transform == list(range(n)), "instance definition or transform indexes")
    need(parent[0] == 255 and all(p < n for p in parent[1:]), "bad instance parents")
    need(all(b == 255 for b in idata[at:at + 2 * n]), "unexpected instance reference columns"); at += 2 * n
    need(list(idata[at:at + n]) == [1] * n and list(idata[at + n:at + 2 * n]) == [0] * n
         and all(b == 255 for b in idata[at + 2 * n:]), "unexpected instance flag columns")
    for i in range(1, n):  # every chain reaches the root without a cycle
        seen, p = {i}, parent[i]
        while p != 0:
            need(p not in seen, "instance parent cycle")
            seen.add(p)
            p = parent[p]
    return {"names": names, "meshRefs": refs, "parent": parent}


def _compose(parent, local):
    """Column-major 3x4 affine matrices (12 doubles): parent x local."""
    cols = [[sum(parent[3 * k + r] * local[3 * c + k] for k in range(3)) for r in range(3)] for c in range(3)]
    t = [sum(parent[3 * k + r] * local[9 + k] for k in range(3)) + parent[9 + r] for r in range(3)]
    return tuple(v for col in cols for v in col) + tuple(t)


def _check_nodes_and_bounds(summary, nodes, matrices, meshes, bounds):
    parent, refs = nodes["parent"], nodes["meshRefs"]
    world = {}

    def resolve(i):
        if i not in world:
            world[i] = matrices[i] if parent[i] == 255 else _compose(resolve(parent[i]), matrices[i])
        return world[i]

    owner = {}
    for definition, mesh in enumerate(refs):
        if mesh is not None:
            need(mesh < meshes and mesh not in owner, "mesh referenced by two definitions or out of range")
            owner[mesh] = definition
    need(sorted(owner) == list(range(meshes)), "every mesh must belong to a definition")
    need(all(summary["meshDefinitions"][m] == owner[m] for m in range(meshes)), "mesh table disagrees with definitions")
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for m, verts in enumerate(summary["meshPositions"]):
        w = resolve(owner[m])
        for x, y, z in verts:
            point = [w[0 + r] * x + w[3 + r] * y + w[6 + r] * z + w[9 + r] for r in range(3)]
            lo = [min(a, b) for a, b in zip(lo, point)]
            hi = [max(a, b) for a, b in zip(hi, point)]
    need(all(math.isclose(a, b, abs_tol=1e-9, rel_tol=1e-9) for a, b in zip(list(lo) + list(hi), bounds)),
         "model bounds do not match the transformed geometry")
    summary["worldTransforms"] = [resolve(i) for i in range(len(matrices))]
