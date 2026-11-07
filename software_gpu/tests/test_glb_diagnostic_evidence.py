"""Real in-memory GLB binary regression tests; synthetic fixtures are NOT production assets."""
from __future__ import annotations

import hashlib
import json
import struct
import unittest

from tools.glb_diagnostic_evidence import inspect_diagnostic_glb


def make_glb(vertices, faces, uv=None, *, material_uri=None, invalid_material=False):
    """Produce a genuine glTF 2.0 GLB with POSITION/indices/TEXCOORD buffers."""
    blob = bytearray()
    views = []
    accessors = []

    def add_view(data):
        while len(blob) % 4:
            blob.append(0)
        offset = len(blob)
        blob.extend(data)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data)})
        return len(views) - 1

    pos = b"".join(struct.pack("<3f", *vertex) for vertex in vertices)
    pos_view = add_view(pos)
    accessors.append({"bufferView": pos_view, "componentType": 5126,
                      "count": len(vertices), "type": "VEC3"})
    indices = [part for face in faces for part in face]
    index_view = add_view(b"".join(struct.pack("<H", index) for index in indices))
    accessors.append({"bufferView": index_view, "componentType": 5123,
                      "count": len(indices), "type": "SCALAR"})
    attributes = {"POSITION": 0}
    if uv is not None:
        tex_view = add_view(b"".join(struct.pack("<2f", *xy) for xy in uv))
        attributes["TEXCOORD_0"] = len(accessors)
        accessors.append({"bufferView": tex_view, "componentType": 5126,
                          "count": len(uv), "type": "VEC2"})
    primitive = {"attributes": attributes, "indices": 1, "mode": 4}
    doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(blob)}],
           "bufferViews": views, "accessors": accessors,
           "meshes": [{"primitives": [primitive]}]}
    if invalid_material:
        primitive["material"] = 99
    if material_uri is not None:
        primitive["material"] = 0
        doc["materials"] = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]
        doc["textures"] = [{"source": 0}]
        doc["images"] = [{"uri": material_uri}]
    document = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    document += b" " * (-len(document) % 4)
    blob.extend(b"\0" * (-len(blob) % 4))
    chunks = (struct.pack("<II", len(document), 0x4E4F534A) + document +
              struct.pack("<II", len(blob), 0x004E4942) + blob)
    return b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks


QUAD = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]


