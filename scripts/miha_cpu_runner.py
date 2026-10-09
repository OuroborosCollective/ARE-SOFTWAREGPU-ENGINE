"""Immutable MIHA CPU preparation, preflight, candidate publication and readback."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

MODEL = "Thorsu/miha-deepseek-r1-distill-qwen-7b-lora"


def config(path):
    value = json.loads(Path(path).read_text())
    for name in ("code_revision", "evidence_revision", "atomic_revision", "bench_revision", "base_revision"):
        if not re.fullmatch(r"[0-9a-f]{40}", value[name]):
            raise ValueError("immutable revision required: " + name)
    return value


def preflight(settings, output):
    source = output / "policy"
    source.mkdir(parents=True, exist_ok=True)
    with urlopen(f"https://huggingface.co/{MODEL}/resolve/{settings['code_revision']}/cpu_policy.py", timeout=60) as response:
        raw = response.read()
    path = source / "cpu_policy.py"
    path.write_bytes(raw)
    spec = importlib.util.spec_from_file_location("pinned_cpu_policy", path)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    report = {"code_revision": settings["code_revision"], "device": "cpu",
              "policy_sha256": hashlib.sha256(raw).hexdigest(),
              "physical_memory_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"),
              "required_memory_bytes": 16 * 1024**3,
              "training_completed": False, "longest_backward_passed": False,
              "benchmark_passed": False, "success": False}
    try:
        policy.enforce_cpu()
        policy.require_base(settings["base_model"], settings["base_revision"])
        policy.require_training_memory()
        report["memory_gate"] = "PASS"
    except RuntimeError as error:
        report.update(memory_gate="BLOCKED", blocker=str(error))
    (output / "preflight.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    return report["memory_gate"] == "PASS"


def train(settings, output, renderer_revision):
    if not re.fullmatch(r"[0-9a-f]{40}", renderer_revision or ""):
        raise ValueError("immutable renderer revision required")
    if not preflight(settings, output):
        raise RuntimeError("CPU memory gate blocked; no model training started")
    from huggingface_hub import snapshot_download
    snapshot = snapshot_download(MODEL, revision=settings["code_revision"],
                                 allow_patterns=["*.py", "COMPUTE_POLICY.json"])
    command = [sys.executable, str(Path(snapshot) / "train_v2.py"),
               "--artifact-only", "--output-dir", str(output / "candidate"),
               "--output-prefix", "unused-local-candidate", "--epochs", "1",
               "--max-length", "8192", "--checkpoint-steps", "5",
               "--render-metrics", "--renderer-revision", renderer_revision]
    for name in ("code_revision", "evidence_revision", "atomic_revision", "bench_revision", "base_revision"):
        command.extend(["--" + name.replace("_", "-"), settings[name]])
    subprocess.run(command, env={**os.environ, "PYTHONPATH": snapshot}, check=True)


def audit(settings, output):
    from huggingface_hub import snapshot_download
    code = snapshot_download(MODEL, revision=settings["code_revision"], allow_patterns=["*.py"])
    sys.path.insert(0, code)
    from dataset_pipeline import build, strict_json, read_atomic_bytes
    evidence = snapshot_download("Thorsu/miha-evidence", repo_type="dataset",
        revision=settings["evidence_revision"], allow_patterns=["data/auto/*.json", "data/auto_rows/*.jsonl"])
    bench = snapshot_download("Thorsu/miha-bench", repo_type="dataset",
        revision=settings["bench_revision"], allow_patterns=["data/test.jsonl"])
    atomic = snapshot_download("Thorsu/miha-train-atomic", repo_type="dataset",
        revision=settings["atomic_revision"], allow_patterns=["data/train.jsonl*", "build_manifest.json"])
    manifest = build(evidence, bench, {"miha-evidence": settings["evidence_revision"],
                                     "miha-bench": settings["bench_revision"]}, output / "rebuilt")
    published = strict_json((Path(atomic) / "build_manifest.json").read_text())
    raw = read_atomic_bytes(atomic)
    if manifest != published or hashlib.sha256(raw).hexdigest() != manifest["train_jsonl_sha256"]:
        raise ValueError("canonical/Atomic dual readback differs")
    report = {"canonical_atomic_readback": True, "examples": len(raw.splitlines()),
              "input_revisions": settings, "manifest": manifest,
              "training_completed": False, "benchmark_passed": False, "success": False}
    (output / "input_audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"canonical_atomic_readback": True, "examples": report["examples"]}))


def publish(output, prefix):
    from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download
    if not re.fullmatch(r"actions/run-[0-9]+-attempt-[0-9]+", prefix or ""):
        raise ValueError("unique GitHub run prefix required")
    candidate = output / "candidate" / "adapter"
    receipt = json.loads((candidate / "training_manifest.json").read_text())
    if not (receipt.get("training_completed") is True and receipt.get("device") == "cpu"
            and receipt.get("optimizer_steps", 0) > 0 and receipt.get("success") is False
            and receipt.get("status") == "candidate_unvalidated"):
        raise ValueError("complete CPU candidate receipt required; benchmark acceptance remains pending")
    api = HfApi()
    if api.whoami()["name"] != "Thorsu":
        raise ValueError("wrong publication account")
    head = api.model_info(MODEL).sha
    if any(p.startswith(prefix + "/") for p in api.list_repo_files(MODEL, revision=head)):
        raise ValueError("candidate prefix exists; historical files will not be overwritten")
    files = sorted(p for p in candidate.rglob("*") if p.is_file())
    commit = api.create_commit(MODEL, parent_commit=head,
        commit_message="GitHub CPU LoRA candidate; benchmark acceptance pending",
        operations=[CommitOperationAdd(path_in_repo=prefix + "/" + p.relative_to(candidate).as_posix(),
                                       path_or_fileobj=str(p)) for p in files])
    for file in files:
        remote = Path(hf_hub_download(MODEL, prefix + "/" + file.relative_to(candidate).as_posix(),
                                     revision=commit.oid, force_download=True))
        if hashlib.sha256(remote.read_bytes()).digest() != hashlib.sha256(file.read_bytes()).digest():
            raise ValueError("Hub candidate readback hash mismatch")
    report = {"candidate_revision": commit.oid, "prefix": prefix,
              "files_verified": len(files), "hub_readback": True,
              "status": "benchmark_required", "success": False}
    (output / "publication.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


def seal(output):
    files = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(output.rglob("*")) if p.is_file() and p.name != "artifact_hashes.json"}
    (output / "artifact_hashes.json").write_text(json.dumps(files, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["audit", "preflight", "train", "publish", "seal"])
    parser.add_argument("--config", default="fixtures/miha/training.json")
    parser.add_argument("--output", default="miha-run")
    parser.add_argument("--renderer-revision")
    parser.add_argument("--prefix")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.mode == "publish":
        publish(output, args.prefix)
    elif args.mode == "seal":
        seal(output)
    elif args.mode == "train":
        train(config(args.config), output, args.renderer_revision)
    elif args.mode == "audit":
        audit(config(args.config), output)
    elif not preflight(config(args.config), output):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
