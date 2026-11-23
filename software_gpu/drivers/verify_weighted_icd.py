"""Build the Linux developer ICD and exercise it from independent native clients."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

from software_gpu.drivers.build_weighted_icd import build
from software_gpu.learning import LocalLearner
from software_gpu.research.native_symbolic import compiler


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(out, registry, include):
    root = Path(__file__).resolve().parents[2]
    out = out.resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError("Use a fresh evidence directory for training and replay")
    out.mkdir(parents=True, exist_ok=True)
    bundle = out / "icd"
    manifest = build(bundle, registry, include)
    library = bundle / "libare_weighted.so"
    probe = out / "vulkan-draw-probe"
    subprocess.run([compiler(), "-std=c++17", "-I" + str(include),
                    str(root / "native/vulkan/weighted/draw_probe.cpp"), "-lvulkan", "-o", str(probe)], check=True)
    env = os.environ.copy()
    # Older loaders understand only VK_ICD_FILENAMES. Both select the same ICD.
    env.update(VK_DRIVER_FILES=str(manifest), VK_ICD_FILENAMES=str(manifest), VK_LOADER_DEBUG="driver",
               OPENBLAS_NUM_THREADS="1", ARE_LEARNING_DB=str(out / "weights.sqlite3"),
               ARE_VK_RECEIPTS=str(out / "submissions.jsonl"))
    for name in ("VK_ADD_DRIVER_FILES", "VK_LOADER_DRIVERS_SELECT", "VK_LOADER_DRIVERS_DISABLE"):
        env.pop(name, None)
    if sys.prefix == sys.base_prefix:
        env.setdefault("PYTHONHOME", sys.base_prefix)
    env["PYTHONPATH"] = os.pathsep.join([str(root), *[p for p in sys.path if p]])
    def client(command, label, *, expect_success=True):
        r = subprocess.run(command, env=env, capture_output=True, timeout=60)
        (out / (label+".stdout")).write_bytes(r.stdout)
        (out / (label+".stderr")).write_bytes(r.stderr)
        if expect_success != (r.returncode == 0):
            raise RuntimeError(f"{label} exit {r.returncode}: {r.stderr[-2000:]!r}")
        return r
    summary = client(["vulkaninfo","--summary"], "summary")
    if (b"ARE SoftwareGPU (experimental headless CPU)" not in summary.stdout or
            b"PHYSICAL_DEVICE_TYPE_CPU" not in summary.stdout or library.name.encode() not in summary.stderr):
        raise RuntimeError("ARE device identity or isolated loader binding missing")
    client(["vulkaninfo"], "device")
    # Feed a genuinely different, validated fragment module to the same application.
    negative_dir = out / "unsupported"
    negative_dir.mkdir()
    shutil.copy2(bundle / "vert.spv", negative_dir / "vert.spv")
    frag = negative_dir / "other.frag"
    frag.write_text("#version 450\nlayout(location=0) out vec4 o; void main(){o=vec4(1,0,1,1);}\n")
    subprocess.run(["glslangValidator","-V",str(frag),"-o",str(negative_dir/"frag.spv")], check=True)
    subprocess.run(["spirv-val",str(negative_dir/"frag.spv")], check=True)
    negative = client([str(probe),str(negative_dir),str(out/"bad")], "negative", expect_success=False)
    if b"vkCreateShaderModule" not in negative.stderr or (out/"weights.sqlite3").exists():
        raise RuntimeError("unsupported shader rejection or weight isolation unproven")
    x, y = np.meshgrid((np.arange(32)+.5)/32, (np.arange(24)+.5)/24)
    covered = x + y < 1
    expected_rgb = np.stack((1-x-y, x, y), axis=-1)*255
    for i in range(5):
        target = out / f"frame-{i}"
        client([str(probe),str(bundle),str(target)], "draw-" + str(i))
        depth = np.fromfile(target.with_suffix(".depth"),np.float32).reshape(24,32)
        color = np.fromfile(target.with_suffix(".rgba"),np.uint8).reshape(24,32,4)
        if (not np.array_equal(depth, np.where(covered,.5,1.).astype(np.float32))
                or not np.all(color[:,:,3] == 255) or np.any(color[~covered,:3])
                or np.max(np.abs(expected_rgb[covered]-color[covered,:3])) > 1.001):
            raise RuntimeError("independent triangle coverage, gradient or depth mismatch")
    rows = [json.loads(s) for s in (out/"submissions.jsonl").read_text().splitlines()]
    model, = LocalLearner(out/"weights.sqlite3", create=False).status()
    if (len(rows) != 5 or model["scope"]["stage"] != "vulkan-queue-cpp17" or model["pairs"] != 4 or
            model["blocked"] or model["runs"] != 5 or model["scope"]["native_binary_sha256"] != digest(library)):
        raise RuntimeError("persisted Vulkan queue learning not proven")
    rgba = digest(out/"frame-0.rgba")
    depth = digest(out/"frame-0.depth")
    for i, row in enumerate(rows):
        draw = row["native_submission"]
        learned = draw["learning"]
        if (row["driver_sha256"] != digest(library) or row["pipeline_sha256"] != model["scope"]["pipeline_sha256"]
                or draw["shaded_samples"] != int(covered.sum()) or draw["rgba_sha256"] != rgba
                or draw["depth_sha256"] != depth or digest(out/f"frame-{i}.rgba") != rgba
                or digest(out/f"frame-{i}.depth") != depth or draw["native_cpp_calls"] !=
                (1 if learned["served"] == "candidate" else 32) or
                (i < 4 and learned["outcome"] != "matched")):
            raise RuntimeError("native submission, weight or mapped image mismatch")
    evidence = {"revision":subprocess.check_output(["git","rev-parse","HEAD"], cwd=root,text=True).strip(),
        "driver_sha256":digest(library), "manifest_sha256":digest(manifest), "probe_sha256":digest(probe),
        "shader_modules":{s:digest(bundle/(s+".spv")) for s in ("vert","frag")},
        "rgba_sha256":rgba, "depth_sha256":depth, "visible_pixels":int(covered.sum()),
        "paired_measurements":model["pairs"], "fifth_process_served":rows[-1]["native_submission"]["learning"]["served"],
        "snapshot_files":{p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()},
        "headless_only":True, "unity_verified":False}
    evidence["receipt_sha256"]=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    (out/"receipt.json").write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
    return evidence


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("output",type=Path)
    p.add_argument("--registry",type=Path,default=Path("/usr/share/vulkan/registry/vk.xml"))
    p.add_argument("--include",type=Path,default=Path("/usr/include"))
    args=p.parse_args()
    print(json.dumps(verify(args.output,args.registry,args.include),indent=2))
