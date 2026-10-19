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
# Bounded, reproducible user-facing presets; never arbitrary worker commands.
TEST_PRESETS = {
    "Schnelltest · 64 Pixel": (686, 64, "tiles"),
    "Standard · 128 Pixel": (686, 128, "tiles-plan"),
    "Detailtest · 256 Pixel": (1234, 256, "tiles-plan"),
    "Vergleich · Referenzrenderer": (686, 128, "bands"),
}


def preset_values(name: str):
    if name not in TEST_PRESETS:
        raise ValueError("TEST_PRESET_INVALID")
    return TEST_PRESETS[name]



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
    theme = gr.themes.Soft(primary_hue="cyan", secondary_hue="slate", neutral_hue="slate")
    with gr.Blocks(title="ARE SoftwareGPU | CPU-Testlabor", theme=theme) as demo:
        gr.Markdown(
            "# ARE SoftwareGPU · CPU-Testlabor\n"
            "### Echte Grafiktests, ohne Kommandozeile\n"
            "Wähle eine Testvorlage und tippe auf **Test starten**. "
            "Der Server rendert ein Bild, wiederholt den Lauf dreimal und "
            "prüft dessen digitale Prüfsumme. Die App selbst enthält keinen Renderer."
        )
        with gr.Row():
            with gr.Column(scale=2):
                preset = gr.Dropdown(
                    choices=list(TEST_PRESETS), value="Schnelltest · 64 Pixel",
                    label="1 · Testvorlage",
                    info="Schnelltest für den ersten Versuch; Detailtest für mehr Bildpunkte."
                )
                gr.Markdown("**2 · Optional anpassen** · Die voreingestellten Werte funktionieren ohne Änderung.")
                seed = gr.Number(value=686, precision=0, label="Testmuster-Nummer",
                                 info="Dieselbe Nummer erzeugt dasselbe Ausgangsmuster.")
                pixels = gr.Dropdown([64, 128, 256], value=64,
                                     label="Bildgröße in Pixeln")
                backend = gr.Dropdown(
                    list(BACKENDS), value="tiles", label="CPU-Berechnungsweg",
                    info="Tiles = Standard, Tiles-plan = Forschung, Bands = Referenz."
                )
                run = gr.Button("3 · Test starten", variant="primary", size="lg")
                state = gr.Markdown("**Bereit.** Wähle eine Vorlage oder starte den Schnelltest.")
            with gr.Column(scale=3):
                image = gr.Image(label="Tatsächlich auf CPU gerendertes Bild",
                                 interactive=False)
                with gr.Accordion("Technische Prüfdaten und SHA-256", open=False):
                    receipt = gr.JSON(label="Original-Worker-Receipt")
        preset.change(preset_values, inputs=[preset],
                      outputs=[seed, pixels, backend])
        def run_with_message(s, p, b):
            picture, evidence = execute(s, p, b)
            result = evidence["outcome"]
            if not result["repeat_byte_identical"]:
                raise RuntimeError("REPLAY_MISMATCH")
            return (picture, evidence,
                    "**Bestanden:** Der echte CPU-Renderer hat das Bild erzeugt. "
                    "Drei Wiederholungen waren byteidentisch; "
                    f"{result['covered_pixels']} Pixel wurden belegt. "
                    "Details findest du unter »Technische Prüfdaten«.")
        run.click(run_with_message, [seed, pixels, backend], [image, receipt, state],
                  concurrency_limit=1, concurrency_id="are-softwaregpu-cpu")
        gr.Markdown(
            "#### Brauche ich einen Server?\n"
            "Ja. Die Android-APK zeigt diese geschützte Testoberfläche an. "
            "Die CPU-Arbeit findet auf dem Rechner mit dem ARE-Dienst statt. "
            "Ohne erreichbaren HTTPS-Dienst kann die APK keinen Renderjob starten.\n\n"
            "**Grenzen:** Nur prozedurale Testbilder, keine veröffentlichten Original-GLBs, "
            "kein Spielserver und kein Nachweis für eine physische GPU."
        )
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
