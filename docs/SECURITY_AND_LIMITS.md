# Issue #5: Loopback-only compute security

This release **does not authorize public HTTP, TCP, or Android IPC deployment**. No TLS gateway, multi-tenant authorization, security audit or globally portable OS-level memory sandbox has been proven.

## Actual controls
- Fail closed: only literal IPv4 loopback \`127.0.0.1\` can be bound. Startup requires an explicit **32–256 character high-entropy printable ASCII** bearer token, supplied via \`SOFTWAREGPU_AUTH_TOKEN\` or Python API. No token defaults.
- HTTP: every endpoint, including health, requires \`Authorization: Bearer ...\`; CORS preflight rejected, no wildcard \`Access-Control-Allow-Origin\` and no detailed errors echoed.
- Binary TCP: one bounded \`SGPU\` JSON request per connection includes \`token\`. Large or malformed frames are rejected before any unbounded allocation. TCP is not encryption.
- Shared quotas: request ≤256 KiB, response ≤1 MiB, elements ≤16384, render ≤256×256/3000 vertices/3000 triangles, ≤10 million coarse operations per request, up to 4 active socket clients and 2 compute jobs, 2 s I/O timeout and 12 s worker timeout (defaults). Limits can be tightened within hard ceilings.
- Each accepted request runs in a short-lived spawned child process. A deadline kills an overlong compute. Linux also enforces a virtual-address-space cap via \`RLIMIT_AS\`; this is not a portable RAM guarantee on Windows.
- Preflight validates shape, base64 byte count, dtype, nonfinite values, indices and estimated operations **before** dispatch. No request gets access to arbitrary dispatcher methods.
- Scope is an experimental **local-only utility**, not a remotely reachable production service. Do not assume that a local token protects against hostile code running under the same host account.

## Local operation

Generate a fresh random token and keep it out of shell history, logs, issues and Git files:

\`\`\`bash
export SOFTWAREGPU_AUTH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python main.py --server
\`\`\`

Then configure the Python client with its \`token=\` argument or the same environment variable. The service binds only to 127.0.0.1; no remote override is accepted.

## Experimental Android/Linux UDS owner boundary (PR #265)

The `AndroidIPCServer` remains **opt-in**. Its default constructor does **not** start a listener.
An operator must provide an explicit filesystem socket under a pre-existing,
owner-controlled **0700** directory. The final path must not exist (including
symlinks); its components must not traverse symlinks. On successful bind the
server enforces **0600** on the socket and verifies its owning UID; shutdown
removes only the exact socket inode created by this process. No shared
`/tmp/software_gpu.sock` unlink or anonymous abstract namespace fallback.

Linux `SO_PEERCRED` is required and the kernel-attested peer UID must equal
the owner UID **before** the first framed request is read. Explicit abstract
namespaces, when selected by a local caller, enforce the same peer check but
do not acquire filesystem permissions. Environments without kernel peer
credentials fail closed. The existing framing, schema, size, timeout and
four-client admission limits remain active.

Example for a private local process (not an Android production endorsement):

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from software_gpu.mobile.android_server import AndroidIPCServer

with TemporaryDirectory() as private_directory:
    path = str(Path(private_directory) / "ipc.sock")
    service = AndroidIPCServer(socket_path=path, abstract_name=None)
    service.start()
    if not service.ready.wait(3):
        raise RuntimeError(service.startup_error or "UDS_LISTENER_NOT_READY")
    try:
        # Run the actual owner-UID client while this block remains active.
        ...
    finally:
        service.stop()
        service.join(timeout=3)
```

Migration: legacy callers that relied on `/tmp/software_gpu.sock` or an
implicitly enabled `software_gpu` abstract socket must provision an explicit
private socket directory and pass the path to both server and client. Do not
turn the unsafe defaults back on for compatibility. This source contract is
**not proof of Android SELinux label isolation**, cross-app UID enforcement
on an actual device, or deployed multi-tenant authorization. Those require
native Android instrumentation and device/UID/readback evidence under
[Issue #235](https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/issues/235).

## Explicit remaining blockers

1. Real TLS termination, mutually authenticated reverse proxy, threat-model review and deployment-specific CIDR firewall evidence.
2. Container/cgroup memory and CPU quotas with runtime readback on Linux and Windows Job Object isolation on Windows; process deadlines alone cannot universally guarantee RAM bounds.
3. Android IPC has its own ownership boundary and is **not** covered by this HTTP/TCP security contract. Do not launch Android IPC by default along with the new secured server.
4. Additional protocol fuzzing, worker crash/OOM tests, per-job telemetry and an externally reviewed pen-test before any network exposure.

## Evidence gate

Real loopback socket and HTTP tests, Linux/Windows Python 3.11/3.12 CI, wheel/CLI and JIT regressions must remain green. No secret or runtime claim is recorded as successful before independent CI and branch readback. This documentation intentionally does not claim a public production network release.
