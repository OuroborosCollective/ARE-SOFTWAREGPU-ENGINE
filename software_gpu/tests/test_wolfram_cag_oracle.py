"""Wolfram exact-rational fixture checked against *real* CPU raster output."""
import json
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest

import numpy as np

from software_gpu.graphics.geometry import clip_triangle, edge_function, edge_covered
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.shader import Shader, Vertex
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.postprocess import MSAAFramebuffer, MSAARasterizer
from software_gpu.research.wolfram_cag_oracle import get_fixture, rational


class OracleShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {"color": vertex.color}

    def fragment_shader(self, varyings):
        rgb = np.clip(varyings["color"] * 255, 0, 255).astype(np.uint8)
        return int(rgb[0]), int(rgb[1]), int(rgb[2]), 255


def vertex_list(matrix, colors=None):
    if colors is None:
        colors = [(1, 0, 0)] * len(matrix)
    return [Vertex(np.array([float(rational(x)) for x in point], dtype=np.float32),
                   color=np.array(color, dtype=np.float32))
            for point, color in zip(matrix, colors)]


class TestWolframCagOracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle, cls.digest = get_fixture()
        cls.shader = OracleShader()

    def test_exact_near_plane_intersections(self):
        case = self.oracle["nearClip"]
        source = [
            (np.array([float(rational(x)) for x in point], dtype=np.float64),
             {"color": np.array([1.0, 0.0, 0.0], dtype=np.float32)})
            for point in case["clipVertices"]
        ]
        triangles = clip_triangle(source)
        self.assertEqual(len(triangles), 2)
        points = [pos for tri in triangles for pos, _ in tri]
        for reference in case["nearIntersections"]:
            target = np.array([float(rational(x)) for x in reference])
            self.assertTrue(any(np.allclose(v, target, rtol=0, atol=2e-12) for v in points),
                            "Wolfram near-plane intersection missing")
        area = sum(abs(np.linalg.det(np.stack([tri[1][0][:2]-tri[0][0][:2],
                                                 tri[2][0][:2]-tri[0][0][:2]])))/2
                   for tri in triangles)
        self.assertAlmostEqual(area, float(rational(case["remainingAreaXY"])), delta=1e-11)

    def test_perspective_interpolation_in_real_renderer(self):
        case = self.oracle["perspective"]
        vertices = vertex_list(case["clipVertices"], [(0, 0, 0), (0, 0, 0), (0, 0, 1)])
        for backend in ("bands", "tiles"):
            framebuffer = Framebuffer(8, 8)
            framebuffer.clear(0, 0, 0, 255)
            engine = SoftwareRasterizer(framebuffer, backend=backend, num_threads=2, tile_size=4)
            try:
                engine.draw_mesh(vertices, [(0, 1, 2)], self.shader)
            finally:
                engine.executor.shutdown(wait=True)
            x, y = case["pixel"]
            self.assertLess(framebuffer.depth_buffer[y, x], 1.0)
            expected_blue = int(255 * float(rational(case["expectedBlue"])))
            self.assertLessEqual(abs(int(framebuffer.color_buffer[y, x, 2])-expected_blue), 1)

    def test_msaa_exact_wolfram_coverage(self):
        case = self.oracle["msaa"]
        vertices = vertex_list(case["clipVertices"])
        framebuffer = MSAAFramebuffer(8, 8, samples=4)
        framebuffer.clear(0, 0, 0, 255)
        MSAARasterizer(framebuffer).draw_mesh(vertices, [(0, 1, 2)], self.shader)
        x, y = case["pixel"]
        actual = (framebuffer.depth_samples[y, x] < 1).tolist()
        self.assertEqual(actual, case["coverage"])
        self.assertEqual(int(framebuffer.resolve().color_buffer[y, x, 0]),
                         case["resolvedRed"])

    def test_top_left_partition_matches_wolfram_counts(self):
        case = self.oracle["sharedEdge"]
        masks = []
        for tri in case["screenTriangles"]:
            a, b, c = [np.asarray(point, dtype=np.float32) for point in tri]
            mask = np.zeros((8, 8), dtype=np.bool_)
            for y in range(8):
                for x in range(8):
                    p = np.asarray([x+.5, y+.5], dtype=np.float32)
                    w0, w1, w2 = (edge_function(b, c, p),
                                  edge_function(c, a, p),
                                  edge_function(a, b, p))
                    mask[y, x] = (edge_covered(w0, b, c) and
                                  edge_covered(w1, c, a) and
                                  edge_covered(w2, a, b))
            masks.append(mask)
        self.assertEqual(int(masks[0].sum()), case["firstCount"])
        self.assertEqual(int(masks[1].sum()), case["secondCount"])
        self.assertEqual(int(np.logical_or(*masks).sum()), case["coveredCount"])
        self.assertEqual(int(np.logical_and(*masks).sum()), case["overlapCount"])

    def test_fail_closed_on_fake_or_oversized_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "evidence.json"
            case = dict(self.oracle)
            case["mutationAuthority"] = "gameplay-write"
            path.write_text(json.dumps(case), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CAG_AUTHORITY"):
                get_fixture(path)
            path.write_text("x"*16_385, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CAG_FIXTURE_SIZE"):
                get_fixture(path)
            with self.assertRaisesRegex(ValueError, "CAG_RATIONAL"):
                rational("1;Import[secret]")

if __name__ == "__main__":
    unittest.main()
