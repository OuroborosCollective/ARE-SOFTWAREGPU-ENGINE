"""Tests for the offline Visual Asset Lab using actual GLB2 BIN payloads, not mock renders."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from software_gpu.tests.test_glb_diagnostic_evidence import make_glb, QUAD
from tools.visual_asset_lab import build_visual_asset_lab


class VisualAssetLabTests(unittest.TestCase):
    def test_real_indexed_glb_produces_deterministic_wireframe_and_uv(self):
        data = make_glb(QUAD, [(0, 1, 2), (0, 2, 3)],
                        [(0, 0), (1, 0), (1, 1), (0, 1)])
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            left = build_visual_asset_lab(data, Path(one))
            right = build_visual_asset_lab(data, Path(two))
            self.assertEqual(left, right)
            self.assertEqual(left["source"]["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(left["authority"], "offline-derived")
            self.assertEqual(left["pbr_beauty"], "not_executed")
            self.assertEqual(left["images"]["wireframe"]["status"], "rendered_geometry_projection")
            self.assertEqual(left["images"]["uv"]["status"], "rendered_uv_projection")
            for key in ("wireframe", "uv"):
                entry = left["images"][key]
                svg = (Path(one) / entry["filename"]).read_bytes()
                self.assertEqual(hashlib.sha256(svg).hexdigest(), entry["sha256"])
                self.assertTrue(svg.startswith(b"<svg "))
                self.assertNotIn(b"<script", svg)
                self.assertNotIn(b"<image", svg)
                self.assertNotIn(b"javascript:", svg)
                self.assertNotIn(b"href=", svg)
            self.assertEqual(json.loads((Path(one) / "visual-asset-receipt.json").read_text()), left)

    def test_disconnected_or_degenerate_remains_diagnostic_not_bad_asset_verdict(self):
        raw = make_glb([(0, 0, 0), (1, 0, 0), (2, 0, 0)], [(0, 1, 2)])
        with tempfile.TemporaryDirectory() as d:
            evidence = build_visual_asset_lab(raw, Path(d))
            self.assertEqual(evidence["diagnostic"]["primitives"][0]["topology"]["zero_area_triangles"], 1)
            self.assertEqual(evidence["verdict"], "not_assessed")

    def test_external_texture_never_fetched_and_is_unresolved(self):
        raw = make_glb(QUAD[:3], [(0, 1, 2)], material_uri="../../private/secret.png")
        with tempfile.TemporaryDirectory() as d:
            evidence = build_visual_asset_lab(raw, Path(d))
            self.assertEqual(evidence["diagnostic"]["primitives"][0]["material"]["status"],
                             "external_unresolved")
            self.assertEqual(evidence["pbr_beauty"], "not_executed")

    def test_missing_uv_is_explicitly_not_rendered(self):
        raw = make_glb(QUAD[:3], [(0, 1, 2)])
        with tempfile.TemporaryDirectory() as d:
            result = build_visual_asset_lab(raw, Path(d))
            self.assertEqual(result["images"]["uv"]["status"], "not_executed")
            self.assertFalse((Path(d) / "uv.svg").exists())

    def test_over_budget_fails_closed_before_creating_output(self):
        raw = make_glb(QUAD, [(0, 1, 2), (0, 2, 3)])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError, "VISUAL_ASSET_TRIANGLE_BUDGET"):
                build_visual_asset_lab(raw, Path(d), max_triangles=1)
            self.assertFalse(list(Path(d).iterdir()))

    def test_invalid_index_fails_closed_before_creating_output(self):
        raw = make_glb(QUAD[:3], [(0, 1, 99)])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                build_visual_asset_lab(raw, Path(d))
            self.assertFalse(list(Path(d).iterdir()))


if __name__ == "__main__":
    unittest.main()
