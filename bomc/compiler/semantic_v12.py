"""Independent BOMC 1.2 semantic geometry writer for BMB-020.

Wire layout is independently specified in BOM_COMPILED_FORMAT.md (v1.1)
and checked against the pinned v1.2 producer/decoder contracts. No producer
implementation is copied. Only strict Module IR floor/wall/opening solid
colors are currently representable; unsupported feature families fail closed.
"""
from __future__ import annotations

import hashlib
import math
import struct
import zlib

from bomc.adapter.writer_v12 import (
    ENTRY, HEADER, MAX_OUTPUT_BYTES, REQUIRED_SECTIONS, encode_graph, UnsupportedFeature,
)
from core.graph import dag

from core.project.projection import (  # shared pure projection (SE-01)
    MAX_FACES, MAX_VERTICES, MAX_TRIANGLES, MAX_MATERIALS, MAX_STRINGS,
    MAX_SOURCE_OPERATIONS, SURFACES, ROLES, GeometryEncodingError, _require, _scalar, _vec,
    _newell, _geometry_face, _face_key, _shape_faces, collect_module_faces, mesh_intermediate,
)

def _uint(v):
    _require(type(v) is int and 0 <= v <= 0xffffffff, "uint32 budget exceeded")
    return struct.pack("<I", v)


def _var(v):
    _require(type(v) is int and 0 <= v <= 0xffffffff, "invalid varuint")
    buf = bytearray()
    while v >= 128:
        buf.append((v & 127) | 128)
        v >>= 7
    buf.append(v)
    return bytes(buf)


def _delta(seq):
    old = 0
    chunks = []
    for x in seq:
        diff = x - old
        old = x
        zig = diff * 2 if diff >= 0 else -2 * diff - 1
        chunks.append(_var(zig))
    return b"".join(chunks)


def _index(seq):
    _require(all(x is None or type(x) is int and 0 <= x < 255 for x in seq),
             "one-byte index width exceeded")
    return bytes(255 if x is None else x for x in seq)


def _parse_sections(data):
    _, major, minor, endian, flags, count, start = HEADER.unpack_from(data)
    _require((major, minor, endian, flags) == (1, 2, 0x01020304, 0x11),
             "unexpected base BOMC profile")
    _require(start == HEADER.size, "unexpected directory placement")
    sections = {}
    for idx in range(count):
        sid, codec, flags, off, stored, raw, records, checksum = ENTRY.unpack_from(
            data, HEADER.size + idx * ENTRY.size)
        _require(sid not in sections and codec == flags == 0 and stored == raw,
                 "invalid base section descriptor")
        part = data[off:off + stored]
        _require(len(part) == stored and zlib.crc32(part) & 0xffffffff == checksum,
                 "invalid base CRC or section length")
        sections[sid] = (part, records)
    _require(tuple(sorted(sections)) == REQUIRED_SECTIONS,
             "unexpected base section inventory")
    return sections


def _strings(payload):
    version, a, b, c, count, size = struct.unpack_from("<4BII", payload)
    _require((version, a, b, c) == (1, 0, 0, 0), "invalid string dictionary")
    offsets = struct.unpack_from("<" + "I" * (count + 1), payload, 12)
    text = payload[12 + 4 * (count + 1):]
    _require(len(text) == size and offsets[0] == 0 and offsets[-1] == size,
             "invalid string byte size")
    return [text[offsets[i]:offsets[i+1]].decode("utf-8") for i in range(count)]


def _encode_strings(names):
    content = b"".join(s.encode("utf-8") for s in names)
    offsets = [0]
    for s in names:
        offsets.append(offsets[-1] + len(s.encode("utf-8")))
    return (struct.pack("<4BII", 1, 0, 0, 0, len(names), len(content)) +
            struct.pack("<" + "I" * len(offsets), *offsets) + content)


def _mesh(faces):
    """Encode the shared canonical mesh intermediate into BOMC position/topology blocks."""
    coords, flat_loops, flat_triangles, logical, _ = mesh_intermediate(faces)
    position_data = struct.pack("<" + "d" * (3 * len(coords)),
                                *(c for pt in coords for c in pt))
    position_block = (struct.pack("<4BII", 1, 1, 0, 0, len(coords), len(position_data)) +
                      struct.pack("<6d", *(0.0 for _ in range(6))) + position_data)
    ldelta, tdelta = _delta(flat_loops), _delta(flat_triangles)
    topology_block = (struct.pack("<4BIIII", 1, 0, 0, 0, len(flat_loops),
                                  len(flat_triangles), len(ldelta), len(tdelta)) +
                      ldelta + tdelta)
    return coords, position_block, topology_block, logical


def _aligned_append(buffer, part):
    while len(buffer) & 7:
        buffer.append(0)
    start = len(buffer)
    buffer.extend(part)
    return start, len(part)


