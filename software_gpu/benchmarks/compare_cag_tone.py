"""Compare a fixed analytic tone shader, batch arithmetic, CAG lookup and learned draws."""
import argparse
import json
import math
import os
from pathlib import Path
import platform
from statistics import median
import subprocess
import sys
import tempfile
from time import perf_counter_ns, process_time_ns

import numpy as np

from .compare_local_learning import geometry
from ..graphics.batch_shader import VertexColorShader
from ..graphics.cag_tone import CagToneShader, tone
from ..graphics.framebuffer import Framebuffer
from ..graphics.rasterizer import SoftwareRasterizer
from ..graphics.surface_plan import BATCH_FIRST_POLICY
from ..learning import LocalLearner, MIN_PAIRS
from ..research.cag_profile import digest, replay


class BatchArithmetic(CagToneShader):
    """Same batching and quantization as the candidate; no lookup in this shader."""
    def fragment_shader_batch(self, varyings):
        rgba = VertexColorShader.fragment_shader_batch(self, varyings)
        i = rgba[:, :3].astype(np.int32)
        rgba[:, :3] = i * i * (765 - 2 * i) // 65025
        return rgba


def draw(shader, mesh, pixels, mode, learner=None):
    start = perf_counter_ns()
    fb = Framebuffer(pixels, pixels)
    fb.clear()
    planned = mode in ("batch_arithmetic", "batch_lookup")
    renderer = SoftwareRasterizer(fb, backend="tiles-plan" if planned else "tiles",
                                  plan_policy=BATCH_FIRST_POLICY if planned else None, num_threads=1)
    renderer.local_learner = learner
    try:
        renderer.draw_mesh(*mesh, shader)
    finally:
        renderer.executor.shutdown()
    return fb, perf_counter_ns() - start, renderer.last_learning_receipt


def compare_buffers(ref, other):
    delta = np.abs(ref.color_buffer.astype(np.int16) - other.color_buffer)
    metrics = {"rgba_sha256": digest(other.color_buffer), "depth_f32_sha256": digest(other.depth_buffer),
               "different_pixels": int(np.count_nonzero(delta.any(axis=2))),
               "rgba_max_error": int(delta.max()), "rgba_rmse": float(np.sqrt(np.mean(delta ** 2.0))),
               "different_depth_words": int(np.count_nonzero(
                   ref.depth_buffer.view(np.uint32) != other.depth_buffer.view(np.uint32))),
               "covered_pixels": int(np.count_nonzero(other.depth_buffer < 1))}
    if metrics["different_pixels"] or metrics["different_depth_words"] or not metrics["covered_pixels"]:
        raise ValueError(f"Frame comparison failed: {metrics}")
    return metrics


