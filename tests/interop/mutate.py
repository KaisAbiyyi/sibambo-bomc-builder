"""BMB-021 container mutation helpers: parse, edit and re-lay-out BOMC files (CRCs recomputed on request)."""
from __future__ import annotations

import struct
import zlib

from tests.interop.reader import ENTRY, HEADER, MAGIC


def parse(payload: bytes) -> dict:
    magic, major, minor, endian, flags, count, directory = HEADER.unpack_from(payload)
    entries = []
    for i in range(count):
        sid, codec, sflags, offset, stored, raw, items, crc = ENTRY.unpack_from(payload, directory + i * ENTRY.size)
        entries.append({"id": sid, "codec": codec, "flags": sflags, "items": items, "raw": raw,
                        "data": bytes(payload[offset:offset + stored]), "crc": crc})
    return {"magic": magic, "major": major, "minor": minor, "endian": endian, "flags": flags, "entries": entries}


def build(model: dict, directory_offset: int = HEADER.size) -> bytes:
    """Lay the model out again: aligned payloads, CRC recomputed unless an entry pins `crc`."""
    entries = model["entries"]
    position = (directory_offset + len(entries) * ENTRY.size + 7) & ~7
    table, chunks = bytearray(), []
    for e in entries:
        crc = e["crc"] if e.get("crc") is not None and e.get("keep_crc") else zlib.crc32(e["data"]) & 0xffffffff
        raw = e["raw"] if e.get("raw") is not None else len(e["data"])
        table += ENTRY.pack(e["id"], e["codec"], e["flags"], position, len(e["data"]), raw, e["items"], crc)
        chunks.append((position, e["data"]))
        position = (position + len(e["data"]) + 7) & ~7
    out = bytearray(HEADER.pack(model["magic"], model["major"], model["minor"], model["endian"], model["flags"],
                                len(entries), directory_offset))
    out += table
    for at, data in chunks:
        out += b"\0" * (at - len(out))
        out += data
    return bytes(out)


def rebuild(payload: bytes, edit) -> bytes:
    """Parse, let `edit(model)` change it in place, and lay it out again with valid CRCs."""
    model = parse(payload)
    for e in model["entries"]:
        e["raw"] = None
    edit(model)
    return build(model)


def edit_section(payload: bytes, sid: int, change) -> bytes:
    """Replace one section's bytes with `change(bytearray)` (in place or returned) and fix its CRC."""
    def edit(model):
        for e in model["entries"]:
            if e["id"] == sid:
                data = bytearray(e["data"])
                result = change(data)
                e["data"] = bytes(data if result is None else result)
                return
        raise KeyError(sid)
    return rebuild(payload, edit)


def patch(payload: bytes, at: int, data: bytes) -> bytes:
    out = bytearray(payload)
    out[at:at + len(data)] = data
    return bytes(out)


def entry_offset(payload: bytes, sid: int) -> tuple[int, int]:
    """(payload offset, length) of a section in the file."""
    count = HEADER.unpack_from(payload)[5]
    for i in range(count):
        row = ENTRY.unpack_from(payload, HEADER.size + i * ENTRY.size)
        if row[0] == sid:
            return row[3], row[4]
    raise KeyError(sid)
