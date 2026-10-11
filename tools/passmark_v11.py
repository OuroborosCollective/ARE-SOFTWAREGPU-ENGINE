"""Audited PassMark V11 Linux CPU/RAM runner. Never distributes vendor binaries."""
import argparse
import hashlib
import json
import math
import signal
import statistics
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import time
from zipfile import ZipFile

PROTOCOL = "are.passmark-cpu-memory.v2"
RESULT_NAMES = {"cpu":"results_cpu.yml","memory":"results_memory.yml","all":"results_all.yml"}
NUMERIC = re.compile(r"^[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$")

ARCHIVES = {
    "x86_64": ("PerformanceTest_Linux_x86-64", "dab991f957373a5cfaa1e1b212a882bbb4d0fb85abaa22fc7694e8bd9dc070ad", "98b9607872a1a741a94cfb471c11464ad4eacfa83c34c6d2140b7d80ca878dbe", 62),
    "aarch64": ("PerformanceTest_Linux_ARM64", "968d247170df1a060e798ce0e9c033c83c8e018fafbd2930d4db666c7d435021", "cf1015b9ae3e91218e25c9461bd270c50f901af75c6c16a720219d576639aae0", 183),
    "armv7l": ("PerformanceTest_Linux_ARM32", "c521a068015c551d4ace1ccc229828699fd3b5fac099016aaec0ad6167e42d6f", "5a418f2a40da706ffed3cba0d84945fdaf2f65874d3051e1a47d0f317a14a6b4", 40),
}
def sha(data):
    return hashlib.sha256(data).hexdigest()

def audit(path, arch):
    name, zhash, ehash, machine = ARCHIVES[arch]
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 40_000_000 or sha(path.read_bytes()) != zhash:
        raise ValueError("PINNED_ARCHIVE_SHA256_MISMATCH")
    with ZipFile(path) as z:
        items = z.infolist()
        allowed = {"PerformanceTest/", "PerformanceTest/readme.txt", "PerformanceTest/" + name}
        if len(items) != 3 or {i.filename for i in items} != allowed:
            raise ValueError("UNEXPECTED_ZIP_CONTENTS")
        if any(i.flag_bits & 1 or i.file_size > 25_000_000 or i.filename.startswith("/") or ".." in Path(i.filename).parts or (i.external_attr >> 16) & 0o170000 == 0o120000 for i in items):
            raise ValueError("UNSAFE_ZIP_MEMBER")
        binary = z.read("PerformanceTest/" + name)
        readme = z.read("PerformanceTest/readme.txt").decode("utf-8")
        if sha(binary) != ehash or binary[:4] != b"\x7fELF" or int.from_bytes(binary[18:20], "little") != machine:
            raise ValueError("PINNED_EXECUTABLE_MISMATCH")
        if "11.0 Build 1004" not in readme:
            raise ValueError("UNEXPECTED_VENDOR_VERSION")
    receipt = {"protocol": PROTOCOL, "version": "11.0.1004", "architecture": arch, "archive_sha256": zhash, "executable_sha256": ehash}
    return name, binary, receipt

def _field(text: str, key: str) -> str:
    match = re.search(r"^  " + re.escape(key) + r":\s*([^\r\n]+)\s*$", text, re.M)
    if not match:
        raise ValueError("PASSMARK_MISSING_FIELD:" + key)
    return match.group(1).strip()


def validate_result(path: Path, profile: str, processes: int) -> dict:
    """A successful return code is insufficient: require complete vendor scores."""
    if profile not in RESULT_NAMES or path.name != RESULT_NAMES[profile]:
        raise ValueError("WRONG_VENDOR_RESULT_NAME")
    if path.is_symlink() or not path.is_file() or not 100 <= path.stat().st_size <= 2_000_000:
        raise ValueError("PASSMARK_RESULT_MISSING_OR_UNSAFE")
    raw = path.read_bytes()
    data = raw.decode("utf-8")
    if (not re.search(r"^  Major:\s*11\s*$", data, re.M)
            or not re.search(r"^  Build:\s*1004\s*$", data, re.M)
            or _field(data, "Results Complete").lower() != "true"):
        raise ValueError("PASSMARK_VERSION_OR_COMPLETENESS_MISMATCH")
    reported_processes = _field(data, "NumTestProcesses")
    if reported_processes != str(processes):
        raise ValueError("PASSMARK_PROCESS_COUNT_MISMATCH")
    marks = {}
    for label, name, required in (
        ("cpu_mark", "SUMM_CPU", profile in ("cpu", "all")),
        ("memory_mark", "SUMM_ME", profile in ("memory", "all")),
    ):
        value = _field(data, name)
        if not NUMERIC.fullmatch(value):
            raise ValueError("PASSMARK_SCORE_NOT_NUMERIC:" + name)
        mark = float(value)
        if not math.isfinite(mark) or (required and mark <= 0):
            raise ValueError("PASSMARK_SCORE_NOT_POSITIVE:" + name)
        marks[label] = mark if required else None
    return {"result_filename":path.name, "result_sha256":sha(raw),
            "result_bytes":len(raw), "vendor_version":"11.0.1004",
            "complete":True, "processes_reported":int(reported_processes), **marks}


