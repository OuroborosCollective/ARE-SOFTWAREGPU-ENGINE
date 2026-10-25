"""Source-bound real CPU whole-frame A/B benchmark. No VPS or publication writes."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import select
import statistics
import subprocess
import sys
import tempfile
import time

SCENES = ("tiny", "small-triangles", "large-surfaces", "procedural400", "procedural5k")
RESOLUTIONS = (64, 128)
WORKERS = (1, 2)
TARGET = "software_gpu/graphics/batch_shader.py"
SOURCE_PATHS = (
    "software_gpu/benchmarks/compare_surface_plans.py",
    "software_gpu/benchmarks/compare_tile_backends.py",
    "software_gpu/integrations/aurion/offline_render_worker.py",
    "software_gpu/graphics/rasterizer.py",
    "software_gpu/graphics/geometry.py",
    "software_gpu/graphics/tile_backend.py",
    "software_gpu/graphics/surface_plan.py",
    "software_gpu/graphics/framebuffer.py",
    TARGET,
    "software_gpu/graphics/shader.py",
)
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")

def require(value, code):
    if not value:
        raise ValueError(code)

def is_pos_number(x):
    return type(x) in (int, float) and math.isfinite(x) and x > 0

def hash_sources(root):
    root = Path(root).resolve()
    result = {}
    for rel in SOURCE_PATHS:
        path = (root / rel).resolve()
        require(path.is_file() and root in path.parents, "SOURCE_MISSING:" + rel)
        result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def check_diff_scope(base, candidate, allow_equal=False):
    require(set(base) == set(SOURCE_PATHS) and set(candidate) == set(SOURCE_PATHS), "SOURCE_SET")
    for rel in SOURCE_PATHS:
        require(bool(SHA64.fullmatch(str(base[rel]))) and bool(SHA64.fullmatch(str(candidate[rel]))), "SOURCE_SHA")
        if rel != TARGET:
            require(base[rel] == candidate[rel], "NON_TARGET_SOURCE_CHANGED:" + rel)
    if not allow_equal:
        require(base[TARGET] != candidate[TARGET], "TARGET_UNCHANGED")

def adjudicate(profiles):
    required = {(scene, pixels, workers) for scene in SCENES for pixels in RESOLUTIONS for workers in WORKERS}
    require(isinstance(profiles, list) and len(profiles) == len(required), "PROFILE_COVERAGE")
    seen, rounds, regressions = set(), [[], []], 0
    for row in profiles:
        require(isinstance(row, dict), "PROFILE_INVALID")
        key = row.get("scene"), row.get("pixels"), row.get("workers")
        require(key in required and key not in seen, "PROFILE_COVERAGE")
        seen.add(key)
        for channel in ("rgba", "depth"):
            before = row.get("baseline_" + channel + "_sha256")
            after = row.get("candidate_" + channel + "_sha256")
            require(bool(SHA64.fullmatch(str(before))) and before == after, channel.upper() + "_PARITY")
        measured = row.get("rounds")
        require(isinstance(measured, list) and len(measured) == 2, "ROUND_COVERAGE")
        for n, rnd in enumerate(measured):
            pairs = rnd.get("pairs") if isinstance(rnd, dict) else None
            require(isinstance(pairs, list) and len(pairs) == 15, "PAIR_COVERAGE")
            ratios = []
            for i, pair in enumerate(pairs):
                require(isinstance(pair, dict), "PAIR_INVALID")
                first = "baseline" if (n+i)%2 == 0 else "candidate"
                require(pair.get("order") == [first, "candidate" if first == "baseline" else "baseline"], "PAIR_ORDER")
                a,b = pair.get("baseline_ms"), pair.get("candidate_ms")
                require(is_pos_number(a) and is_pos_number(b), "PAIR_TIMING")
                ratios.append(a/b)
            med = statistics.median(ratios)
            if med < 0.98:
                regressions += 1
            rounds[n].append(med)
    require(seen == required, "PROFILE_COVERAGE")
    means = [math.exp(statistics.mean(math.log(x) for x in group)) for group in rounds]
    outcome = "rejected" if regressions else "accepted" if all(x >= 1.02 for x in means) else "no_gain"
    return {"outcome": outcome, "score": math.sqrt(means[0]*means[1]), "round_geomeans": means,
            "profile_count": len(seen), "regressed_profile_rounds": regressions}

def git(root, *args):
    p = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, timeout=90)
    require(p.returncode == 0, "GIT_ERROR:" + " ".join(args[:2]) + ":" + p.stderr[-200:])
    return p.stdout.strip()

def worker(repo):
    repo = Path(repo).resolve()
    require(repo.is_dir(), "WORKER_ROOT_MISSING")
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    import numpy as np
    from software_gpu.benchmarks.compare_surface_plans import SCENES as scene_specs, build_scene
    from software_gpu.graphics.batch_shader import VertexColorShader
    from software_gpu.graphics.framebuffer import Framebuffer
    from software_gpu.graphics.rasterizer import SoftwareRasterizer
    specs = dict(scene_specs)
    engine = framebuffer = shader = None
    current = None
    try:
        for line in sys.stdin:
            request = json.loads(line)
            key = request.get("scene"), request.get("pixels"), request.get("workers")
            require(key[0] in SCENES and key[1] in RESOLUTIONS and key[2] in WORKERS, "WORKER_PROFILE")
            if key != current:
                if engine is not None:
                    engine.executor.shutdown(wait=True)
                mesh, faces = build_scene(specs[key[0]])
                framebuffer = Framebuffer(key[1], key[1])
                engine = SoftwareRasterizer(framebuffer, backend="tiles-plan", num_threads=key[2])
                shader = VertexColorShader()
                current = key
            framebuffer.clear(16,25,38,255,depth=1.0)
            start = time.perf_counter_ns()
            engine.draw_mesh(mesh,faces,shader)
            ms = (time.perf_counter_ns()-start)/1e6
            require(is_pos_number(ms), "WORKER_TIME")
            require(framebuffer.color_buffer.dtype == np.uint8 and framebuffer.depth_buffer.dtype == np.float32, "BUFFER_DTYPE")
            print(json.dumps({"ms":ms,"rgba_sha256":hashlib.sha256(framebuffer.color_buffer.tobytes()).hexdigest(),
                              "depth_sha256":hashlib.sha256(framebuffer.depth_buffer.tobytes()).hexdigest()}),flush=True)
    finally:
        if engine is not None:
            engine.executor.shutdown(wait=True)
    return 0

def rpc(proc, message, deadline):
    require(proc.poll() is None, "WORKER_DIED")
    proc.stdin.write(json.dumps(message)+"\n")
    proc.stdin.flush()
    remaining = min(120,deadline-time.monotonic())
    require(remaining > 0, "TIME_BUDGET")
    ready,_,_ = select.select([proc.stdout], [], [], remaining)
    require(bool(ready), "WORKER_TIMEOUT")
    line = proc.stdout.readline()
    require(0 < len(line) < 4096, "WORKER_REPLY")
    value = json.loads(line)
    require(is_pos_number(value.get("ms")), "WORKER_TIMING")
    require(all(bool(SHA64.fullmatch(str(value.get(k)))) for k in ("rgba_sha256","depth_sha256")), "WORKER_HASH")
    return value

def measure(root,baseline,output,smoke,budget,candidate=None,sweep=None):
    root = Path(root).resolve()
    require(root.is_dir() and Path(output).is_absolute(), "ABS_PATH_REQUIRED")
    require(bool(SHA40.fullmatch(baseline)) and 0 < budget <= 2700, "ARGUMENTS_INVALID")
    if not smoke:
        require(isinstance(candidate,str) and candidate in ("scalar-float32-rgb-conversion","batch-rgb-inplace-clamp","batch-rgba-allocation","batch-broadcast-and-stride","shader-call-overhead","batch-dtype-fastpath"), "CANDIDATE_INVALID")
        require(type(sweep) is int and sweep > 0, "SWEEP_INVALID")
    head = git(root,"rev-parse","HEAD")
    require(bool(SHA40.fullmatch(head)), "HEAD_INVALID")
    dirty = [x[3:] for x in git(root,"status","--porcelain","--untracked-files=no").splitlines() if x.strip()]
    require(all(x==TARGET for x in dirty), "DIRTY_OUTSIDE_TARGET")
    deadline = time.monotonic()+budget
    oldenv = dict(os.environ)
    os.environ.update({k:"1" for k in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","NUMEXPR_NUM_THREADS","VECLIB_MAXIMUM_THREADS")})
    try:
        with tempfile.TemporaryDirectory(prefix="are-autoloop-") as td:
            base = Path(td)/"baseline"
            git(root,"worktree","add","--detach",str(base),baseline)
            try:
                before,after = hash_sources(base),hash_sources(root)
                check_diff_scope(before,after,allow_equal=smoke)
                with (Path(td)/"worker.log").open("wb") as logs:
                    env = os.environ.copy()
                    procs = {
                        name:subprocess.Popen([sys.executable,"-u",str(Path(__file__).resolve()),"--worker",str(path)],
                                              cwd=path,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=logs,
                                              text=True,bufsize=1,env=env)
                        for name,path in (("baseline",base),("candidate",root))
                    }
                    try:
                        profiles = []
                        for scene in SCENES[:1] if smoke else SCENES:
                            for pixels in RESOLUTIONS[:1] if smoke else RESOLUTIONS:
                                for workers in WORKERS[:1] if smoke else WORKERS:
                                    request = {"scene":scene,"pixels":pixels,"workers":workers}
                                    hashes={}
                                    for label in ("baseline","candidate"):
                                        v = rpc(procs[label],request,deadline)
                                        hashes[label]=(v["rgba_sha256"],v["depth_sha256"])
                                    require(hashes["baseline"]==hashes["candidate"],"WARMUP_PARITY")
                                    rounds=[]
                                    for n in range(1 if smoke else 2):
                                        pairs=[]
                                        for i in range(2 if smoke else 15):
                                            first="baseline" if (n+i)%2==0 else "candidate"
                                            order=[first,"candidate" if first=="baseline" else "baseline"]
                                            item={"order":order}
                                            for label in order:
                                                v=rpc(procs[label],request,deadline)
                                                require((v["rgba_sha256"],v["depth_sha256"])==hashes[label],"FRAME_NONDETERMINISTIC")
                                                item[label+"_ms"]=v["ms"]
                                            pairs.append(item)
                                        rounds.append({"pairs":pairs})
                                    profiles.append({"scene":scene,"pixels":pixels,"workers":workers,"rounds":rounds,
                                                     "baseline_rgba_sha256":hashes["baseline"][0],
                                                     "candidate_rgba_sha256":hashes["candidate"][0],
                                                     "baseline_depth_sha256":hashes["baseline"][1],
                                                     "candidate_depth_sha256":hashes["candidate"][1]})
                    finally:
                        for p in procs.values():
                            if p.poll() is None:p.terminate()
                            try:p.communicate(timeout=8)
                            except subprocess.TimeoutExpired:p.kill();p.communicate()
                require((Path(td)/"worker.log").stat().st_size < 1048576,"WORKER_LOG_OVERFLOW")
            finally:
                git(root,"worktree","remove","--force",str(base))
    finally:
        os.environ.clear();os.environ.update(oldenv)
    result={"protocol":"are.autoloop-cpu-ab-smoke.v1" if smoke else "are.autoloop-cpu-ab-run.v1",
            "baseline_commit":baseline,"source_commit":head,"source_sha256":after,"baseline_source_sha256":before,
            "render_scope":"whole-draw CPU RGBA8 plus float32 depth",
            "environment":{"runner":os.getenv("RUNNER_ENVIRONMENT","unverified-local"),"cpu":platform.processor() or platform.machine(),
                           "python":platform.python_version(),"numpy":_numpy_version(),"workers":[1,2]},
            "profiles":profiles,"candidate_dirty_shader":bool(dirty),"smoke_only":bool(smoke)}
    if not smoke:
        result["candidate"] = candidate
        result["sweep"] = sweep
    decision=({"outcome":"smoke-pass","score":1.0,"profile_count":len(profiles)} if smoke else adjudicate(profiles))
    result.update(decision)
    result["sha256"]=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    path=Path(output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    require(json.loads(path.read_text())["sha256"]==result["sha256"],"RECEIPT_READBACK")
    return result

def _numpy_version():
    import numpy
    return numpy.__version__

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline")
    p.add_argument("--output",type=Path)
    p.add_argument("--max-seconds",type=int,default=2400)
    p.add_argument("--smoke",action="store_true")
    p.add_argument("--candidate")
    p.add_argument("--sweep",type=int)
    p.add_argument("--worker",type=Path,help=argparse.SUPPRESS)
    args=p.parse_args()
    if args.worker:return worker(args.worker)
    require(args.baseline and args.output,"ARGUMENTS_MISSING")
    result=measure(Path.cwd(),args.baseline,args.output,args.smoke,args.max_seconds,args.candidate,args.sweep)
    print(json.dumps({"score":result["score"] if result["outcome"]=="accepted" else 1.0,
                      "outcome":result["outcome"],"profiles":result["profile_count"],
                      "receipt_sha256":result["sha256"]}))
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired,json.JSONDecodeError,KeyError) as exc:
        print("AUTOLOOP_AB_BLOCKED:"+str(exc),file=sys.stderr);sys.exit(1)
