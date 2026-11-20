"""Paired end-to-end draw timings on unseen geometry with a frozen training snapshot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter_ns

import numpy as np

from ..graphics.batch_shader import VertexColorShader
from ..graphics.framebuffer import Framebuffer
from ..graphics.rasterizer import SoftwareRasterizer
from ..graphics.shader import Vertex
from ..learning import LocalLearner, MIN_PAIRS


def geometry(held_out):
    # Train on a coplanar rectangle; evaluate two differently coloured, overlapping faces.
    if held_out:
        points = [(-.9, -.8, .6), (.8, -.8, .6), (.1, .9, .6),
                  (-.8, .8, .2), (.8, -.8, .2), (.9, .8, .2)]
        indices = [(0, 1, 2), (3, 4, 5)]
    else:
        points = [(-.8, -.8, .4), (.8, -.8, .4), (.8, .8, .4), (-.8, .8, .4)]
        indices = [(0, 1, 2), (0, 2, 3)]
    colors = [[.2,.5,.8], [.8,.3,.1], [.2,.8,.4]]
    vertices = [Vertex(np.asarray(p, np.float32), color=np.asarray(colors[i % 3], np.float32))
                for i, p in enumerate(points)]
    return vertices, indices


def draw(db, mesh, pixels):
    # Select the installation's public configuration before constructing the renderer.
    os.environ["ARE_LEARNING_DB"] = str(db)
    fb = Framebuffer(pixels, pixels)
    render = SoftwareRasterizer(fb, num_threads=1)
    fb.clear()
    try:
        start = perf_counter_ns()
        render.draw_mesh(*mesh, VertexColorShader())
        elapsed = perf_counter_ns() - start
        color = hashlib.sha256(fb.color_buffer).hexdigest()
        depth = hashlib.sha256(fb.depth_buffer).hexdigest()
        return elapsed, color, depth, render.last_learning_receipt
    finally:
        render.executor.shutdown()


def compare(folder, pixels, repeats):
    train_mesh, holdout_mesh = geometry(False), geometry(True)
    train_db = folder / "train.sqlite3"
    train = [draw(train_db, train_mesh, pixels) for _ in range(MIN_PAIRS)]
    model = LocalLearner(train_db, create=False)
    weights, = model.status()
    if weights["pairs"] != MIN_PAIRS:
        raise RuntimeError("Training did not produce the required equal-buffer pairs")
    observations = []
    for i in range(repeats):
        evaluation_db = folder / f"heldout-{i}.sqlite3"
        # No writers remain. Every evaluation begins with exactly the same weights.
        shutil.copyfile(train_db, evaluation_db)
        runs = {}
        order = ("fixed", "learning") if i % 2 == 0 else ("learning", "fixed")
        for key in order:
            runs[key] = draw("off" if key == "fixed" else evaluation_db, holdout_mesh, pixels)
        fixed, learned = runs["fixed"], runs["learning"]
        if fixed[1:3] != learned[1:3] or learned[1:3] == train[0][1:3]:
            raise RuntimeError("Held-out raster color/depth verification failed")
        if learned[3]["scope"] != train[0][3]["scope"] or learned[3]["outcome"] != "single":
            raise RuntimeError("Held-out geometry did not use the trained profile")
        observations.append({"fixed_ns": fixed[0], "learning_ns": learned[0],
                             "served": learned[3]["served"], "color": fixed[1], "depth": fixed[2]})
    fixed = median(row["fixed_ns"] for row in observations)
    learned = median(row["learning_ns"] for row in observations)
    return {"pixels": pixels, "weights_before_holdout": weights, "training_samples": model.samples(),
            "holdout": observations, "fixed_median_ns": fixed, "learning_median_ns": learned,
            "ratio_fixed_over_learning": fixed / learned}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pixels", type=int, choices=(96, 128, 192, 256), default=128)
    parser.add_argument("--repeats", type=int, choices=range(3, 32), default=11)
    args = parser.parse_args()
    old = os.environ.get("ARE_LEARNING_DB")
    try:
        with TemporaryDirectory() as tmp:
            report = compare(Path(tmp), args.pixels, args.repeats)
    finally:
        if old is None:
            os.environ.pop("ARE_LEARNING_DB", None)
        else:
            os.environ["ARE_LEARNING_DB"] = old
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k.endswith(("_ns", "_learning"))}))


if __name__ == "__main__":
    main()