def compare(provider, db, pixels, repeats):
    start = perf_counter_ns()
    table = replay(provider)
    shader = CagToneShader(table)
    replay_setup = perf_counter_ns() - start
    start = perf_counter_ns()
    local_table = bytes(map(tone, range(256)))
    local_build = perf_counter_ns() - start
    if local_table != table:
        raise ValueError("Local table mismatch")
    arithmetic = BatchArithmetic(table)
    train, holdout = geometry(False), geometry(True)
    start = perf_counter_ns()
    learner = LocalLearner(db)
    store_setup = perf_counter_ns() - start
    training = []
    for _ in range(MIN_PAIRS):
        _, elapsed, receipt = draw(shader, train, pixels, "learned", learner)
        if receipt["outcome"] != "matched":
            raise ValueError("Training did not produce matched buffers")
        training.append(elapsed)
    model, = learner.status()
    training_samples = learner.samples()
    modes = ("scalar", "batch_arithmetic", "batch_lookup", "learned")
    rows = []
    baseline_train = [draw(shader, train, pixels, "scalar")[1] for _ in training]
    for index in range(repeats):
        # Rotate and reverse to distribute warm-cache/order bias.
        order = modes[index % 4:] + modes[:index % 4]
        if index % 8 >= 4:
            order = order[::-1]
        frames, times = {}, {}
        for mode in order:
            frames[mode], times[mode], receipt = draw(arithmetic if mode == "batch_arithmetic" else shader,
                holdout, pixels, mode, learner if mode == "learned" else None)
            if mode == "learned":
                if receipt["scope"] != training_samples[0]["scope"] or receipt["outcome"] != "single":
                    raise ValueError("Holdout did not use calibrated weights")
                served = receipt["served"]
        metrics = {mode: compare_buffers(frames["scalar"], frame) for mode, frame in frames.items()}
        rows.append({"order": order, "frame_ns": times, "served": served, "buffers": metrics})
    medians = {mode: median(row["frame_ns"][mode] for row in rows) for mode in modes}
    setup = provider["preparation_ns"] + replay_setup + store_setup
    sunk = setup + sum(training) - sum(baseline_train)
    saved = medians["scalar"] - medians["learned"]
    return {"pixels": pixels, "workers": 1, "python": platform.python_version(), "numpy": np.__version__,
            "os": platform.system(), "machine": platform.machine(), "training_ns": training,
            "scalar_training_ns": baseline_train, "model_after_training": model,
            "paired_samples": training_samples, "holdout": rows, "median_frame_ns": medians,
            "cost": {"prepare_including_http_ns": provider["preparation_ns"],
                     "http_ns": provider["http_elapsed_ns"], "http_calls_during_render": 0,
                     "local_table_generation_ns": local_build, "replay_and_shader_init_ns": replay_setup,
                     "learning_db_init_ns": store_setup, "provider_price_basis": "owner-declared developer grant",
                     "provider_incremental_eur_at_declared_rate": 0, "provider_invoice_verified": False,
                     "host_compute_price_eur": None,
                     "scalar_total_ns": sum(baseline_train) + sum(row["frame_ns"]["scalar"] for row in rows),
                     "pilot_total_ns": setup + sum(training) + sum(row["frame_ns"]["learned"] for row in rows),
                     "estimated_holdout_frames_to_recover_after_training":
                         max(0, math.ceil(sunk / saved)) if saved > 0 else None}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--handoff", type=Path, help="Optional timed delivery for this provider response")
    parser.add_argument("--pixels", type=int, choices=(64, 96, 128, 192, 256), default=128)
    parser.add_argument("--repeats", type=int, choices=range(4, 25), default=12)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    if git("status", "--porcelain", "--", "software_gpu"):
        parser.error("Commit renderer, benchmark and test sources before recording evidence")
    revision = git("rev-parse", "HEAD")
    read_start = perf_counter_ns()
    raw = args.provider.read_bytes()
    provider = json.loads(raw)
    receipt_read_ns = perf_counter_ns() - read_start
    # Run only in this dedicated CLI process. Fail on any attempted network
    # connection during replay, calibration, or rendering.
    def offline_guard(event, _args):
        if event == "socket.connect":
            raise RuntimeError("Network access attempted during local pilot")
    sys.addaudithook(offline_guard)
    os.environ["ARE_LEARNING_DB"] = "off"  # Isolate this CLI from user databases.
    cpu_start = process_time_ns()
    with tempfile.TemporaryDirectory() as tmp:
        report = compare(provider, Path(tmp) / "pilot.db", args.pixels, args.repeats)
    report["cost"]["benchmark_process_cpu_ns_including_controls"] = process_time_ns() - cpu_start
    report["cost"]["receipt_read_decode_ns"] = receipt_read_ns
    report["cost"]["pilot_total_ns"] += receipt_read_ns
    if args.handoff:
        handoff = json.loads(args.handoff.read_bytes())
        delivered = handoff["elapsed_ms"] * 1_000_000
        if (handoff["schema"] != "are.cag-handoff.v1" or
                handoff["response_uuid"] != provider["response"]["uuid"] or
                handoff["table_sha256"] != provider["table_sha256"] or delivered < provider["preparation_ns"]):
            raise ValueError("Unrelated delivery receipt")
        overhead = delivered - provider["preparation_ns"]
        cost = report["cost"]
        cost["handoff_overhead_beyond_provider_ns"] = overhead
        cost["pilot_total_including_handoff_ns"] = cost["pilot_total_ns"] + overhead
        saving = report["median_frame_ns"]["scalar"] - report["median_frame_ns"]["learned"]
        differential = (delivered + cost["replay_and_shader_init_ns"] + receipt_read_ns +
                        cost["learning_db_init_ns"] + sum(report["training_ns"]) - sum(report["scalar_training_ns"]))
        cost["estimated_holdout_frames_including_handoff"] = max(0, math.ceil(differential / saving)) if saving > 0 else None
        report["handoff_receipt_sha256"] = digest(args.handoff.read_bytes())
    report.update(schema="are.cag-shader-comparison.v1", source_revision=revision,
                  provider_receipt_sha256=digest(raw))
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2, allow_nan=False)
        out.write("\n")


if __name__ == "__main__":
    main()
