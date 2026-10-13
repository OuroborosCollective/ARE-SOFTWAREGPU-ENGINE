"""Private optional Gradio facade around the isolated offline CPU renderer.

No remote model input, untrusted shell commands or Aurion gameplay authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/aurion/phase4_offline/job.example.json"
BACKENDS = ("tiles", "tiles-plan", "bands")


def make_job(seed: int, pixels: int, backend: str) -> dict:
    if type(seed) is float and math.isfinite(seed) and seed.is_integer():
        seed = int(seed)  # Gradio Number can return an integer value as float.
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError("SEED_INVALID")
    if type(pixels) is not int or pixels not in (64, 128, 256):
        raise ValueError("PIXELS_INVALID")
    if backend not in BACKENDS:
        raise ValueError("BACKEND_INVALID")
    job = json.loads(FIXTURE.read_text(encoding="utf-8"))
    job["fixture"].update(fixture_id="gradio_cpu_seedmesh", seed=seed)
    job["render"].update(pixels=pixels, backend=backend, repeats=3)
    job["budget"].update(deadline_seconds=90, cpu_seconds=90, memory_mb=2048)
    from software_gpu.integrations.aurion.offline_render_worker import validate_job
    return validate_job(job)


def execute(seed: int, pixels: int, backend: str):
    """Run the real bounded subprocess, hash-check disk outputs before exposure."""
    from PIL import Image
    from software_gpu.integrations.aurion.offline_render_worker import run_job

    job = make_job(seed, pixels, backend)
    with tempfile.TemporaryDirectory(prefix="are-gradio-render-") as temporary:
        output = Path(temporary)
        receipt = run_job(job, out_dir=output)
        disk = json.loads((output / "aurion-phase4-receipt.json").read_text("utf-8"))
        if receipt != disk:
            raise RuntimeError("RECEIPT_READBACK_MISMATCH")
        if disk["errors"] or disk.get("outcome") is None:
            raise RuntimeError("RENDER_FAILED:" + str(disk["errors"]))
        outcome = disk["outcome"]
        if not outcome["repeat_byte_identical"]:
            raise RuntimeError("REPLAY_MISMATCH")
        file = output / (job["fixture"]["fixture_id"] + "_ARE.bmp")
        if file.name != outcome["image_file"]:
            raise RuntimeError("IMAGE_NAME_MISMATCH")
        if hashlib.sha256(file.read_bytes()).hexdigest() != outcome["image_bmp_sha256"]:
            raise RuntimeError("IMAGE_DIGEST_MISMATCH")
        with Image.open(file) as bmp:
            image = bmp.convert("RGB").copy()
        return image, disk


def create_demo():
    import gradio as gr
    with gr.Blocks(title="ARE SoftwareGPU | Private CPU Arena") as demo:
        gr.Markdown("# ARE SoftwareGPU | private offline CPU arena\n"
                    "Seeded geometry only; CPU-vs-CPU is not GPU parity. "
                    "No Aurion gameplay authority or original GLB publication.")
        with gr.Row():
            seed = gr.Number(value=686, precision=0, label="Deterministic mesh seed")
            pixels = gr.Dropdown([64, 128, 256], value=128, label="Resolution")
            backend = gr.Dropdown(list(BACKENDS), value="tiles-plan", label="CPU renderer")
        run = gr.Button("Render and verify", variant="primary")
        with gr.Row():
            image = gr.Image(label="Actual CPU framebuffer", interactive=False)
            receipt = gr.JSON(label="Worker receipt / hashes / CPU timings")
        run.click(execute, [seed, pixels, backend], [image, receipt],
                  concurrency_limit=1, concurrency_id="are-softwaregpu-cpu")
    return demo


def main():
    user, password = os.environ.get("ARE_GRADIO_USER"), os.environ.get("ARE_GRADIO_PASSWORD")
    if not user or not password or len(password) < 20:
        raise SystemExit("SET_ARE_GRADIO_USER_AND_STRONG_PASSWORD")
    create_demo().queue(max_size=3, default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=7860, share=False,
        auth=(user, password), show_error=False, allowed_paths=[])


if __name__ == "__main__":
    main()