def _invoke(exe: Path, wd: Path, args):
    command = [str(exe), "-p", str(args.processes), "-i", str(args.iterations),
               "-d", str(args.duration), "-r", str({"cpu":1,"memory":2,"all":3}[args.profile])]
    env = {"PATH":"/usr/bin:/bin", "HOME":str(wd), "LANG":"C",
           "LC_ALL":"C", "TERM":"dumb"}
    start = time.monotonic()
    proc = subprocess.Popen(command, cwd=wd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise RuntimeError("PASSMARK_TIMEOUT") from None
    return proc.returncode, sha(stdout), sha(stderr), round(time.monotonic()-start,4)


def run(args):
    arch = {"amd64":"x86_64", "arm64":"aarch64", "armv8l":"armv7l"}.get(
        platform.machine().lower(), platform.machine().lower())
    if args.profile not in RESULT_NAMES or not (1 <= args.iterations <= 5
            and 1 <= args.processes <= 32 and 1 <= args.duration <= 4
            and 1 <= args.samples <= 5 and 30 <= args.timeout_seconds <= 1800):
        raise ValueError("UNSAFE_BENCHMARK_LIMITS")
    if args.samples * args.timeout_seconds > 3600:
        raise ValueError("BENCHMARK_WALL_BUDGET_EXCEEDED")
    output = Path(args.output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("OUTPUT_DIR_MUST_BE_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    receipt = {
        "protocol": PROTOCOL, "benchmark_is_gpu":False,
        "source_sha":os.environ.get("ARE_BENCH_SOURCE_SHA", "local-unbound"),
        "profile":args.profile, "processes":args.processes,
        "iterations":args.iterations, "duration":args.duration,
        "samples_requested":args.samples,
        "timeout_seconds_per_sample":args.timeout_seconds,
        "host_os":platform.system(), "cpu_arch":arch,
        "affinity_cpus":len(os.sched_getaffinity(0)) if hasattr(os,"sched_getaffinity") else None,
        "execution":"not_started", "raw_results_published":False, "measurements":[]
    }
    try:
        name, binary, pin = audit(args.archive, arch)
        receipt.update(pin)
        for index in range(args.samples):
            with tempfile.TemporaryDirectory(prefix="passmark-v11-", dir=output) as folder:
                wd = Path(folder)
                exe = wd / name
                exe.write_bytes(binary)
                exe.chmod(0o500)
                exit_code, stdout_hash, stderr_hash, elapsed = _invoke(exe, wd, args)
                if exit_code != 0:
                    raise RuntimeError("PASSMARK_NONZERO_EXIT:" + str(exit_code))
                parsed = validate_result(wd / RESULT_NAMES[args.profile],
                                         args.profile, args.processes)
                receipt["measurements"].append({
                    "sample":index+1, "elapsed_seconds":elapsed, "exit_code":exit_code,
                    "stdout_sha256":stdout_hash, "stderr_sha256":stderr_hash, **parsed
                })
        receipt["execution"] = "completed"
        for name in ("cpu_mark", "memory_mark"):
            marks = [m[name] for m in receipt["measurements"] if m[name] is not None]
            receipt[name + "_median"] = statistics.median(marks) if marks else None
        (output/"receipt.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
    except Exception as exc:
        receipt["execution"]="blocked"
        receipt["blocker"]=type(exc).__name__ + ":" + str(exc)[:180]
        (output/"failure.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
        raise
    return receipt


def main(argv=None):
    p=argparse.ArgumentParser(description="SHA-pinned PassMark V11 CPU and RAM tests, never a GPU benchmark")
    sub=p.add_subparsers(dest="action",required=True)
    a=sub.add_parser("audit")
    a.add_argument("--arch",required=True,choices=tuple(ARCHIVES))
    a.add_argument("--archive",required=True)
    b=sub.add_parser("run")
    b.add_argument("--archive",required=True)
    b.add_argument("--output-dir",required=True)
    b.add_argument("--profile",choices=tuple(RESULT_NAMES),default="all")
    b.add_argument("--iterations",type=int,default=1)
    b.add_argument("--processes",type=int,default=1)
    b.add_argument("--duration",type=int,default=1)
    b.add_argument("--samples",type=int,default=1)
    b.add_argument("--timeout-seconds",type=int,default=900)
    args=p.parse_args(argv)
    if args.action=="audit":
        print(json.dumps(audit(args.archive,args.arch)[2],sort_keys=True))
    else:
        print(json.dumps(run(args),sort_keys=True))
if __name__=="__main__":
    main()
