"""Measured raster scheduling after vertex preparation, outside simulation authority."""
from copy import copy
from functools import lru_cache
import hashlib
from pathlib import Path

import numpy as np

from ..learning import bucket, implementation_id, scope_key
from .batch_shader import VertexColorShader, _NATIVE_VERTEX_COLOR_METHODS, _VERTEX_COLOR_BATCH
from .framebuffer import Framebuffer
from .shader import BlinnPhongShader, _BLINN_PHONG_FRAGMENT
from .surface_plan import BATCH_FIRST_POLICY
from .tile_backend import rasterize_tiles


@lru_cache(maxsize=1)
def _source_id():
    root = Path(__file__).parent
    return implementation_id(__file__, *(root / name for name in
                             ("rasterizer.py", "geometry.py", "tile_backend.py",
                              "shader.py", "batch_shader.py", "surface_plan.py", "framebuffer.py")))


def fingerprint(fb):
    digest = hashlib.sha256()
    digest.update(fb.color_buffer.tobytes())
    digest.update(fb.depth_buffer.tobytes())
    return digest.hexdigest()


def _bbox_bucket(triangles, width, height):
    # Bounded pre-raster estimate: sample at most eight clipped projected triangles.
    count = min(8, len(triangles))
    area = 0.0
    for i in range(count):
        a, b, c = triangles[i * len(triangles) // count][:3]
        left = max(0., min(a[0], b[0], c[0]))
        right = min(width, max(a[0], b[0], c[0]) + 1.)
        top = max(0., min(a[1], b[1], c[1]))
        bottom = min(height, max(a[1], b[1], c[1]) + 1.)
        area += max(0., right - left) * max(0., bottom - top)
    return bucket(int(area / count)) if count else 0


def measured_draw(renderer, triangles, shader, prepared_bins):
    fb = renderer.fb
    shader_type = type(shader)
    variant = None
    if (renderer.backend == "tiles" and triangles and renderer.preparation_cache is None
            and type(fb) is Framebuffer and shader_type in (VertexColorShader, BlinnPhongShader)
            and "fragment_shader" not in vars(shader)
            and "fragment_shader_batch" not in vars(shader)):
        if (shader_type is VertexColorShader
                and shader_type.fragment_shader is _NATIVE_VERTEX_COLOR_METHODS[1]
                and shader_type.fragment_shader_batch is _VERTEX_COLOR_BATCH):
            variant = "batch-first"
        elif (shader_type is BlinnPhongShader and shader_type.fragment_shader is _BLINN_PHONG_FRAGMENT
              and renderer.tile_size <= 128):
            variant = "double-tile"
    key = scope_key(stage="raster", implementation=_source_id(), numpy=np.__version__,
                    backend=renderer.backend, variant=variant,
                    shader=shader_type.__module__ + "." + shader_type.__qualname__,
                    textured=shader_type is BlinnPhongShader and shader.texture is not None,
                    width=bucket(fb.width), height=bucket(fb.height),
                    triangles=bucket(len(triangles)), bbox=_bbox_bucket(triangles, fb.width, fb.height) if variant else None,
                    tile=renderer.tile_size, workers=renderer.num_threads)
    if variant is None:
        def observe(_):
            renderer._draw_prepared(triangles, shader, prepared_bins)
        _, receipt = renderer.local_learner.execute(key, observe)
        return receipt

    def run(alternative):
        # Both paths start with existing depth/colour (including earlier draws).
        result = copy(fb)
        result.color_buffer = fb.color_buffer.copy()
        result.depth_buffer = fb.depth_buffer.copy()
        batch = alternative and variant == "batch-first"
        tile = renderer.tile_size * 2 if alternative and variant == "double-tile" else renderer.tile_size
        rasterize_tiles(result, triangles, shader, tile, renderer.executor,
                        renderer.num_threads, planned=batch, plan_policy=BATCH_FIRST_POLICY if batch else None)
        return result

    def publish(result):
        # Keep externally held array references valid.
        np.copyto(fb.color_buffer, result.color_buffer)
        np.copyto(fb.depth_buffer, result.depth_buffer)

    _, receipt = renderer.local_learner.execute(key, run, fingerprint, publish)
    return receipt
