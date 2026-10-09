"""Render observed cross-entropy logs through the actual CPU tile rasterizer."""
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

from ..graphics.framebuffer import Framebuffer
from ..graphics.rasterizer import SoftwareRasterizer
from ..graphics.shader import Shader, Vertex


class MetricShader(Shader):
    def vertex_shader(self, vertex):
        return vertex.position, {"color": vertex.color}

    def fragment_shader(self, varyings):
        rgb = np.clip(varyings["color"], 0, 1) * 255
        return (*[int(round(v)) for v in rgb], 255)


class MetricRecorder:
    """Keep exact loss observations alongside a deterministic, labelled receipt.

    No dataset records are generated. Empty histories produce no chart. A chart
    represents logging observations, not unlogged optimizer steps or validation.
    """
    def __init__(self, output, renderer_revision, model_code_revision):
        for value in (renderer_revision, model_code_revision):
            if not re.fullmatch(r"[0-9a-f]{40}", value):
                raise ValueError("immutable renderer and model code revisions required")
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.revisions = {"renderer_revision": renderer_revision,
                          "model_code_revision": model_code_revision}
        self.history = []

    def observe(self, step, logs):
        if "loss" not in logs:
            return False
        loss = float(logs["loss"])
        if (not isinstance(step, int) or isinstance(step, bool) or step < 0
                or not math.isfinite(loss) or loss < 0):
            raise ValueError("invalid cross-entropy observation")
        if self.history and step <= self.history[-1]["step"]:
            raise ValueError("loss observations must have increasing steps")
        self.history.append({"step": step, "loss": loss})
        raw = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n"
                      for row in self.history).encode()
        (self.output / "loss.jsonl").write_bytes(raw)
        self.render(raw)
        return True

    def render(self, raw):
        fb = Framebuffer(480, 240)
        fb.clear(20, 25, 35)
        vertices, indices = [], []

        def rectangle(x0, y0, x1, y1, color):
            start = len(vertices)
            vertices.extend(Vertex(np.array([x, y, 0.0, 1.0]), color=color)
                            for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
            indices.extend([(start, start + 1, start + 2),
                            (start, start + 2, start + 3)])

        # Grey axes, cyan loss bars: left-to-right logged step, bottom-to-top loss.
        rectangle(-0.91, -0.82, 0.92, -0.80, [0.6, 0.65, 0.7])
        rectangle(-0.92, -0.82, -0.90, 0.9, [0.6, 0.65, 0.7])
        maximum = max(row["loss"] for row in self.history) or 1.0
        maximum_step = max(row["step"] for row in self.history) or 1
        width = min(0.03, 1.7 / max(len(self.history), 1) * 0.6)
        for row in self.history:
            x = -0.85 + 1.72 * row["step"] / maximum_step
            height = 1.65 * row["loss"] / maximum
            if height > 0:
                rectangle(x - width / 2, -0.79, x + width / 2,
                          -0.79 + height, [0.2, 0.8, 0.9])
        raster = SoftwareRasterizer(fb, num_threads=1, backend="tiles")
        try:
            raster.draw_mesh(vertices, indices, MetricShader())
        finally:
            raster.executor.shutdown(wait=True)
        image = self.output / "loss.bmp"
        fb.save_bmp(str(image))
        receipt = {**self.revisions, "device": "cpu", "backend": "tiles",
                   "observations": len(self.history), "x_axis": "logged global step",
                   "x_range": [0, maximum_step], "y_axis": "training cross-entropy",
                   "y_range": [0, maximum], "bar_color": "cyan", "axes_color": "grey",
                   "loss_jsonl_sha256": hashlib.sha256(raw).hexdigest(),
                   "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                   "validation_metrics": None, "model_release_accepted": False}
        (self.output / "render_receipt.json").write_text(
            json.dumps(receipt, indent=2, allow_nan=False) + "\n")


def trainer_callback(output, renderer_revision, model_code_revision):
    """Import Transformers only in a training runtime, not renderer installations."""
    from transformers import TrainerCallback
    recorder = MetricRecorder(output, renderer_revision, model_code_revision)

    class SoftwareGPUCallback(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            if state.is_world_process_zero:
                recorder.observe(state.global_step, logs or {})

    return SoftwareGPUCallback()
