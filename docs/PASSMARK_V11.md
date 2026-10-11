# PassMark V11 Linux CPU and memory evidence

Scope: CPU Mark and Memory Mark, never a GPU/GTX/Radeon graphics benchmark. Proprietary PassMark binaries are not redistributed in the repository.

The Python runner pins the exact user-supplied 2025-11-12 V11 Build 1004 archives for x86-64, ARM32 and ARM64. It verifies archive SHA-256, executable SHA-256, ELF architecture, the expected three archive entries and vendor README before launching. Vendor version changes or downloads with new hashes must fail closed until reviewed.

Use Actions > PassMark V11 CPU and memory evidence > Run workflow. Select CPU, memory or all. The GitHub runner is Ubuntu 22.04 with ncurses5 dependencies. PRs run a short CPU profile. Results come from temporary, restricted working directories without inherited credentials. Raw vendor reports are not made public. Receipts record hashes and executed durations; they do NOT invent CPU Mark or Memory Mark numbers. Exit failure, timeout or missing generated vendor result file must block.

VPS (dedicated, non-root, offline and only after assessing the uploaded executable):
python tools/passmark_v11.py audit --arch x86_64 --archive /path/PerformanceTest_Linux_x86-64.zip
python tools/passmark_v11.py run --archive /path/PerformanceTest_Linux_x86-64.zip --output-dir /tmp/are-passmark-results --profile all --iterations 2

The -r 1, -r 2 and -r 3 vendor modes select CPU, memory and both. Wrapper process/duration input fields are bounded metadata until optional vendor CLI flag compatibility is proven; do not treat them as confirmed vendor thread controls.

GitHub runners vary in host CPUs and contention. They verify compatibility, but a stable VPS with fixed hardware, low background load and pinned OS is preferable for comparing repeatable CPU scores. PassMark numbers do not establish graphics-card equivalence; that requires a separate equivalent-scene benchmark executed against real hardware GPU outputs. GitHub Actions workflow files may require credentials with workflow write scope to modify, and a downloaded vendor archive may have a new build not matching pins.
