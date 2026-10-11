# PassMark V11: SHA-pinned CPU/Memory benchmark evidence

This lane measures **PassMark CPU Mark and Memory Mark**, not graphics performance. It cannot establish GeForce/GTX/Radeon equivalence. The owner-uploaded three vendor archives are proprietary and must **never** be redistributed via GitHub repository, public release, workflow artifacts, or logs.

## Trusted packages

The runner supports verified x86-64, ARM64 and ARM32 (native Linux execution only), with fixed archive and ELF hashes and a V11 Build 1004 readme check. The exact uploaded x86-64 ZIP SHA-256 is `dab991f957373a5cfaa1e1b212a882bbb4d0fb85abaa22fc7694e8bd9dc070ad`. A changed upstream archive is rejected until separately verified.

## GitHub and host separation

PR, push and manual GitHub workflow jobs run the wrapper and negative-contract tests without executing vendor binaries. A green run **does not mean a PassMark measurement succeeded**. The previous attempted direct vendor download returned **HTTP 403** on 2026-10-11; this dependency was removed from GitHub CI. Actual benchmarking runs separately on an authorized Linux host with the owner-provided local archive. Do not bypass HTTP controls or replace the archive with an unknown binary.

On an authorized, isolated, non-root **Linux VPS**, install the genuine ncurses5 runtime (do not replace it with an unvalidated ncurses6 symlink), provide the uploaded archive using a private authorized file channel and run:

```sh
python tools/passmark_v11.py audit --arch x86_64 --archive /secure/path/PerformanceTest_Linux_x86-64.zip
ARE_BENCH_SOURCE_SHA="$(git rev-parse HEAD)" python tools/passmark_v11.py run --archive /secure/path/PerformanceTest_Linux_x86-64.zip --output-dir /tmp/are-passmark-001 --profile all --processes 1 --iterations 1 --duration 1 --samples 1 --timeout-seconds 900
```

For ARM64 choose `--arch aarch64` at audit time, or `armv7l` on ARM32. The launcher invokes real PassMark vendor flags `-p`, `-i`, `-d`, `-r` and requires exit 0 **and** the corresponding `results_cpu.yml`, `results_memory.yml` or `results_all.yml` with `Results Complete: true`, version 11.0.1004, matching process count and positive required CPU/Memory Mark fields. It emits a JSON receipt with scores, hashes and environment boundaries; vendor YAML is deleted from the ephemeral work directory. Bounded wall times and one test job per host avoid uncontrolled load.

## Real diagnostic evidence, not host normalization

The uploaded x86-64 V11 archive was executed as user `nobody` in an ephemeral Debian-13 container on 2026-10-11, with a **temporary ncurses6-to-ncurses5 diagnostic shim**; this shim is not an approved deployment dependency. A short CPU run produced `results_cpu.yml`, complete with CPU Mark `2645.3099441056506` (SHA-256 `29a597e3489801976e726c1c6ff29af7e155ea53139a807f912979c1216e6d9f`). A short all-suite run produced `results_all.yml`, complete with CPU Mark `2595.5417928140437` and Memory Mark `1809.6752230812042` (SHA-256 `b0def0f26b8e227b1711d98dc282f621a159a2ab66fc4f7287da084ec02a3aa4`). Container resources, shared CPU time and shim prevent comparison to a dedicated VPS baseline. These observations prove that this exact binary genuinely computes results; they do not establish GPU parity, a target-VPS result or the final-head integrated launcher execution.

A PR merge requires green full-head CI, evidence documentation and a final immutable readback. VPS deployment must be separately authorized and actually verified.
