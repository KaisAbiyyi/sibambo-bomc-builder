#!/usr/bin/env python3
"""BMB-007 independently authored synthetic BOMC container fixture harness.

All section payloads are opaque invented markers, NOT semantic BOMC tables.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

MAGIC = b"BOMC\r\n\x1a\n"
HEADER = struct.Struct("<8sHHIIIQ")
ENTRY = struct.Struct("<HBBIIIII")
FLAGS = 0x11
BASE = (1, 2, 11, 12, 13, 17, 20)
LIMIT = 2 * 1024 * 1024
RECIPES = {
    "minimal": ({}, "empty synthetic root"),
    "floor": ({3: 1, 5: 1, 6: 6, 7: 8, 8: 6, 9: 6}, "fictitious flat slab"),
    "holed-wall": ({3: 1, 5: 1, 6: 8, 7: 16, 8: 8, 9: 8}, "fictitious wall with hole"),
    "concave": ({5: 1, 6: 1, 7: 5, 8: 1, 9: 1}, "fictitious concave face"),
    "nested-affine": ({5: 1, 6: 3, 7: 9, 8: 3, 9: 3}, "fictitious mirrored/sheared occurrences"),
    "face-materials": ({3: 2, 5: 1, 6: 2, 7: 8, 8: 2, 9: 2}, "fictitious front/back materials"),
}

class InvalidBomc(ValueError):
    pass

def align8(value: int) -> int:
    return (value + 7) & ~7

def generate(case: str) -> bytes:
    if case not in RECIPES:
        raise ValueError("unknown synthetic case")
    sections = {s: 1 for s in BASE}
    sections.update(RECIPES[case][0])
    offset = align8(HEADER.size + len(sections) * ENTRY.size)
    directory = bytearray()
    chunks = []
    for typ, count in sorted(sections.items()):
        raw = b"SYNTHETIC_CONTAINER_ONLY\x00" + json.dumps(
            {"case": case, "section": typ, "count": count}, sort_keys=True,
            separators=(",", ":")).encode("utf8")
        directory += ENTRY.pack(typ, 0, 0, offset, len(raw), len(raw),
                                count, zlib.crc32(raw))
        chunks.append((offset, raw))
        offset = align8(offset + len(raw))
    result = bytearray(HEADER.pack(MAGIC, 1, 2, 0x01020304, FLAGS,
                                   len(sections), HEADER.size))
    result.extend(directory)
    for position, raw in chunks:
        result.extend(b"\0" * (position - len(result)))
        result.extend(raw)
    return bytes(result)

def inspect_container(data: bytes) -> list[dict]:
    if len(data) < HEADER.size or len(data) > LIMIT:
        raise InvalidBomc("truncated header or input budget")
    magic, major, minor, endian, flags, count, directory_offset = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise InvalidBomc("magic")
    if (major, minor) != (1, 2):
        raise InvalidBomc("version")
    if endian != 0x01020304:
        raise InvalidBomc("endian")
    if flags != FLAGS:
        raise InvalidBomc("unknown flags")
    if count < 1 or count > 64 or directory_offset != HEADER.size:
        raise InvalidBomc("invalid directory header")
    end = directory_offset + count * ENTRY.size
    if end > len(data):
        raise InvalidBomc("truncated directory")
    last_type = -1
    ranges, rows, raw_total = [], [], 0
    for i in range(count):
        typ, codec, section_flags, off, size, raw_size, logical_count, crc = ENTRY.unpack_from(
            data, directory_offset + i * ENTRY.size)
        if typ <= last_type:
            raise InvalidBomc("unsorted or duplicate sections")
        last_type = typ
        if codec not in (0, 1) or section_flags:
            raise InvalidBomc("unsupported codec or section flags")
        if off % 8 or off < align8(end) or off + size > len(data):
            raise InvalidBomc("section bounds or alignment")
        if raw_size > LIMIT - raw_total:
            raise InvalidBomc("raw expansion budget")
        raw_total += raw_size
        stored = data[off:off + size]
        if zlib.crc32(stored) != crc:
            raise InvalidBomc("CRC")
        if codec == 0:
            decoded = stored
        else:
            inflater = zlib.decompressobj()
            try:
                decoded = inflater.decompress(stored, raw_size + 1)
            except zlib.error as exc:
                raise InvalidBomc("zlib") from exc
            if inflater.unconsumed_tail or inflater.unused_data or not inflater.eof:
                raise InvalidBomc("trailing or oversized compression")
        if len(decoded) != raw_size:
            raise InvalidBomc("expanded length")
        ranges.append((off, off + size))
        rows.append({"type": typ, "count": logical_count, "storedBytes": size,
                     "rawBytes": raw_size, "crc32": f"{crc:08x}"})
    ordered = sorted(ranges)
    if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        raise InvalidBomc("overlapping payloads")
    if not set(BASE).issubset(r["type"] for r in rows):
        raise InvalidBomc("missing baseline section")
    return rows

def corruptions(source: bytes) -> dict[str, bytes]:
    def change(at, data):
        result = bytearray(source)
        result[at:at + len(data)] = data
        return bytes(result)
    first_payload = ENTRY.unpack_from(source, HEADER.size)[3]
    return {
        "magic": change(0, b"WRNG"),
        "version-1.3": change(10, struct.pack("<H", 3)),
        "version-2.0": change(8, struct.pack("<H", 2)),
        "unknown-flag": change(16, struct.pack("<I", 0x80000011)),
        "truncated": source[:-1],
        "crc": change(first_payload, b"\xff"),
        "codec": change(HEADER.size + 2, b"\x02"),
        "expanded-budget": change(HEADER.size + 12, struct.pack("<I", LIMIT + 1)),
        "overlap-directory": change(HEADER.size + 4, struct.pack("<I", HEADER.size)),
        "duplicate-section": change(HEADER.size + ENTRY.size, struct.pack("<H", 1)),
    }

def build_all():
    blobs = {case: generate(case) for case in sorted(RECIPES)}
    entries = []
    for case, blob in blobs.items():
        rows = inspect_container(blob)
        entries.append({"name": case, "intent": RECIPES[case][1], "seed": 0,
                        "sha256": hashlib.sha256(blob).hexdigest(),
                        "byteSize": len(blob), "sectionCount": len(rows),
                        "sections": rows, "scope": "container-only",
                        "semanticBomcTablesValid": False,
                        "independentConsumerStatus": "NOT_RUN"})
    return blobs, {"schemaVersion": 1, "generator": "bmb-007-container-only-v1",
                   "warning": "OPAQUE SYNTHETIC PAYLOADS; NOT CONSUMER-VALID GOLDENS",
                   "cases": entries}

def write(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    blobs, meta = build_all()
    for name, data in blobs.items():
        (path / f"container-{name}.bomc").write_bytes(data)
    (path / "manifest.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf8")

def check(path: Path):
    blobs, expected = build_all()
    for name, data in blobs.items():
        assert (path / f"container-{name}.bomc").read_bytes() == data, name
        print(name, hashlib.sha256(data).hexdigest(), len(data))
    assert json.loads((path / "manifest.json").read_text(encoding="utf8")) == expected

def selftest():
    blobs, meta = build_all()
    assert len(blobs) == 6 and len(meta["cases"]) == 6
    assert all(generate(k) == blob for k, blob in blobs.items())
    for name, corrupted in corruptions(blobs["floor"]).items():
        try:
            inspect_container(corrupted)
        except InvalidBomc:
            pass
        else:
            raise AssertionError(f"accepted corruption: {name}")
    print("PASS 6 container-only variants, 10 negative structural vectors")

def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path)
    group.add_argument("--check", type=Path)
    group.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.write is not None:
        write(args.write)
    elif args.check is not None:
        check(args.check)
    else:
        selftest()

if __name__ == "__main__":
    main()
