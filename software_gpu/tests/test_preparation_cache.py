"""Real framebuffer/depth regression for content-keyed preparation reuse."""
import unittest
from dataclasses import replace

import numpy as np

from software_gpu.benchmarks.compare_surface_plans import build_scene, SCENES
from software_gpu.benchmarks.compare_tile_backends import make_fixture
from software_gpu.graphics.batch_shader import VertexColorShader
from software_gpu.graphics.framebuffer import Framebuffer
from software_gpu.graphics.preparation_cache import PreparationCache, input_key, retained_bytes
from software_gpu.graphics.rasterizer import SoftwareRasterizer
from software_gpu.graphics.shader import BlinnPhongShader, Matrix4, Vertex
from software_gpu.graphics.surface_plan import BATCH_FIRST_POLICY, SurfacePlanPolicy
from software_gpu.graphics.tile_backend import bin_triangles, rasterize_tiles
from software_gpu.tests.test_prepare_triangles_setup import tri_lists_equal
from software_gpu.graphics.geometry import prepare_triangles


class FragmentCounter(VertexColorShader):
    def __init__(self):
        self.calls = 0

    def fragment_shader(self, varyings):
        self.calls += 1
        return super().fragment_shader(varyings)


class StatefulVertex(FragmentCounter):
    def __init__(self):
        super().__init__()
        self.vertices_seen = 0

    def vertex_shader(self, vertex):
        self.vertices_seen += 1
        return super().vertex_shader(vertex)


def buffers(fb):
    return fb.color_buffer.tobytes(), fb.depth_buffer.tobytes()