class DiagnosticGLBEvidenceTests(unittest.TestCase):
    def test_indexed_quad_matches_independent_wolfram_topology_oracle(self):
        raw = make_glb(QUAD, [(0, 1, 2), (0, 2, 3)],
                       [(0, 0), (1, 0), (1, 1), (0, 1)])
        original = bytes(raw)
        found = inspect_diagnostic_glb(raw)
        self.assertEqual(found["protocol"], "are.glb-diagnostic-evidence.v1")
        self.assertEqual(found["authority"], "offline-derived")
        self.assertEqual(found["source"]["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(found["verdict"], "not_assessed")
        self.assertEqual(found["rendered_passes"]["beauty"], "not_executed")
        self.assertEqual(found["rendered_passes"]["wireframe"], "not_executed")
        topology = found["primitives"][0]["topology"]
        self.assertEqual(topology, {"status": "analyzed", "triangles": 2,
                                    "used_vertices": 4, "unique_edges": 5,
                                    "boundary_edges": 4, "nonmanifold_edges": 0,
                                    "connected_components": 1,
                                    "zero_area_triangles": 0,
                                    "euler_characteristic": 1})
        self.assertEqual(found["primitives"][0]["uv"]["candidate_seam_positions"], 0)
        self.assertEqual(raw, original)
        self.assertEqual(found, inspect_diagnostic_glb(raw))

    def test_disconnected_mesh_is_reported_not_auto_rejected(self):
        vertices = QUAD[:3] + [(5, 0, 0), (6, 0, 0), (5, 1, 0)]
        found = inspect_diagnostic_glb(make_glb(vertices, [(0, 1, 2), (3, 4, 5)]))
        t = found["primitives"][0]["topology"]
        self.assertEqual((t["connected_components"], t["euler_characteristic"],
                          t["boundary_edges"]), (2, 2, 6))
        self.assertEqual(found["verdict"], "not_assessed")

    def test_zero_area_triangle_is_evidence_not_a_quality_label(self):
        raw = make_glb([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 2)])
        found = inspect_diagnostic_glb(raw)
        self.assertEqual(found["primitives"][0]["topology"]["zero_area_triangles"], 1)
        self.assertEqual(found["verdict"], "not_assessed")

    def test_same_position_with_different_uv_is_only_a_candidate(self):
        vertices = QUAD[:3] + [(0, 0, 0), (0, -1, 0), (1, -1, 0)]
        uv = [(0, 0), (1, 0), (1, 1), (.7, 0), (0, 1), (1, 1)]
        found = inspect_diagnostic_glb(make_glb(vertices, [(0, 1, 2), (3, 4, 5)], uv))
        self.assertEqual(found["primitives"][0]["uv"]["candidate_seam_positions"], 1)

    def test_external_texture_is_unresolved_and_never_loaded(self):
        raw = make_glb(QUAD[:3], [(0, 1, 2)], material_uri="../../private/secret.png")
        found = inspect_diagnostic_glb(raw)
        self.assertEqual(found["primitives"][0]["material"]["status"], "external_unresolved")
        self.assertEqual(found["rendered_passes"]["uv_seam_wireframe"], "not_executed")

    def test_missing_material_reference_fails_closed(self):
        raw = make_glb(QUAD[:3], [(0, 1, 2)], invalid_material=True)
        with self.assertRaisesRegex(ValueError, "GLB_DIAGNOSTIC_MATERIAL_REF_INVALID"):
            inspect_diagnostic_glb(raw)

    def test_out_of_bounds_index_fails_closed(self):
        raw = make_glb(QUAD[:3], [(0, 1, 7)])
        with self.assertRaisesRegex(ValueError, "GLB_DIAGNOSTIC_INDEX_INVALID"):
            inspect_diagnostic_glb(raw)

    def test_bound_prevents_unbounded_topology_allocation(self):
        raw = make_glb(QUAD, [(0, 1, 2), (0, 2, 3)])
        evidence = inspect_diagnostic_glb(raw, max_triangles=1)["primitives"][0]["topology"]
        self.assertEqual(evidence["status"], "not_analyzed")
        self.assertEqual(evidence["reason"], "analysis_budget")

    def test_unindexed_unsupported_does_not_claim_geometry_proof(self):
        raw = bytearray(make_glb(QUAD[:3], [(0, 1, 2)]))
        length = struct.unpack_from("<I", raw, 12)[0]
        doc = json.loads(raw[20:20+length])
        del doc["meshes"][0]["primitives"][0]["indices"]
        payload = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
        payload += b" " * (-len(payload) % 4)
        old_bin_offset = 20 + length
        bin_part = bytes(raw[old_bin_offset:])
        chunks = struct.pack("<II", len(payload), 0x4E4F534A) + payload + bin_part
        result = inspect_diagnostic_glb(b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks)
        self.assertEqual(result["primitives"][0]["topology"]["status"], "not_analyzed")

    def test_source_empty_container_stays_valid_but_no_render_evidence(self):
        doc = b'{"asset":{"version":"2.0"}}'
        doc += b" " * (-len(doc) % 4)
        raw = b"glTF" + struct.pack("<II", 2, 20 + len(doc)) + struct.pack("<II", len(doc), 0x4E4F534A) + doc
        result = inspect_diagnostic_glb(raw)
        self.assertEqual(result["primitives"], [])
        self.assertEqual(result["verdict"], "not_assessed")


if __name__ == "__main__":
    unittest.main()
