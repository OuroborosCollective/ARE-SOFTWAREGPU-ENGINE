"""Killable per-request computation with no network access inside worker."""
import multiprocessing as mp
import queue

from .security import RequestRejected, SecurityLimits


def _run(method, params, output, memory_limit):
    try:
        # RLIMIT_AS is a real address-space cap on Linux. Windows is kept
        # loopback-only and still uses deadline termination and small inputs.
        import sys
        if sys.platform.startswith("linux"):
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
        from .dispatcher import GPUCommandDispatcher
        result = GPUCommandDispatcher().handle_request(method, params)
        output.put(("ok", result))
    except BaseException:
        output.put(("error", "COMPUTE_FAILED"))


class IsolatedExecutor:
    def __init__(self, limits: SecurityLimits):
        self.limits = limits
        self.context = mp.get_context("spawn")

    def execute(self, method, params):
        result_queue = self.context.Queue(maxsize=1)
        proc = self.context.Process(
            target=_run, args=(method, params, result_queue,
                               self.limits.worker_virtual_memory_bytes), daemon=True
        )
        proc.start()
        try:
            try:
                state, data = result_queue.get(timeout=self.limits.worker_timeout_seconds)
            except queue.Empty:
                raise RequestRejected("WORKER_DEADLINE_EXCEEDED", 504) from None
            if state != "ok":
                raise RequestRejected("COMPUTE_FAILED", 422)
            return data
        finally:
            if proc.is_alive():
                proc.terminate()
            proc.join(timeout=2)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=2)
            result_queue.close()
            result_queue.join_thread()
