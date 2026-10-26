"""BMB-019 synthetic semantic metadata subset tests, no private fixtures."""
import copy
import hashlib
import math
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bomc.adapter.writer_v12 import (  # noqa: E402
    encode_graph, UnsupportedFeature, IDENTITY, HEADER, ENTRY, MAGIC)
from tools.bomc_fixture_harness import inspect_container  # noqa: E402


def graph():
    ident = list(IDENTITY)
    moved = list(IDENTITY)
    moved[12] = 2.5
    moved[13] = -3.0
    return {"schemaVersion": "bmb-writer-graph-v1",
            "name": "Synthetic tree",
            "nodes": [
                {"id": "child", "kind": "group", "name": "Room A",
                 "parentId": "root", "transform": moved},
                {"id": "root", "kind": "root", "name": "Synthetic tree",
                 "parentId": None, "transform": ident},
            ]}


def sections(data):
    parsed = inspect_container(data)
    result = {}
    for index, row in enumerate(parsed):
        typ, codec, flags, offset, length, raw, count, crc = ENTRY.unpack_from(
            data, HEADER.size + index * ENTRY.size)
        payload = data[offset:offset + length]
        assert codec == flags == 0 and length == raw
        assert (zlib.crc32(payload) & 0xffffffff) == crc
        result[typ] = (count, payload)
    return result


class WriterTests(unittest.TestCase):
    def test_semantic_tables_and_indices(self):
        binary = encode_graph(graph())
        self.assertEqual(binary[:8], MAGIC)
        self.assertEqual(HEADER.unpack_from(binary)[1:3], (1, 2))
        rows = sections(binary)
        self.assertEqual(tuple(sorted(rows)), (1, 2, 11, 12, 13, 17, 20))
        self.assertEqual([rows[x][0] for x in sorted(rows)],
                         [1, 2, 2, 2, 2, 1, 1])
        model = rows[1][1]
        self.assertEqual(struct.unpack_from("<9I", model, 56),
                         (0, 0, 0, 0, 2, 2, 2, 0, 0))
        self.assertEqual(model[2], 1)
        self.assertEqual(struct.unpack_from("<I", model, 4)[0], 0)
        defs = rows[11][1]
        self.assertEqual(defs[:8], b"\x01\x01\x01\x00\x02\x00\x00\x00")
        self.assertEqual(defs[10:12], b"\x01\x03")
        self.assertEqual(defs[12:14], b"\xff\xff")
        instances = rows[12][1]
        self.assertEqual(instances[14:16], b"\x01\x03")
        self.assertEqual(instances[16:18], b"\xff\x00")
        self.assertEqual(instances[18:20], b"\x00\x01")
        self.assertEqual(instances[20:22], b"\x00\x01")
        transforms = rows[13][1]
        self.assertEqual(transforms[:4], b"\x01\x01\x00\x00")
        self.assertEqual(struct.unpack_from("<I", transforms, 4)[0], 2)
        self.assertEqual(struct.unpack_from("<I", transforms, 8)[0], 192)
        child_affine = struct.unpack_from("<12d", transforms, 12 + 96)
        self.assertEqual(child_affine[9:12], (2.5, -3.0, 0.0))
        self.assertEqual(rows[17][1], b"\x00" * 24)
        self.assertEqual(len(rows[20][1]), 76)
        self.assertEqual(struct.unpack_from("<HBB", rows[20][1]), (1, 1, 0))

    def test_determinism_independent_of_input_order(self):
        a = graph()
        b = copy.deepcopy(a)
        b["nodes"] = list(reversed(b["nodes"]))
        self.assertEqual(encode_graph(a), encode_graph(b))
        self.assertEqual(hashlib.sha256(encode_graph(a)).digest(),
                         hashlib.sha256(encode_graph(b)).digest())

    def test_nested_groups_and_affine(self):
        doc = graph()
        transformed = list(IDENTITY)
        transformed[0] = -1  # mirror
        transformed[4] = 0.25  # shear
        doc["nodes"].append({"id": "nested", "kind": "group", "name": "Nested",
                             "parentId": "child", "transform": transformed})
        rows = sections(encode_graph(doc))
        self.assertEqual(rows[12][0], 3)
        # Lexicographic order: root, child, nested; nested is owned by child definition.
        self.assertEqual(rows[12][1][12 + 3 * 2:12 + 3 * 3], b"\xff\x00\x01")

    def assert_rejected(self, mutation):
        doc = graph()
        mutation(doc)
        with self.assertRaises(UnsupportedFeature):
            encode_graph(doc)

    def test_fail_closed_unsupported(self):
        self.assert_rejected(lambda d: d.update(schemaVersion="1.3"))
        self.assert_rejected(lambda d: d.update(meshes=[]))
        self.assert_rejected(lambda d: d["nodes"][0].update(materialId="wood"))
        self.assert_rejected(lambda d: d["nodes"][0].update(kind="mesh"))
        self.assert_rejected(lambda d: d["nodes"][0].update(name=""))
        self.assert_rejected(lambda d: d["nodes"][0].update(parentId="missing"))
        self.assert_rejected(lambda d: d["nodes"][0].update(parentId="child"))
        self.assert_rejected(lambda d: d["nodes"][1].update(transform=[0] * 16))
        self.assert_rejected(lambda d: d["nodes"][0]["transform"].__setitem__(12, float("nan")))
        self.assert_rejected(lambda d: d["nodes"][0]["transform"].__setitem__(12, 10 ** 500))
        self.assert_rejected(lambda d: d["nodes"][0].update(name="bad\ud800"))
        self.assert_rejected(lambda d: d["nodes"][0]["transform"].__setitem__(0, 0.0))
        self.assert_rejected(lambda d: d["nodes"][0]["transform"].__setitem__(3, 1.0))
        self.assert_rejected(lambda d: d["nodes"].append(copy.deepcopy(d["nodes"][0])))

    def test_budget_and_no_mutation(self):
        doc = graph()
        before = copy.deepcopy(doc)
        encode_graph(doc)
        self.assertEqual(doc, before)
        doc["nodes"] += [{"id": "n-" + str(i), "kind": "group",
                          "name": "Tiny", "parentId": "root",
                          "transform": list(IDENTITY)} for i in range(128)]
        with self.assertRaises(UnsupportedFeature):
            encode_graph(doc)


if __name__ == "__main__":
    unittest.main()
