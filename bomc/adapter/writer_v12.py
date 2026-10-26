"""BMB-019: clean-room BOMC 1.2 writer for a geometry-free authored node tree.

Only root and empty group instances are supported. This is a real semantic
metadata subset, NOT the opaque container-only BMB-007 fixture format.
Geometry, materials, UVs, scenes, editor section 241, and other features
must go through later, separately qualified compiler/interop work.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
from pathlib import Path
import zlib

MAGIC = b"BOMC\r\n\x1a\n"
HEADER = struct.Struct("<8sHHIIIQ")
ENTRY = struct.Struct("<HBBIIIII")
IDENTITY = (1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0)
AFFINE = (0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14)
REQUIRED_SECTIONS = (1, 2, 11, 12, 13, 17, 20)
MAX_NODES = 128
MAX_INPUT_BYTES = 1_000_000
MAX_OUTPUT_BYTES = 2_000_000
ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")


class UnsupportedFeature(ValueError):
    """Input is outside the explicitly qualified BMB-019 wire subset."""


def _require(test: bool, reason: str) -> None:
    if not test:
        raise UnsupportedFeature(reason)


def _fields(value: object, required: set[str], optional: set[str], label: str) -> dict:
    _require(isinstance(value, dict), f"{label}: expected object")
    _require(required <= value.keys(), f"{label}: missing {sorted(required - value.keys())}")
    _require(value.keys() <= required | optional,
             f"{label}: unsupported fields {sorted(value.keys() - required - optional)}")
    return value


def _name(value: object, label: str) -> str:
    _require(isinstance(value, str) and 1 <= len(value) <= 128,
             f"{label}: must be nonempty text up to 128 characters")
    _require(not any(ord(ch) < 32 for ch in value), f"{label}: control characters unsupported")
    return value


def _affine(value: object, label: str) -> tuple[float, ...]:
    _require(isinstance(value, list) and len(value) == 16,
             f"{label}: requires 16 column-major scalars")
    _require(all(type(v) in (float, int) and math.isfinite(v) for v in value),
             f"{label}: non-finite/non-numeric transform")
    matrix = tuple(float(v) for v in value)
    _require(matrix[3] == matrix[7] == matrix[11] == 0.0 and matrix[15] == 1.0,
             f"{label}: only affine transforms supported")
    a, b, c, d, e, f, g, h, i = (matrix[k] for k in (0, 4, 8, 1, 5, 9, 2, 6, 10))
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    _require(math.isfinite(det) and abs(det) > 1e-12,
             f"{label}: degenerate transform")
    return matrix


def _index_width(size: int) -> int:
    return 1 if size <= 255 else 2 if size <= 65535 else 4


def _indexes(values: list[int | None], width: int) -> bytes:
    ceiling = (1 << (width * 8)) - 1
    fmt = {1: "B", 2: "H", 4: "I"}[width]
    assert all(v is None or 0 <= v < ceiling for v in values)
    return struct.pack("<" + fmt * len(values),
                       *(ceiling if v is None else v for v in values))


def _align(size: int) -> int:
    return (size + 7) & ~7


def _validate_graph(value: object) -> tuple[str, list[dict]]:
    doc = _fields(value, {"schemaVersion", "name", "nodes"}, set(), "graph")
    _require(doc["schemaVersion"] == "bmb-writer-graph-v1", "unsupported graph schemaVersion")
    title = _name(doc["name"], "graph.name")
    nodes = doc["nodes"]
    _require(isinstance(nodes, list) and 1 <= len(nodes) <= MAX_NODES,
             "nodes must have 1..128 entries")
    by_id: dict[str, dict] = {}
    for index, candidate in enumerate(nodes):
        node = _fields(candidate, {"id", "kind", "name", "parentId", "transform"},
                       set(), f"nodes[{index}]")
        key = node["id"]
        _require(isinstance(key, str) and ID_PATTERN.fullmatch(key) is not None,
                 f"nodes[{index}]: invalid id")
        _require(key not in by_id, f"duplicate node id {key}")
        _require(node["kind"] in ("root", "group"), f"{key}: unsupported kind/geometry")
        _name(node["name"], f"{key}.name")
        _affine(node["transform"], key)
        by_id[key] = node
    _require("root" in by_id and by_id["root"]["kind"] == "root",
             "exactly one root node with id 'root' required")
    _require(sum(n["kind"] == "root" for n in nodes) == 1, "duplicate root kinds")
    root = by_id["root"]
    _require(root["parentId"] is None and tuple(root["transform"]) == IDENTITY,
             "root must be unparented with identity transform")
    for key, node in by_id.items():
        if key == "root":
            continue
        parent = node["parentId"]
        _require(isinstance(parent, str) and parent in by_id and parent != key,
                 f"{key}: parentId must reference a different existing node")
        seen = {key}
        while parent != "root":
            _require(parent not in seen, f"{key}: cycle detected")
            seen.add(parent)
            parent = by_id[parent]["parentId"]
            _require(isinstance(parent, str) and parent in by_id,
                     f"{key}: disconnected hierarchy")
    return title, [root] + [by_id[k] for k in sorted(by_id) if k != "root"]


def encode_graph(graph: object) -> bytes:
    """Compile the bounded, geometry-free node-tree subset into BOMC 1.2.

    All unknown semantic features are rejected; no synthetic marker payloads.
    Output is deterministic with respect to JSON object and node ordering.
    """
    title, nodes = _validate_graph(graph)
    names = sorted({title, *(node["name"] for node in nodes)})
    index = {value: i for i, value in enumerate(names)}
    count = len(nodes)
    sw = _index_width(len(names))
    dw = _index_width(count)
    tw = _index_width(count)

    data = b"".join(value.encode("utf-8") for value in names)
    offsets = [0]
    for name in names:
        offsets.append(offsets[-1] + len(name.encode("utf-8")))
    strings = struct.pack("<4BII", 1, 0, 0, 0, len(names), len(data))
    strings += struct.pack("<" + "I" * len(offsets), *offsets) + data

    model = struct.pack("<4BI", 1, 1, sw, 5, 0)
    model += struct.pack("<6d", *(0.0 for _ in range(6)))
    model += struct.pack("<9I", 0, 0, 0, 0, count, count, count, 0, 0)
    model += _indexes([None, index[title]], sw)

    definitions = struct.pack("<4BI", 1, sw, 1, 0, count)
    definitions += _indexes([index[n["name"]] for n in nodes], sw)
    definitions += bytes([1] + [3] * (count - 1))
    definitions += _indexes([None] * count, 1)

    node_ids = {n["id"]: i for i, n in enumerate(nodes)}
    instances = struct.pack("<8BI", 1, sw, dw, tw, 1, 1, 0, 0, count)
    instances += _indexes([index[n["name"]] for n in nodes], sw)
    instances += bytes([1] + [3] * (count - 1))
    instances += _indexes([None if n["id"] == "root" else
                           node_ids[n["parentId"]] for n in nodes], dw)
    instances += _indexes(list(range(count)), dw)
    instances += _indexes(list(range(count)), tw)
    instances += _indexes([None] * count, 1) * 2
    instances += bytes([1] * count)
    instances += bytes([0] * count)
    instances += _indexes([None] * count, sw)

    matrix_payload = b"".join(
        struct.pack("<12d", *(float(node["transform"][k]) for k in AFFINE))
        for node in nodes
    )
    transforms = struct.pack("<4BII", 1, 1, 0, 0, count, len(matrix_payload))
    transforms += matrix_payload
    coverage = struct.pack("<6I", 0, 0, 0, 0, 0, 0)
    # Section-20 revision-1 exact zero-error profile, no SketchUp source/texture budget.
    contract = struct.pack("<HBBQddQddddBBBBI",
                           1, 1, 0, 0, 0.0, 0.0, 0,
                           0.0, 0.0, 0.0, 0.0, 1, 1, 1, 1, 1)
    assert len(contract) == 76

    parts = {1: (model, 1), 2: (strings, len(names)),
             11: (definitions, count), 12: (instances, count),
             13: (transforms, count), 17: (coverage, 1), 20: (contract, 1)}
    assert tuple(sorted(parts)) == REQUIRED_SECTIONS
    position = _align(HEADER.size + len(parts) * ENTRY.size)
    directory = bytearray()
    output = bytearray(HEADER.pack(MAGIC, 1, 2, 0x01020304, 0x11,
                                   len(parts), HEADER.size))
    for section_id, (payload, item_count) in sorted(parts.items()):
        directory += ENTRY.pack(section_id, 0, 0, position, len(payload),
                                len(payload), item_count, zlib.crc32(payload) & 0xffffffff)
        position = _align(position + len(payload))
    output.extend(directory)
    for section_id, (payload, _) in sorted(parts.items()):
        output.extend(b"\0" * (_align(len(output)) - len(output)))
        output.extend(payload)
    _require(len(output) <= MAX_OUTPUT_BYTES, "output budget exceeded")
    return bytes(output)


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise UnsupportedFeature(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def load_graph(path: Path) -> object:
    _require(path.stat().st_size <= MAX_INPUT_BYTES, "input budget exceeded")
    return json.loads(path.read_text(encoding="utf-8"),
                      object_pairs_hook=_no_duplicates,
                      parse_constant=lambda name: (_ for _ in ()).throw(
                          UnsupportedFeature(f"invalid JSON numeric value: {name}")))


def main() -> None:
    parser = argparse.ArgumentParser(description="BMB-019 geometry-free BOMC 1.2 writer")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = encode_graph(load_graph(args.input))
        # No output is written for a rejected graph.
        args.output.write_bytes(payload)
    except (UnsupportedFeature, OSError, UnicodeError, ValueError) as error:
        parser.exit(2, f"BMB-019 reject: {error}\n")


if __name__ == "__main__":
    main()
