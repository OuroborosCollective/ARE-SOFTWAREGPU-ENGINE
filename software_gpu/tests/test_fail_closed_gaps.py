"""Fail-closed gap-closure tests: public framebuffer export contract, geometry
and shader defensive paths, tile-backend early exits and the network admission
policy unit surface.

Every test asserts a documented contract. Three defensive lines in
geometry._prepare slow path (wv < _MIN_W break, non-finite screen break,
len(screen_v) != 3 continue) are unreachable by construction: Sutherland-
Hodgman clipping guarantees w >= _MIN_W and |ndc| <= 1 within float rounding,
so a clipped fan vertex can never fail those checks. They are intentionally
NOT covered here and documented as defensive in docs/CI_COVERAGE_GATES.md.
"""
import base64
import math
import os
import secrets
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics import geometry
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import Matrix4, Shader, Vertex
from software_gpu.network.security import (
    RequestRejected,
    SecurityLimits,
    authorized,
    bounded_json,
    ensure_loopback,
    get_token,
    tensor_shape,
    validate_request,
)


class FlatShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {"color": np.asarray(vertex.color, dtype=np.float32)}

    def fragment_shader(self, varyings):
        c = varyings["color"]
        return (int(c[0] * 255), int(c[1] * 255), int(c[2] * 255), 255)


def V(x, y, z, w=1.0):
    return Vertex(np.array([x, y, z, w], dtype=np.float32))


