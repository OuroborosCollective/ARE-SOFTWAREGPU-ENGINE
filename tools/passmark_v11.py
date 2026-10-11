"""Audited PassMark V11 Linux CPU/RAM runner. Never distributes vendor binaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import time
from zipfile import ZipFile

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
    receipt = {"protocol": "are.passmark-cpu-memory.v1", "version": "V11", "architecture": arch, "archive_sha256": zhash, "executable_sha256": ehash}
    return name, binary, receipt

def run(args):
    arch = {"amd64":"x86_64", "arm64":"aarch64", "armv8l":"armv7l"}.get(platform.machine().lower(), platform.machine().lower())
    if arch not in ARCHIVES:
        raise ValueError("UNSUPPORTED_ARCHITECTURE")
    name, binary, receipt = audit(args.archive, arch)
    if not (1 <= args.iterations <= 5 and 1 <= args.processes <= 8 and 1 <= args.duration <= 2 and 30 <= args.timeout_seconds <= 1200):
        raise ValueError("UNSAFE_BENCHMARK_LIMITS")
    output = Path(args.output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("OUTPUT_DIR_MUST_BE_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    receipt.update({"profile":args.profile, "benchmark_is_gpu":False, "source_sha":os.environ.get("ARE_BENCH_SOURCE_SHA", "unbound"), "iterations":args.iterations, "processes":args.processes, "duration":args.duration, "execution":"not_started", "raw_results_published":False, "measurements":[]})
    try:
        with tempfile.TemporaryDirectory(prefix="are-passmark-", dir=output) as temp:
            wd = Path(temp)
            exe = wd / name
            exe.write_bytes(binary)
            exe.chmod(0o500)
            env = {"PATH":"/usr/bin:/bin", "HOME":temp, "LANG":"C", "LC_ALL":"C", "TERM":"dumb"}
            for index in range(args.iterations):
                start = time.monotonic()
                completed = subprocess.run([str(exe), "-r", str({"cpu":1,"memory":2,"all":3}[args.profile])],cwd=wd,env=env,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=args.timeout_seconds,check=False)
                files = [p for p in wd.iterdir() if p.is_file() and p.name != name and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}",p.name) and p.stat().st_size < 2_000_000]
                receipt["measurements"].append({"index":index, "elapsed_seconds":round(time.monotonic()-start,3), "exit_code":completed.returncode, "stdout_sha256":sha(completed.stdout.encode()), "stderr_sha256":sha(completed.stderr.encode()), "files":[{"name":p.name,"sha256":sha(p.read_bytes()),"bytes":p.stat().st_size} for p in files]})
                if completed.returncode != 0 or not files:
                    raise RuntimeError("PASSMARK_EXIT_FAILURE_OR_RESULT_MISSING")
        receipt["execution"] = "completed"
        (output / "receipt.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
    except Exception as exc:
        receipt["execution"] = "blocked"
        receipt["blocker"] = type(exc).__name__ + ":" + str(exc)[:180]
        (output / "failure.json").write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n")
        raise
    return receipt

def main(argv=None):
    p = argparse.ArgumentParser(description="Pinned PassMark V11 CPU/RAM only; no GPU equivalence")
    sub = p.add_subparsers(dest="action",required=True)
    a=sub.add_parser("audit"); a.add_argument("--arch",required=True,choices=tuple(ARCHIVES)); a.add_argument("--archive",required=True)
    b=sub.add_parser("run"); b.add_argument("--archive",required=True); b.add_argument("--output-dir",required=True)
    b.add_argument("--profile",choices=("cpu","memory","all"),default="all")
    b.add_argument("--iterations",type=int,default=2); b.add_argument("--processes",type=int,default=2)
    b.add_argument("--duration",type=int,default=1); b.add_argument("--timeout-seconds",type=int,default=1000)
    args=p.parse_args(argv)
    if args.action=="audit":
        print(json.dumps(audit(args.archive,args.arch)[2],sort_keys=True))
    else:
        print(json.dumps(run(args),sort_keys=True))
if __name__=="__main__":
    main()