def _pack_container(sections):
    position = (HEADER.size + ENTRY.size * len(sections) + 7) & ~7
    directory = bytearray()
    result = bytearray(HEADER.pack(b"BOMC\r\n\x1a\n", 1, 2, 0x01020304, 0x11,
                                   len(sections), HEADER.size))
    for sid, (data, count) in sorted(sections.items()):
        _require(0 <= count <= 0xffffffff and len(data) <= 0xffffffff,
                 "section size budget exceeded")
        directory.extend(ENTRY.pack(sid, 0, 0, position, len(data), len(data),
                                    count, zlib.crc32(data) & 0xffffffff))
        position = (position + len(data) + 7) & ~7
    result.extend(directory)
    for sid, (data, _) in sorted(sections.items()):
        _aligned_append(result, data)
    _require(len(result) <= MAX_OUTPUT_BYTES, "compiled BOMC output exceeds 2 MiB")
    return bytes(result)


def encode_semantic(assembly, nodes):
    """Compile nonempty floor/wall/cut geometry with true BOMC 1.2 tables."""
    _require(len(nodes) <= 128, "metadata node budget exceeded")
    base = _parse_sections(encode_graph({
        "schemaVersion": "bmb-writer-graph-v1",
        "name": "BOMC Builder assembly", "nodes": nodes,
    }))
    base_strings = _strings(base[2][0])
    module_faces = collect_module_faces(assembly)

    materials = {}
    for mid, module in sorted(assembly.modules.items()):
        for mat in sorted(module["materials"], key=lambda m: m["materialId"]):
            key = (mid, mat["materialId"])
            _require(key not in materials, "duplicate authored material")
            materials[key] = mat
    _require(len(materials) <= MAX_MATERIALS, "material budget exceeded")
    used_materials = {(mid, mat) for mid, faces in module_faces.items()
                      for f in faces for mat in (f["front"], f["back"]) if mat is not None}
    _require(used_materials <= materials.keys(), "unknown referenced material")
    _require(set(materials) == used_materials, "unreferenced authored material cannot be discarded")

    material_keys = sorted(materials)
    material_ids = {key: i for i, key in enumerate(material_keys)}
    mnames = {key: key[0] + "/" + key[1] for key in material_keys}
    labels = {f["label"] for faces in module_faces.values() for f in faces}
    names = sorted(set(base_strings) | set(mnames.values()) | labels)
    _require(len(names) <= MAX_STRINGS, "string table exceeds single-byte profile")
    strids = {s: i for i, s in enumerate(names)}
    mapping = {i: strids[s] for i, s in enumerate(base_strings)}

    sections = dict(base)
    sections[2] = (_encode_strings(names), len(names))
    model = bytearray(base[1][0])
    _require(model[2] == 1, "base string index width changed")
    model[93] = mapping[model[93]]
    # definitions and instances require remapping old string dictionary refs
    defs = bytearray(base[11][0])
    ndefs = base[11][1]
    _require(defs[1] == defs[2] == 1, "base definition width unsupported")
    for i in range(ndefs):
        defs[8 + i] = mapping[defs[8 + i]]
    instances = bytearray(base[12][0])
    ninstances = base[12][1]
    _require(instances[1] == instances[2] == instances[3] == 1, "base instance width unsupported")
    for i in range(ninstances):
        instances[12 + i] = mapping[instances[12 + i]]

    # Source module labels identify unique definition records without any
    # dependence on the hashed implementation-only node IDs.
    def_names = [names[defs[8 + i]] for i in range(ndefs)]
    refs = {name: i for i, name in enumerate(def_names)}
    positions, topologies = bytearray(), bytearray()
    meshes, all_faces, all_normals = [], [], []
    world_points = []
    for mid, faces in sorted(module_faces.items()):
        _require(mid in refs, "missing module definition")
        coord, pblock, tblock, face_counts = _mesh(faces)
        poff, plen = _aligned_append(positions, pblock)
        toff, tlen = _aligned_append(topologies, tblock)
        mesh_id = len(meshes)
        mesh_definition_index = refs[mid]
        # Definition table: [header 8][names N][kinds N][mesh refs N].
        mesh_refs_start = 8 + ndefs * 2
        _require(defs[mesh_refs_start + mesh_definition_index] == 255,
                 "definition already owns another mesh")
        defs[mesh_refs_start + mesh_definition_index] = mesh_id
        meshes.append((mesh_definition_index, len(coord), len(all_faces),
                       len(faces), poff, plen, toff, tlen))
        for f, (loop_length, triangle_length) in zip(faces, face_counts):
            front = material_ids.get((mid, f["front"])) if f["front"] else None
            back = material_ids.get((mid, f["back"])) if f["back"] else None
            all_faces.append((SURFACES[f["role"]], 0, ROLES[f["role"]],
                              front, back, strids[f["label"]], loop_length, triangle_length))
            all_normals.extend(f["normal"])
        xform = assembly.world_transforms[mid]
        for point in coord:
            p = dag.apply_point(xform, point)
            _require(all(math.isfinite(v) and abs(v) <= 1e6 for v in p),
                     "transformed geometry exceeds world budget")
            world_points.append(p)
    _require(len(all_faces) <= MAX_FACES and len(world_points) <= MAX_FACES * MAX_VERTICES,
             "aggregate geometry budget exceeded")

    # Section 3: v1.2 material table v2 including no-texture solid colors.
    count = len(material_keys)
    matsec = bytearray(struct.pack("<4BI", 2, 1, 1, 0, count))
    matsec.extend(_index([strids[mnames[k]] for k in material_keys]))
    matsec.extend(_index([strids[mnames[k]] for k in material_keys]))
    matsec.extend(bytes(channel for k in material_keys for channel in materials[k]["rgba"]))
    matsec.extend(struct.pack("<" + "H" * count, *(int(materials[k]["opacity"]*65535 + 0.5)
                                                 for k in material_keys)))
    matsec.extend(_index([None] * count))
    matsec.extend(bytes(count * 8))  # Float32 texture width and height = 0.
    matsec.extend(bytes(count * 2))  # material type=0; semantic colorize=0.
    matsec.extend(bytes(count * 24))  # three colorize Float64 deltas = zero.
    matsec.extend(bytes(count * 32))  # no semantic colorize SHA.
    if count:
        sections[3] = (bytes(matsec), count)

    nmeshes = len(meshes)
    meshes_sec = bytearray(struct.pack("<4BI", 1, 1, 0, 0, nmeshes))
    meshes_sec.extend(_index([m[0] for m in meshes]))
    mesh_columns = (
        [m[1] for m in meshes], [m[2] for m in meshes],
        [m[3] for m in meshes], [0] * nmeshes,
        [0] * nmeshes, [m[4] for m in meshes],
        [m[5] for m in meshes], [m[6] for m in meshes],
        [m[7] for m in meshes], [0] * nmeshes,
        [0] * nmeshes,
    )
    for col in mesh_columns:
        meshes_sec.extend(struct.pack("<" + "I" * nmeshes, *col))
    sections[5] = (bytes(meshes_sec), nmeshes)

    fcount = len(all_faces)
    loop_var = b"".join(_var(1) for _ in all_faces)
    tri_var = b"".join(_var(f[7]) for f in all_faces)
    lens_var = b"".join(_var(f[6]) for f in all_faces)
    faces_sec = bytearray(struct.pack("<4BIIIII", 1, 1, 1, 1, fcount, fcount,
                                      len(loop_var), len(tri_var), len(lens_var)))
    for col in (bytes(f[0] for f in all_faces),
                bytes(f[1] for f in all_faces),
                bytes(f[2] for f in all_faces),
                _index([f[3] for f in all_faces]),
                _index([f[4] for f in all_faces]),
                _index([None] * fcount),
                _index([f[5] for f in all_faces])):
        faces_sec.extend(col)
    faces_sec.extend(loop_var + tri_var + lens_var)
    sections[6] = (bytes(faces_sec), fcount)
    sections[7] = (bytes(positions), nmeshes)
    sections[8] = (bytes(topologies), nmeshes)
    normal_data = struct.pack("<" + "d" * len(all_normals), *all_normals)
    sections[9] = (struct.pack("<4BII", 1, 3, 0, 0, fcount, len(normal_data)) +
                   normal_data, fcount)
    sections[11] = (bytes(defs), ndefs)
    sections[12] = (bytes(instances), ninstances)

    if world_points:
        bbox = [min(p[i] for p in world_points) for i in range(3)] + [
            max(p[i] for p in world_points) for i in range(3)]
        struct.pack_into("<6d", model, 8, *bbox)
    model_counts = (count, 0, nmeshes, fcount, ndefs, ninstances,
                    base[13][1], 0, 0)
    struct.pack_into("<9I", model, 56, *model_counts)
    sections[1] = (bytes(model), 1)
    # Count actual serialized face rows, never source op count or forged positives.
    coverage = (fcount, fcount, 0, 0, 0, 0)
    sections[17] = (struct.pack("<6I", *coverage), 1)
    data = _pack_container(sections)
    return data, {
        "geometrySemanticsValid": True,
        "modelCounts": model_counts,
        "coverage": coverage,
        "vertexCount": sum(m[1] for m in meshes),
        "faceCount": fcount,
        "triangleCount": sum(f[7] // 3 for f in all_faces),
        "materialCount": count,
        "meshCount": nmeshes,
        "sectionIds": tuple(sorted(sections)),
    }
