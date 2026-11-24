# Privacy — ARE SoftwareGPU Diagnostics 0.1.0

The add-on sends no data to its author or to any server. It has no analytics,
telemetry, advertising, user account, cookies, remote scripts, content scripts,
or access to browsing history or other tabs. It does not request browser or
website permissions.

Checks run only after the user selects **Run graphics checks**. They read the
graphics API information Firefox makes available, compile and execute packaged
shaders, inspect API errors, and read a small test image. Results remain in
memory in the diagnostics tab. Closing that tab discards the in-memory report.

**Save results as JSON** creates a local file chosen through Firefox's normal
download behavior. It includes available graphics vendor/renderer or adapter
information, feature/limit values, errors, pixel counts, hashes, and the raw
test-image bytes. The add-on does not upload that file. The user decides
whether to keep or share it.

The source repository, issue tracker, and project website links open those
external pages only when selected. Normal browser requests and the destination
sites' own privacy practices apply to those pages. The add-on does not append
the diagnostic report to the links.

Author: Thomas Markgraf (pseudonym: OuroborosCollective).

Public support: <https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/issues>