class TestFramebufferContract(unittest.TestCase):
    def test_set_pixel_depth_test_tie_break_and_bounds(self):
        fb = Framebuffer(4, 4)
        self.assertTrue(fb.set_pixel(1, 1, 10, 20, 30, 40, z=0.5))
        # Farther fragment rejected, state unchanged.
        self.assertFalse(fb.set_pixel(1, 1, 1, 2, 3, 4, z=0.9))
        self.assertEqual(list(fb.color_buffer[1, 1]), [10, 20, 30, 40])
        self.assertAlmostEqual(float(fb.depth_buffer[1, 1]), 0.5)
        # Nearer fragment replaces.
        self.assertTrue(fb.set_pixel(1, 1, 5, 6, 7, 8, z=0.25))
        self.assertEqual(list(fb.color_buffer[1, 1]), [5, 6, 7, 8])
        # Depth tie rejected (strict <, same contract as the rasterizer).
        self.assertFalse(fb.set_pixel(1, 1, 9, 9, 9, 9, z=0.25))
        self.assertEqual(list(fb.color_buffer[1, 1]), [5, 6, 7, 8])
        # Out-of-bounds writes are rejected without raising.
        for x, y in ((-1, 0), (4, 0), (0, -1), (0, 4), (-5, -5), (10**9, 10**9)):
            self.assertFalse(fb.set_pixel(x, y, 1, 2, 3, z=0.1))
        self.assertTrue((fb.depth_buffer[0, :] == 1.0).all())

    def test_clear_sets_every_channel_and_depth(self):
        fb = Framebuffer(2, 3)
        fb.clear(1, 2, 3, 4, depth=0.75)
        self.assertTrue((fb.color_buffer == np.array([1, 2, 3, 4], dtype=np.uint8)).all())
        self.assertTrue((fb.depth_buffer == np.float32(0.75)).all())

    def test_save_ppm_binary_layout_and_alpha_dropped(self):
        fb = Framebuffer(3, 2)
        fb.set_pixel(0, 0, 255, 0, 0, 7, z=0.0)
        fb.set_pixel(2, 1, 0, 255, 0, 9, z=0.0)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.ppm"
            fb.save_ppm(str(path))
            raw = path.read_bytes()
        header = b"P6\n3 2\n255\n"
        self.assertTrue(raw.startswith(header))
        payload = raw[len(header):]
        self.assertEqual(len(payload), 3 * 2 * 3)
        self.assertEqual(payload[0:3], bytes([255, 0, 0]))   # pixel (0, 0), alpha dropped
        self.assertEqual(payload[-3:], bytes([0, 255, 0]))   # pixel (2, 1)

    def test_save_bmp_layout_padding_and_bottom_up_bgr(self):
        for width in (3, 4):  # width 3 forces row padding, width 4 does not
            fb = Framebuffer(width, 2)
            fb.set_pixel(0, 1, 1, 2, 3, z=0.0)          # buffer row 1 = stored first
            fb.set_pixel(width - 1, 0, 4, 5, 6, z=0.0)  # buffer row 0 = stored last
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "x.bmp"
                fb.save_bmp(str(path))
                raw = path.read_bytes()
            self.assertEqual(raw[0:2], b"BM")
            self.assertEqual(struct.unpack_from("<I", raw, 2)[0], len(raw))
            self.assertEqual(struct.unpack_from("<I", raw, 10)[0], 54)
            self.assertEqual(struct.unpack_from("<II", raw, 18), (width, 2))
            self.assertEqual(struct.unpack_from("<H", raw, 28)[0], 24)
            stride = (width * 3 + 3) & ~3
            self.assertEqual(len(raw) - 54, stride * 2)
            # First stored row is buffer row 1 (bottom-up), BGR order.
            self.assertEqual(raw[54:57], bytes([3, 2, 1]))
            last = 54 + stride + (width - 1) * 3
            self.assertEqual(raw[last:last + 3], bytes([6, 5, 4]))

    def test_save_bmp_deterministic_bytes(self):
        import hashlib
        fb = Framebuffer(5, 3)
        fb.set_pixel(2, 1, 9, 8, 7, z=0.0)
        digests = set()
        for _ in range(2):
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / "x.bmp"
                fb.save_bmp(str(path))
                digests.add(hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(len(digests), 1)


class TestGeometryDefensivePaths(unittest.TestCase):
    def test_non_dict_varyings_raise_type_error(self):
        class BadShader(Shader):
            def vertex_shader(self, vertex):
                return vertex.position, ["not-a-dict"]

            def fragment_shader(self, varyings):
                return (0, 0, 0, 255)

        verts = [V(0, 0, 0.5), V(0.5, 0, 0.5), V(0, 0.5, 0.5)]
        with self.assertRaises(TypeError) as cm:
            geometry.prepare_triangles(verts, [(0, 1, 2)], BadShader(), 64, 64)
        self.assertIn("varyings must be a dict", str(cm.exception))

    def test_ragged_face_records_fail_fast_with_index_error(self):
        verts = [V(0, 0, 0.5), V(0.5, 0, 0.5), V(0, 0.5, 0.5)]
        with self.assertRaises(IndexError) as cm:
            geometry.prepare_triangles(verts, [(0, 1, 2), (0, 1)], FlatShader(), 64, 64)
        self.assertIn("triangle index outside vertex array", str(cm.exception))

    def test_non_integer_face_records_fail_fast_with_index_error(self):
        verts = [V(0, 0, 0.5), V(0.5, 0, 0.5), V(0, 0.5, 0.5)]
        with self.assertRaises(IndexError):
            geometry.prepare_triangles(verts, [(0, 1, 2.5)], FlatShader(), 64, 64)

    def test_sliver_crossing_near_plane_discarded_deterministically(self):
        # Degenerate-after-clip sliver must be discarded via the slow path
        # (area <= 1e-9 continue), identically on repeated calls.
        verts = [V(-1e-12, 0, 0), V(1e-12, 0, 0), V(0.0, 1e-12, 2.0)]
        first = geometry.prepare_triangles(verts, [(0, 1, 2)], FlatShader(), 128, 128)
        second = geometry.prepare_triangles(verts, [(0, 1, 2)], FlatShader(), 128, 128)
        self.assertEqual(first, [])
        self.assertEqual(second, [])


class TestTileBackendEarlyExits(unittest.TestCase):
    def test_empty_index_list_returns_without_touching_framebuffer(self):
        fb = Framebuffer(32, 32)
        render = SoftwareRasterizer(fb, backend="tiles", num_threads=1, tile_size=16)
        render.draw_mesh([V(0, 0, 0.5), V(0.5, 0, 0.5), V(0, 0.5, 0.5)], [], FlatShader())
        self.assertTrue((fb.color_buffer == 0).all())
        self.assertTrue((fb.depth_buffer == 1.0).all())

    def test_fully_outside_frustum_hits_empty_bins_early_return(self):
        fb = Framebuffer(32, 32)
        render = SoftwareRasterizer(fb, backend="tiles", num_threads=1, tile_size=16)
        # All three vertices violate the same clip plane (w - x < 0):
        # discarded in prepare_triangles, so the tile pass sees zero bins.
        verts = [V(10, 0, 0.5), V(11, 0, 0.5), V(10, 1, 0.5)]
        render.draw_mesh(verts, [(0, 1, 2)], FlatShader())
        self.assertTrue((fb.color_buffer == 0).all())
        self.assertTrue((fb.depth_buffer == 1.0).all())
        # Bands backend agrees (same contract, different code path).
        fb2 = Framebuffer(32, 32)
        SoftwareRasterizer(fb2, backend="bands", num_threads=1).draw_mesh(
            verts, [(0, 1, 2)], FlatShader())
        self.assertTrue((fb2.color_buffer == 0).all())
        self.assertTrue((fb2.depth_buffer == 1.0).all())


class TestShaderMathContract(unittest.TestCase):
    def test_vertex_defaults_are_float32_and_filled(self):
        v = Vertex([1, 2, 3])
        self.assertEqual(v.position.dtype, np.float32)
        self.assertEqual(list(v.position), [1.0, 2.0, 3.0, 1.0])
        self.assertEqual(list(v.uv), [0.0, 0.0])
        self.assertEqual(list(v.color), [1.0, 1.0, 1.0])
        v2 = Vertex([0, 0, 0, 1], uv=[0.25, 0.75], color=[0.5, 0.25, 0.125])
        self.assertEqual(list(v2.uv), [0.25, 0.75])
        self.assertEqual(v2.color.dtype, np.float32)
        self.assertAlmostEqual(float(v2.color[2]), 0.125, places=6)

    def test_base_shader_stages_raise_not_implemented(self):
        shader = Shader()
        with self.assertRaises(NotImplementedError):
            shader.vertex_shader(Vertex([0, 0, 0]))
        with self.assertRaises(NotImplementedError):
            shader.fragment_shader({})

    def test_matrix_transforms_act_on_points(self):
        p = np.array([1, 2, 3, 1], dtype=np.float32)
        moved = Matrix4.translation(10, 20, 30) @ p
        np.testing.assert_allclose(moved, [11, 22, 33, 1], atol=1e-6)
        scaled = Matrix4.scale(2, 3, 4) @ p
        np.testing.assert_allclose(scaled, [2, 6, 12, 1], atol=1e-6)
        rotated = Matrix4.rotation_z(math.pi / 2) @ np.array([1, 0, 0, 1], dtype=np.float32)
        np.testing.assert_allclose(rotated[:2], [0, 1], atol=1e-6)
        np.testing.assert_array_equal(Matrix4.identity(), np.eye(4, dtype=np.float32))

    def test_perspective_maps_near_to_minus_one_and_far_to_plus_one(self):
        near, far = 0.5, 100.0
        m = Matrix4.perspective(math.radians(60), 1.0, near, far)
        for z, expected_ndc in ((-near, -1.0), (-far, 1.0)):
            clip = m @ np.array([0, 0, z, 1], dtype=np.float32)
            self.assertAlmostEqual(float(clip[2] / clip[3]), expected_ndc, places=5)

    def test_look_at_identity_for_canonical_camera(self):
        m = Matrix4.look_at(np.array([0, 0, 0]), np.array([0, 0, -1]), np.array([0, 1, 0]))
        np.testing.assert_allclose(m, np.eye(4, dtype=np.float32), atol=1e-6)


class TestNetworkAdmissionUnitGaps(unittest.TestCase):
    """Direct unit coverage of the fail-closed admission policy branches that
    the socket-level integration tests do not reach."""

    def test_security_limits_reject_out_of_cap_values(self):
        with self.assertRaises(ValueError) as cm:
            SecurityLimits(max_elements=0)
        self.assertIn("INVALID_SECURITY_LIMIT_MAX_ELEMENTS", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            SecurityLimits(max_clients=17)
        self.assertIn("INVALID_SECURITY_LIMIT_MAX_CLIENTS", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            SecurityLimits(io_timeout_seconds=0.01)
        self.assertIn("INVALID_SECURITY_LIMIT_IO_TIMEOUT_SECONDS", str(cm.exception))
        with self.assertRaises(ValueError):
            SecurityLimits(max_elements="100")

    def test_ensure_loopback_rejects_everything_but_ipv4_loopback(self):
        ensure_loopback("127.0.0.1")  # must not raise
        for host in ("0.0.0.0", "::1", "localhost", "127.0.0.2", ""):
            with self.assertRaises(ValueError) as cm:
                ensure_loopback(host)
            self.assertIn("REMOTE_BIND_FORBIDDEN", str(cm.exception))

    def test_get_token_entropy_and_charset_policy(self):
        saved = os.environ.pop("SOFTWAREGPU_AUTH_TOKEN", None)
        try:
            with self.assertRaises(ValueError) as cm:
                get_token(None)
            self.assertIn("AUTH_TOKEN_REQUIRED", str(cm.exception))
            for bad in ("short", "a" * 40, "token with space " + "x" * 30,
                        "ä" * 40, 12345):
                with self.assertRaises(ValueError):
                    get_token(bad)
            good = secrets.token_urlsafe(40)
            self.assertEqual(get_token(good), good)
            os.environ["SOFTWAREGPU_AUTH_TOKEN"] = good
            self.assertEqual(get_token(None), good)
        finally:
            if saved is None:
                os.environ.pop("SOFTWAREGPU_AUTH_TOKEN", None)
            else:
                os.environ["SOFTWAREGPU_AUTH_TOKEN"] = saved

    def test_authorized_constant_time_comparison_contract(self):
        secret = secrets.token_urlsafe(40)
        self.assertTrue(authorized(secret, secret))
        self.assertFalse(authorized(secret, secret + "x"))
        self.assertFalse(authorized(secret, ""))
        self.assertFalse(authorized(secret, None))

    def test_bounded_json_rejects_hostile_structures(self):
        nested = current = []
        for _ in range(16):
            nxt = []
            current.append(nxt)
            current = nxt
        with self.assertRaises(RequestRejected) as cm:
            bounded_json(nested)
        self.assertEqual(cm.exception.code, "JSON_STRUCTURE_LIMIT")
        with self.assertRaises(RequestRejected) as cm:
            bounded_json({"x": 1 << 100})
        self.assertEqual(cm.exception.code, "INTEGER_LIMIT")
        with self.assertRaises(RequestRejected) as cm:
            bounded_json({"x": float("nan")})
        self.assertEqual(cm.exception.code, "NONFINITE_NUMBER")
        with self.assertRaises(RequestRejected) as cm:
            bounded_json({1: "x"})
        self.assertEqual(cm.exception.code, "JSON_KEY_LIMIT")
        with self.assertRaises(RequestRejected) as cm:
            bounded_json({"k" * 129: 1})
        self.assertEqual(cm.exception.code, "JSON_KEY_LIMIT")
        with self.assertRaises(RequestRejected) as cm:
            bounded_json({"x": b"bytes"})
        self.assertEqual(cm.exception.code, "JSON_TYPE_INVALID")
        bounded_json({"ok": [1, 2.5, "s", True, None, {"n": []}]})  # must not raise

    def test_tensor_shape_dict_encoding_validation(self):
        limits = SecurityLimits()
        raw = np.zeros((2, 3), dtype=np.float32).tobytes()
        payload = base64.b64encode(raw).decode("ascii")
        shape = tensor_shape({"__tensor__": True, "shape": [2, 3],
                              "dtype": "float32", "data_b64": payload}, limits)
        self.assertEqual(shape, (2, 3))
        cases = [
            ({"shape": [2, 3], "dtype": "float32", "data_b64": payload}, "TENSOR_ENCODING_INVALID"),
            ({"__tensor__": True, "shape": [2, 3, 1, 1], "dtype": "float32",
              "data_b64": payload}, "TENSOR_RANK_INVALID"),
            ({"__tensor__": True, "shape": [0, 3], "dtype": "float32",
              "data_b64": payload}, "DIMENSION_LIMIT"),
            ({"__tensor__": True, "shape": [129, 128], "dtype": "float32",
              "data_b64": payload}, "TENSOR_ELEMENTS_LIMIT"),
            ({"__tensor__": True, "shape": [2, 3], "dtype": "int32",
              "data_b64": payload}, "TENSOR_DTYPE_UNSUPPORTED"),
            ({"__tensor__": True, "shape": [2, 3], "dtype": "float32",
              "data_b64": payload[:-1]}, "TENSOR_LENGTH_MISMATCH"),
            ({"__tensor__": True, "shape": [2, 3], "dtype": "float32",
              "data_b64": "!" * len(payload)}, "TENSOR_BASE64_INVALID"),
            ({"__tensor__": True, "shape": [2, 3], "dtype": "float32",
              "data_b64": 12345}, "TENSOR_PAYLOAD_LIMIT"),
        ]
        for doc, code in cases:
            with self.assertRaises(RequestRejected) as cm:
                tensor_shape(doc, limits)
            self.assertEqual(cm.exception.code, code, doc)
        self.assertEqual(cases[3][1], "TENSOR_ELEMENTS_LIMIT")

    def test_tensor_shape_list_encoding_validation(self):
        limits = SecurityLimits()
        self.assertEqual(tensor_shape([[1.0, 2.0], [3.0, 4.0]], limits), (2, 2))
        cases = [
            (5, "TENSOR_RANK_INVALID"),
            ([], "TENSOR_RANK_INVALID"),
            ([[]], "EMPTY_TENSOR"),
            ([[1.0, 2.0], [3.0]], "TENSOR_RAGGED"),
            ([[[[1.0]]]], "TENSOR_RANK_INVALID"),
            ([1.0, float("inf")], "NUMERIC_PARAMETER_OUT_OF_RANGE"),
            (["text"], "NUMERIC_PARAMETER_INVALID"),
        ]
        for doc, code in cases:
            with self.assertRaises(RequestRejected) as cm:
                tensor_shape(doc, limits)
            self.assertEqual(cm.exception.code, code, doc)

    def test_validate_request_method_and_shape_contracts(self):
        limits = SecurityLimits()
        validate_request("device_info", {}, limits)  # must not raise
        with self.assertRaises(RequestRejected) as cm:
            validate_request("definitely_not_a_method", {}, limits)
        self.assertEqual(cm.exception.code, "METHOD_NOT_ALLOWED")
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaises(RequestRejected) as cm:
            validate_request("gemm", [1, 2], limits)
        self.assertEqual(cm.exception.code, "PARAMETERS_MUST_BE_OBJECT")
        with self.assertRaises(RequestRejected) as cm:
            validate_request("device_info", {"x": 1}, limits)
        self.assertEqual(cm.exception.code, "UNEXPECTED_PARAMETERS")
        with self.assertRaises(RequestRejected) as cm:
            validate_request("vector_add", {"a": [1.0, 2.0], "b": [1.0]}, limits)
        self.assertEqual(cm.exception.code, "TENSOR_SHAPE_MISMATCH")
        with self.assertRaises(RequestRejected) as cm:
            validate_request("gemm", {"a": [[1.0, 2.0]], "b": [[1.0, 2.0]]}, limits)
        self.assertEqual(cm.exception.code, "MATRIX_SHAPE_MISMATCH")
        with self.assertRaises(RequestRejected) as cm:
            validate_request("gemm",
                             {"a": [[1.0]] * 130, "b": [[1.0] * 128]},
                             limits)
        # 130x1 @ 1x128: result 16640 > 16384 elements
        self.assertEqual(cm.exception.code, "RESULT_ELEMENTS_LIMIT")
        self.assertEqual(cm.exception.status, 413)

    def test_validate_request_compute_ops_limit_with_tight_limits(self):
        tight = SecurityLimits(max_compute_ops=10)
        # 2x3 @ 3x2: result 4 elements ok, but 2*2*2*3 = 24 ops > 10.
        with self.assertRaises(RequestRejected) as cm:
            validate_request("gemm", {"a": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
                                      "b": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]}, tight)
        self.assertEqual(cm.exception.code, "COMPUTE_OPERATIONS_LIMIT")

    def test_validate_request_activation_type_whitelist(self):
        limits = SecurityLimits()
        validate_request("activation", {"x": [1.0], "type": "relu"}, limits)
        validate_request("activation", {"x": [1.0], "type": "gelu"}, limits)
        with self.assertRaises(RequestRejected) as cm:
            validate_request("activation", {"x": [1.0], "type": "sigmoid"}, limits)
        self.assertEqual(cm.exception.code, "ACTIVATION_UNSUPPORTED")


class TestRenderAndPhysicsAdmissionGaps(unittest.TestCase):
    def test_physics_step_entity_shapes_and_dt(self):
        limits = SecurityLimits()
        validate_request("physics_step",
                         {"positions": [[0.0, 0.0, 0.0]], "velocities": [[1.0, 1.0, 1.0]],
                          "dt": 0.016, "world_bounds": [-1, 1, -1, 1, -1, 1]}, limits)
        with self.assertRaises(RequestRejected) as cm:
            validate_request("physics_step",
                             {"positions": [[0.0, 0.0, 0.0]], "velocities": [[1.0, 1.0]]},
                             limits)
        self.assertEqual(cm.exception.code, "ENTITY_SHAPE_MISMATCH")
        with self.assertRaises(RequestRejected) as cm:
            validate_request("physics_step",
                             {"positions": [[0.0, 0.0, 0.0]],
                              "velocities": [[1.0, 1.0, 1.0]], "dt": 5.0}, limits)
        self.assertEqual(cm.exception.code, "NUMERIC_PARAMETER_OUT_OF_RANGE")
        with self.assertRaises(RequestRejected) as cm:
            validate_request("physics_step",
                             {"positions": [[0.0, 0.0, 0.0]],
                              "velocities": [[1.0, 1.0, 1.0]], "dt": "fast"}, limits)
        self.assertEqual(cm.exception.code, "NUMERIC_PARAMETER_INVALID")
        with self.assertRaises(RequestRejected) as cm:
            validate_request("physics_step",
                             {"positions": [[0.0, 0.0, 0.0]],
                              "velocities": [[1.0, 1.0, 1.0]],
                              "world_bounds": [0, 1, 0, 1]}, limits)
        self.assertEqual(cm.exception.code, "WORLD_BOUNDS_INVALID")
        with self.assertRaises(RequestRejected) as cm:
            validate_request("physics_step",
                             {"positions": [[0.0, 0.0, 0.0]],
                              "velocities": [[1.0, 1.0, 1.0]],
                              "world_bounds": [10, -10, -1, 1, -1, 1]}, limits)
        self.assertEqual(cm.exception.code, "WORLD_BOUNDS_INVALID")

    def test_boids_swarm_max_speed_and_no_world_bounds_requirement(self):
        limits = SecurityLimits()
        # boids_swarm deliberately does not require world_bounds.
        validate_request("boids_swarm",
                         {"positions": [[0.0, 0.0, 0.0]], "velocities": [[1.0, 0.0, 0.0]],
                          "max_speed": 50.0}, limits)
        with self.assertRaises(RequestRejected) as cm:
            validate_request("boids_swarm",
                             {"positions": [[0.0, 0.0, 0.0]],
                              "velocities": [[1.0, 0.0, 0.0]], "max_speed": 0.0}, limits)
        self.assertEqual(cm.exception.code, "NUMERIC_PARAMETER_OUT_OF_RANGE")

    def test_render_mesh_happy_path_and_dimension_limits(self):
        limits = SecurityLimits()
        validate_request("render_mesh", {
            "width": 64, "height": 64,
            "vertices": [{"pos": [0, 0, 0.5, 1]}, {"pos": [1, 0, 0.5, 1]},
                         {"pos": [0, 1, 0.5, 1]}],
            "indices": [[0, 1, 2]]}, limits)
        with self.assertRaises(RequestRejected) as cm:
            validate_request("render_mesh", {"width": 0, "height": 64,
                                             "vertices": [], "indices": []}, limits)
        self.assertEqual(cm.exception.code, "DIMENSION_LIMIT")
        tiny_pixels = SecurityLimits(max_render_pixels=100)
        with self.assertRaises(RequestRejected) as cm:
            validate_request("render_mesh", {"width": 64, "height": 64,
                                             "vertices": [], "indices": []}, tiny_pixels)
        self.assertEqual(cm.exception.code, "RENDER_PIXELS_LIMIT")
        self.assertEqual(cm.exception.status, 413)

    def test_render_mesh_vertex_and_triangle_caps(self):
        limits = SecurityLimits()
        with self.assertRaises(RequestRejected) as cm:
            validate_request("render_mesh", {"vertices": "not-a-list", "indices": []}, limits)
        self.assertEqual(cm.exception.code, "VERTICES_LIMIT")
        tiny_verts = SecurityLimits(max_vertices=2)
        with self.assertRaises(RequestRejected) as cm:
            validate_request("render_mesh",
                             {"vertices": [{"pos": [0, 0, 1]}] * 3, "indices": []},
                             tiny_verts)
        self.assertEqual(cm.exception.code, "VERTICES_LIMIT")
        with self.assertRaises(RequestRejected) as cm:
            validate_request("render_mesh", {"vertices": [], "indices": "x"}, limits)
        self.assertEqual(cm.exception.code, "TRIANGLES_LIMIT")

    def test_render_mesh_cost_limit_with_tight_limits(self):
        tight = SecurityLimits(max_compute_ops=10)
        with self.assertRaises(RequestRejected) as cm:
            validate_request("render_mesh",
                             {"width": 8, "height": 8,
                              "vertices": [{"pos": [0, 0, 1]}] * 3,
                              "indices": [[0, 1, 2]]}, tight)
        self.assertEqual(cm.exception.code, "RENDER_COST_LIMIT")
        self.assertEqual(cm.exception.status, 413)

    def test_render_mesh_vertex_attribute_validation(self):
        limits = SecurityLimits()
        bad_vertices = [
            (["not-a-dict"], "VERTEX_INVALID"),
            ([{"no_pos": [0, 0, 1]}], "VERTEX_INVALID"),
            ([{"pos": [0, 1]}], "VERTEX_INVALID"),
            ([{"pos": [0, 0, 1], "norm": [1, 1]}], "VERTEX_ATTRIBUTE_INVALID"),
            ([{"pos": [0, 0, 1], "uv": [0.5, "x"]}], "NUMERIC_PARAMETER_INVALID"),
            ([{"pos": [0, 0, 1], "color": [1e9, 0, 0]}], "NUMERIC_PARAMETER_OUT_OF_RANGE"),
        ]
        for vertices, code in bad_vertices:
            with self.assertRaises(RequestRejected) as cm:
                validate_request("render_mesh",
                                 {"vertices": vertices, "indices": []}, limits)
            self.assertEqual(cm.exception.code, code, vertices)

    def test_render_mesh_triangle_index_validation(self):
        limits = SecurityLimits()
        vertices = [{"pos": [0, 0, 1]}, {"pos": [1, 0, 1]}, {"pos": [0, 1, 1]}]
        bad_faces = [
            ([[0, 1]], "TRIANGLE_INDEX_INVALID"),
            ([[0, 1, 99]], "TRIANGLE_INDEX_INVALID"),
            ([[0, 1, -1]], "TRIANGLE_INDEX_INVALID"),
            ([["0", 1, 2]], "TRIANGLE_INDEX_INVALID"),
        ]
        for faces, code in bad_faces:
            with self.assertRaises(RequestRejected) as cm:
                validate_request("render_mesh",
                                 {"vertices": vertices, "indices": faces}, limits)
            self.assertEqual(cm.exception.code, code, faces)


if __name__ == "__main__":
    unittest.main()
