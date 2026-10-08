# Security and operational limits

**Do not expose the current SoftwareGPU HTTP/TCP/Android IPC prototypes to untrusted networks or tenants.**

The HTTP handler sends wildcard CORS headers and has no mandatory request authentication. The TCP binary protocol and Android IPC also have no hardened identity/authorization boundary. Incoming payload lengths, tensor shapes, compute costs, timeouts and concurrency limits are not yet comprehensively bounded and tested. Accepting an untrusted request can therefore exhaust CPU/RAM or crash a worker.

- The local server defaults to `127.0.0.1`. Keep it behind loopback/firewall in development. Binding to a non-loopback interface is not approved for production.
- Do not issue long-lived API tokens to this experimental server or connect it to canonical Aurion state.
- Before any external deployment: add authenticated/authorized requests, bounded frame/JSON/tensor sizes, deadlines, quotas, TLS at a trusted boundary, safe error reporting and resource isolation.
- Prevent GPU/hardware equivalence claims: all current mathematical and graphics tests execute on CPU.
- For an Aurion integration, isolate the worker in a separate unprivileged process/container with immutable input hashes and read-only application contracts.

The source import runner has only read permissions during extraction and testing, and grants write permissions to a separate job *after* passing source and CPU tests. The archive is SHA-256 pinned; TAR links/compiled caches and generated images are excluded from imports.
