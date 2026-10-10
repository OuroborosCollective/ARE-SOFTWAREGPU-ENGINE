"""Isolated Phase-4 child entry point (subprocess bootstrap).

Stdlib-only at import time by design: CPU/RAM rlimits are applied BEFORE
numpy or the software_gpu package (whose __init__ pulls in heavy modules)
are imported, so memory limits genuinely bound the whole render. The parent
talks to this child exclusively through an atomic reply file.
"""
import json
import math
import os
from pathlib import Path
import sys

STARTUP_FLOOR_MB = 512  # minimum RLIMIT_AS for a reliable CPython+numpy start


def _apply_limits(budget):
    if sys.platform.startswith("linux"):
        import resource
        # The kernel limit sits at max(budget, STARTUP_FLOOR): below the floor
        # CPython + numpy/OpenBLAS cannot even start reliably (allocation
        # failure inside native threadpool init can hang instead of raising).
        # The contractual budget itself is enforced fail-closed by the parent
        # via the child-reported peak-RSS receipt.
        memory_mb = max(int(budget["memory_mb"]), STARTUP_FLOOR_MB)
        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024**2,) * 2)
        # Cooperative checks inside execute_job enforce the exact budget; this
        # kernel limit at 2x (min 1 s) is only a backstop against hangs inside
        # a single raster call.
        hard_cpu = max(1, int(math.ceil(float(budget["cpu_seconds"]) * 2)))
        resource.setrlimit(resource.RLIMIT_CPU, (hard_cpu, hard_cpu))


def _write_reply(path: Path, payload: dict):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def main(argv):
    job_path, model_dir, out_dir = Path(argv[1]), argv[2], Path(argv[3])
    reply_path = Path(argv[4])
    try:
        job = json.loads(job_path.read_text("utf-8"))
        _apply_limits(job["budget"])
        from software_gpu.integrations.aurion.offline_render_worker import execute_job
        outcome = execute_job(job, None if model_dir == "-" else model_dir, out_dir)
        _write_reply(reply_path, {"ok": outcome})
    except MemoryError:
        _write_reply(reply_path, {"error": "MemoryError",
                                  "family": "WORKER_MEMORY_EXCEEDED"})
    except ValueError as exc:
        _write_reply(reply_path, {"error": "ValueError", "family": str(exc)[:120]})
    except BaseException as exc:
        _write_reply(reply_path, {"error": type(exc).__name__,
                                  "family": str(exc)[:120]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