class TestPreparationCache(unittest.TestCase):
    def make_engine(self, pixels=32, workers=1, backend="tiles-plan", budget=8 << 20, entries=8):
        fb = Framebuffer(pixels, pixels)
        engine = SoftwareRasterizer(fb, backend=backend, num_threads=workers,
                                    plan_policy=BATCH_FIRST_POLICY if backend == "tiles-plan" else None,
                                    preparation_cache_bytes=budget, preparation_cache_entries=entries)
        self.addCleanup(engine.executor.shutdown, wait=True)
        return fb, engine

    def assert_draw(self, engine, mesh, faces, shader, status=None):
        reference = SoftwareRasterizer(Framebuffer(engine.fb.width, engine.fb.height),
                                       tile_size=engine.tile_size, num_threads=engine.num_threads,
                                       backend=engine.backend, plan_policy=engine.plan_policy)
        try:
            for fb in (engine.fb, reference.fb):
                fb.clear(16, 25, 38, 255, depth=1.0)
            reference.draw_mesh(mesh, faces, shader)
            engine.draw_mesh(mesh, faces, shader)
            self.assertEqual(buffers(engine.fb), buffers(reference.fb))
            self.assertEqual(engine.last_plan_receipt, reference.last_plan_receipt)
            if status:
                self.assertEqual(engine.last_preparation_receipt["status"], status)
        finally:
            reference.executor.shutdown(wait=True)

    def test_warm_hits_are_real_byte_identical_draws_all_scenes(self):
        for workers in (1, 2):
            _, engine = self.make_engine(pixels=32, workers=workers)
            for name, spec in SCENES:
                with self.subTest(workers=workers, scene=name):
                    mesh, faces = build_scene(spec)
                    self.assert_draw(engine, mesh, faces, VertexColorShader(), "miss")
                    self.assert_draw(engine, mesh, faces, VertexColorShader(), "hit")

    def test_numpy_tiles_and_rectangular_viewport(self):
        _, engine = self.make_engine(backend="tiles")
        mesh, faces = make_fixture(5, .7)
        for width, height in ((32, 32), (48, 24)):
            engine.fb = Framebuffer(width, height)
            self.assert_draw(engine, mesh, faces, VertexColorShader(), "miss")
            self.assert_draw(engine, mesh, faces, VertexColorShader(), "hit")

    def test_content_edits_and_submissions_invalidate_without_versions(self):
        mesh, faces = make_fixture(5, .7)
        _, engine = self.make_engine()
        shader = VertexColorShader()
        self.assert_draw(engine, mesh, faces, shader, "miss")
        mutations = (
            lambda: mesh[0].position.__setitem__(0, .25),
            lambda: mesh[0].color.__setitem__(0, .12),
            lambda: faces.reverse(),
            lambda: faces.__setitem__(0, tuple(reversed(faces[0]))),
        )
        previous = engine.last_preparation_receipt["key_sha256"]
        for mutate in mutations:
            mutate()
            self.assert_draw(engine, mesh, faces, shader, "miss")
            self.assertNotEqual(previous, engine.last_preparation_receipt["key_sha256"])
            previous = engine.last_preparation_receipt["key_sha256"]
            self.assert_draw(engine, mesh, faces, shader, "hit")

    def test_unchanged_content_with_new_objects_hits(self):
        mesh, faces = make_fixture(4, .5)
        _, engine = self.make_engine()
        self.assert_draw(engine, mesh, faces, VertexColorShader(), "miss")
        clone = [Vertex(v.position.copy(), v.normal.copy(), v.uv.copy(), v.color.copy()) for v in mesh]
        self.assert_draw(engine, clone, [tuple(f) for f in faces], VertexColorShader(), "hit")

    def test_fragment_work_and_current_depth_are_never_reused(self):
        mesh, faces = make_fixture(1, .8)
        fb, engine = self.make_engine()
        shader = FragmentCounter()
        for status in ("miss", "hit"):
            fb.clear(depth=1.0)
            before = shader.calls
            engine.draw_mesh(mesh, faces, shader)
            self.assertGreater(shader.calls, before)
            self.assertEqual(engine.last_preparation_receipt["status"], status)
        color, depth = buffers(fb)
        before = shader.calls
        engine.draw_mesh(mesh, faces, shader)
        self.assertEqual(shader.calls, before)  # strict-less reads current buffer
        self.assertEqual(buffers(fb), (color, depth))
        fb.clear(depth=-1.0)
        engine.draw_mesh(mesh, faces, shader)
        self.assertEqual(shader.calls, before)
        self.assertTrue(np.all(fb.depth_buffer == -1.0))

    def test_depth_ties_and_removed_foreground_after_clear(self):
        mesh = [Vertex(p, color=[1, 0, 0]) for p in
                ((-.8, -.8, .2, 1), (.8, -.8, .2, 1), (0, .8, .2, 1))]
        mesh += [Vertex(v.position, color=[0, 1, 0]) for v in mesh[:3]]
        _, engine = self.make_engine()
        for faces in ([(0, 1, 2), (3, 4, 5)], [(3, 4, 5), (0, 1, 2)], [(0, 1, 2)]):
            self.assert_draw(engine, mesh, faces, VertexColorShader(), "miss")
            self.assert_draw(engine, mesh, faces, VertexColorShader(), "hit")
        mesh[0].position[2] = -.2
        self.assert_draw(engine, mesh, [(0, 1, 2), (3, 4, 5)], VertexColorShader(), "miss")
        self.assert_draw(engine, mesh, [(3, 4, 5)], VertexColorShader(), "miss")

    def test_clipping_slivers_nonfinite_and_empty_geometry(self):
        vertices = [Vertex(p, color=[.2, .6, .9]) for p in (
            (-2, -.7, 0, 1), (.7, -.7, 0, 1), (0, .7, 0, 1),
            (-.5, -.5, -2, 1), (.5, -.5, 0, 1), (0, .5, 0, 1),
            (0, 0, 0, 1), (1e-8, 0, 0, 1), (0, 1e-8, 0, 1),
            (np.nan, 0, 0, 1))]
        _, engine = self.make_engine()
        for faces in ([(0, 1, 2), (3, 4, 5), (6, 7, 8), (9, 1, 2)], [], [(0, 0, 0)]):
            self.assert_draw(engine, vertices, faces, VertexColorShader(), "miss")
            self.assert_draw(engine, vertices, faces, VertexColorShader(), "hit")

    def test_shader_mvp_normal_and_vertex_attributes_are_dependencies(self):
        mesh, faces = make_fixture(2, .5)
        identity = Matrix4.identity()
        shader = BlinnPhongShader(identity, identity, identity)
        _, engine = self.make_engine()
        self.assert_draw(engine, mesh, faces, shader, "miss")
        edits = (lambda: shader.mvp.__setitem__((0, 3), .1),
                 lambda: shader.normal_matrix.__setitem__((0, 0), .7),
                 lambda: mesh[0].normal.__setitem__(0, .2),
                 lambda: mesh[0].uv.__setitem__(0, .9))
        for edit in edits:
            edit()
            self.assert_draw(engine, mesh, faces, shader, "miss")
            self.assert_draw(engine, mesh, faces, shader, "hit")

    def test_fragment_uniforms_texture_and_light_reexecute_on_hit(self):
        mesh, faces = make_fixture(1, .8)
        identity = Matrix4.identity()
        shader = BlinnPhongShader(identity, identity, identity)
        _, engine = self.make_engine()
        self.assert_draw(engine, mesh, faces, shader, "miss")
        for edit in (lambda: shader.diffuse_color.__setitem__(0, .9),
                     lambda: setattr(shader, "texture", np.full((2, 2, 3), 120, dtype=np.uint8)),
                     lambda: shader.texture.__setitem__((0, 0, 0), 255),
                     lambda: shader.light_dir.__setitem__(0, -.3)):
            edit()
            self.assert_draw(engine, mesh, faces, shader, "hit")

    def test_tile_policy_dependency_reuses_only_matching_bins(self):
        mesh, faces = make_fixture(2, .5)
        _, engine = self.make_engine()
        self.assert_draw(engine, mesh, faces, VertexColorShader(), "miss")
        engine.tile_size = 8
        self.assert_draw(engine, mesh, faces, VertexColorShader(), "miss")
        engine.plan_policy = SurfacePlanPolicy()
        self.assert_draw(engine, mesh, faces, VertexColorShader(), "miss")
        engine.plan_policy = replace(engine.plan_policy, batch_min_samples=99,
                                     draw_min_bbox_samples_per_triangle=0, name="test")
        self.assert_draw(engine, mesh, faces, VertexColorShader(), "hit")

    def test_unknown_or_overridden_vertex_function_bypasses_effects(self):
        mesh, faces = make_fixture(1, .5)
        _, engine = self.make_engine()
        shader = StatefulVertex()
        for _ in range(2):
            before = shader.vertices_seen
            engine.fb.clear()
            engine.draw_mesh(mesh, faces, shader)
            self.assertEqual(shader.vertices_seen - before, len(mesh))
            self.assertEqual(engine.last_preparation_receipt["reason"], "undeclared-vertex-shader")
        self.assertEqual(engine.preparation_cache.bytes, 0)

    def test_instance_replacement_cannot_inherit_pure_admission(self):
        mesh, faces = make_fixture(1, .5)
        _, engine = self.make_engine()
        shader = VertexColorShader()
        self.assert_draw(engine, mesh, faces, shader, "miss")
        shader.vertex_shader = StatefulVertex().vertex_shader
        self.assert_draw(engine, mesh, faces, shader, "bypass")
        self.assertEqual(engine.last_preparation_receipt["reason"], "undeclared-vertex-shader")

    def test_iterators_bypass_without_being_consumed_by_key(self):
        mesh, faces = make_fixture(1, .5)
        _, engine = self.make_engine()
        self.assert_draw(engine, mesh, faces, VertexColorShader(), "miss")
        for v, f in ((iter(mesh), faces), (mesh, iter(faces))):
            engine.fb.clear()
            engine.draw_mesh(v, f, VertexColorShader())
            self.assertEqual(engine.last_preparation_receipt["reason"], "unsupported-input-container")
            reference = prepare_triangles(mesh, faces, VertexColorShader(), 32, 32)
            self.assertEqual(engine.last_preparation_receipt["triangles"], len(reference))

    def test_invalid_indices_still_raise_and_do_not_poison_entries(self):
        mesh, faces = make_fixture(1, .5)
        _, engine = self.make_engine()
        engine.draw_mesh(mesh, faces, VertexColorShader())
        retained = engine.preparation_cache.bytes
        for indices in ([(0, 1, 9999)], [(0, 1, -1)], [(0, 1)], [(0, 1, 2.5)], [(0, 1, 2), (1,)]):
            with self.subTest(indices=indices), self.assertRaises(IndexError):
                engine.draw_mesh(mesh, indices, VertexColorShader())
            self.assertIsNone(engine.last_preparation_receipt)
            self.assertEqual(engine.preparation_cache.bytes, retained)

    def test_input_layout_and_dtype_are_distinct_keys(self):
        mesh, faces = make_fixture(1, .5)
        def key():
            return input_key(mesh, faces, VertexColorShader(), 32, 32, 32, None)[0]
        initial = key()
        mesh[0].position = mesh[0].position.astype(np.float64)
        self.assertNotEqual(key(), initial)
        previous = key()
        mesh[0].position = np.repeat(mesh[0].position, 2)[::2]
        self.assertNotEqual(key(), previous)

    def test_budget_and_lru_evictions_are_bounded(self):
        mesh, faces = make_fixture(1, .5)
        _, engine = self.make_engine(entries=2)
        shader = VertexColorShader()
        for x in (.1, .2, .3):
            mesh[0].position[0] = x
            self.assert_draw(engine, mesh, faces, shader, "miss")
            self.assertLessEqual(engine.preparation_cache.bytes, engine.preparation_cache.max_bytes)
        self.assertEqual(engine.last_preparation_receipt["evicted"], 1)
        mesh[0].position[0] = .2
        self.assert_draw(engine, mesh, faces, shader, "hit")
        mesh[0].position[0] = .1
        self.assert_draw(engine, mesh, faces, shader, "miss")
        cache = engine.preparation_cache
        charge = next(iter(cache._entries.values()))[1]
        cache.max_bytes = charge + 1
        cache.clear()
        for x in (.4, .5):
            mesh[0].position[0] = x
            self.assert_draw(engine, mesh, faces, shader, "miss")
        self.assertEqual(engine.last_preparation_receipt["evicted"], 1)
        cache.clear()
        self.assertEqual(cache.bytes, 0)
        self.assertEqual(len(cache._entries), 0)

    def test_oversize_entry_runs_correctly_without_retention(self):
        mesh, faces = make_fixture(2, .5)
        _, engine = self.make_engine(budget=1)
        for _ in range(2):
            self.assert_draw(engine, mesh, faces, VertexColorShader(), "bypass")
            self.assertEqual(engine.last_preparation_receipt["reason"], "entry-exceeds-budget")
            self.assertEqual(engine.preparation_cache.bytes, 0)

    def test_retained_arrays_and_attribute_maps_have_no_mutable_alias(self):
        mesh, faces = make_fixture(2, .7)
        cache = PreparationCache(1 << 20)
        data, _ = cache.prepare(mesh, faces, VertexColorShader(), 32, 32, 8)
        fresh = prepare_triangles(mesh, faces, VertexColorShader(), 32, 32)
        self.assertTrue(tri_lists_equal(fresh, data.triangles))
        screen = data.triangles[0][0]
        color = data.triangles[0][6]["color"]
        for array in (screen, color):
            with self.assertRaises(ValueError):
                array.setflags(write=True)
            with self.assertRaises(ValueError):
                array.flat[0] = 55
        with self.assertRaises(TypeError):
            data.triangles[0][6]["color"] = np.zeros(3)
        expected = color.tobytes()
        for vertex in mesh:
            vertex.color[:] = 0
        self.assertEqual(color.tobytes(), expected)
        shared = (color, color)
        self.assertLess(retained_bytes(shared), retained_bytes((color, color.copy())))
        self.assertGreater(retained_bytes([1]), 0)

    def test_key_bypasses_unsupported_arrays_and_vertex_subclasses(self):
        mesh, faces = make_fixture(1, .5)
        shader = VertexColorShader()
        mesh[0].color = [.1, .2, .3]
        self.assertEqual(input_key(mesh, faces, shader, 32, 32, 32, None)[1], "unsupported-vertex-array")
        identity = Matrix4.identity()
        lit = BlinnPhongShader(identity, identity, identity)
        lit.mvp = identity.tolist()
        self.assertEqual(input_key(mesh, faces, lit, 32, 32, 32, None)[1], "unsupported-shader-state")
        class ExtraVertex(Vertex):
            pass
        self.assertEqual(input_key([ExtraVertex([0, 0, 0])], [], shader, 32, 32, 32, None)[1],
                         "unsupported-input-container")
        self.assertIsNone(input_key(mesh, [[0, 1, 2], [1]], shader, 32, 32, 32, None)[0])
        mesh, faces = make_fixture(1, .5)
        self.assertEqual(input_key(mesh, [[0, 1, 2], [1]], shader, 32, 32, 32, None)[1],
                         "unsupported-indices")

    def test_random_real_geometry_edits_and_strided_varyings(self):
        rng = np.random.default_rng(813)
        _, engine = self.make_engine(pixels=48, workers=2)
        for seed in range(15):
            mesh, faces = make_fixture(8, .2 + seed * .05)
            for vertex in mesh:
                vertex.position[2] = np.float32(rng.uniform(-1.5, 1.5))
                vertex.color = np.repeat(vertex.color.astype(np.float64), 2)[::2]
            self.assert_draw(engine, mesh, faces, VertexColorShader(), "miss")
            self.assert_draw(engine, mesh, faces, VertexColorShader(), "hit")
            mesh[seed % len(mesh)].position[0] = np.float32(rng.uniform(-2., 2.))
            self.assert_draw(engine, mesh, faces, VertexColorShader(), "miss")

    def test_prepared_bins_cannot_be_reused_with_different_context(self):
        mesh, faces = make_fixture(1, .5)
        triangles = prepare_triangles(mesh, faces, VertexColorShader(), 32, 32)
        bins = bin_triangles(triangles, 32, 32, 8)
        for altered in (None, replace(bins, width=64), replace(bins, tile_size=32),
                        replace(bins, triangles=list(triangles)), replace(bins, scan_min_samples=64)):
            with self.assertRaisesRegex(ValueError, "PREPARED_TILE_BINS_MISMATCH"):
                rasterize_tiles(Framebuffer(32, 32), triangles, VertexColorShader(), 8, None, 1,
                                prepared_bins=object() if altered is None else altered)

    def test_configuration_is_opt_in_and_rejects_bad_budgets_backends(self):
        _, default = self.make_engine(budget=0)
        mesh, faces = make_fixture(1, .5)
        default.draw_mesh(mesh, faces, VertexColorShader())
        self.assertIsNone(default.preparation_cache)
        self.assertIsNone(default.last_preparation_receipt)
        for budget, entries in ((True, 1), (-1, 1), (1.5, 1), (1, 0), (1, True)):
            with self.assertRaises(ValueError):
                SoftwareRasterizer(Framebuffer(8, 8), preparation_cache_bytes=budget,
                                   preparation_cache_entries=entries)
        for budget, entries in ((0, 1), (1, 0), (True, 1)):
            with self.assertRaises(ValueError):
                PreparationCache(budget, entries)
        for backend in ("bands", "tiles-jit"):
            with self.assertRaisesRegex(ValueError, "PREPARATION_CACHE_REQUIRES_NUMPY_TILES"):
                SoftwareRasterizer(Framebuffer(8, 8), backend=backend, preparation_cache_bytes=1)


if __name__ == "__main__":
    unittest.main()
