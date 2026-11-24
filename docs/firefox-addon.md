# ARE SoftwareGPU Diagnostics for Firefox

This desktop Firefox extension runs small graphics checks locally. Its toolbar
action opens a packaged page. **Run graphics checks** compiles real shaders,
draws a red triangle on blue, reads back a 64 × 64 RGBA8 buffer, and verifies
every pixel. **Save results as JSON** downloads the report locally.

Project: <https://arelogic.space/projects/are-softwaregpu-engine/>

Source: <https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE>

Author: Thomas Markgraf, using the pseudonym OuroborosCollective.

## What is checked

| Case | Actual browser operations | Accepted result |
| --- | --- | --- |
| WebGL | Context, shader compilation/link, vertex buffer, triangle draw, `readPixels` | Every pixel and alpha byte matches, no GL/context error |
| WebGPU | Default adapter request, WGSL compilation, render pipeline, submission, texture-to-buffer copy, mapping | Every returned pixel matches, no validation/device/cleanup error |
| WebGPU fallback | Explicit `forceFallbackAdapter: true`, then the same render path | Same requirements; null adapter remains unavailable |

The geometry is fixed at clip coordinates (-0.75, -0.75), (0.75, -0.75),
(0, 0.75). Independent integer edge equations identify 1,152 red and 2,944
blue pixels. No pixel center lies on an edge. WebGL rows start at the bottom;
WebGPU rows start at the top. SHA-256 hashes cover the actual readback bytes.

A passing case establishes this small rendering operation for this session.
It does not establish complete API conformance, engine performance, or ARE
driver use. A CPU, Mesa, or fallback label does not identify the ARE engine.
This extension cannot install a Vulkan ICD, implement browser-native missing
features, change Firefox graphics preferences, or choose the browser's native
driver. It contains no second SoftwareGPU implementation.

## Install a temporary development copy

Use desktop Firefox 142 or later. Open `about:debugging`, choose **This Firefox**,
select **Load Temporary Add-on**, and select the built `.xpi` or
`clients/firefox-addon/manifest.json`. Open the extension from Firefox's
extensions menu, run the checks, and save the report if needed. Temporary
installation ends when Firefox restarts. A signed AMO release is a separate
publication step; the repository's package builder does not sign or publish.

No account, server, API key, browser permission, or content script is required.
The add-on makes no diagnostic network request. Repository and project links
open only when the user selects them. See [privacy details](firefox-addon-privacy.md).

## Build and verify

Python 3.11+ builds the unsigned archive without third-party packages. From the
repository root, choose a new output directory:

```sh
python tools/package_firefox_addon.py --output-dir build/firefox-addon
python -m unittest discover -s software_gpu/tests -p 'test_firefox_addon*.py' -v
node --test tools/firefox-addon-tests/*.test.mjs
```

The build creates the unsigned XPI, a source ZIP, and a receipt with file hashes.
The ten runtime files are copied unchanged, sorted, with fixed ZIP timestamps
and modes. The source ZIP contains those files, this documentation, the builder,
and the tests. Unpack it into an empty directory and rerun the build command to
reproduce the XPI. There is no transpilation, minification, downloaded runtime
code, or JavaScript dependency inside the add-on. ZIP compression bytes can
depend on the Python/zlib version; the receipt also records each original file
hash for comparison across environments.

The `Firefox add-on` GitHub Actions workflow runs Node verification tests,
Python packaging tests, and Mozilla `web-ext` 10.8.0 validation. Node package
installation for that validator occurs only on the GitHub runner. These checks
are not browser/GPU runtime evidence.

The optional Linux runtime harness uses only Python's standard library,
`xvfb-run`, and an existing pinned Firefox installation:

```sh
python tools/firefox_addon_smoke.py \
  --package build/firefox-addon/are-softwaregpu-diagnostics-0.1.0.xpi \
  --install-receipt /path/to/pinned-firefox-install-receipt.json \
  --output-dir /path/to/new-isolated-run
```

Run it as an unprivileged user. The installation receipt supplies
`expectedBuildId` and a `files` mapping whose entries contain `path` and `sha256`,
including `firefox`. The harness verifies those files before and after, starts
its own profile and Xvfb, checks the running browser's `moz:buildID` against the
expected build before installing the exact XPI, opens its toolbar
action, clicks the run and download buttons, independently checks exported
pixels, captures the actual page, uninstalls the temporary add-on, and stops
its own process group. `MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1` is used solely for
Marionette automation of the fresh browser's extension menu; it is not an
add-on permission. The tested Nightly requires this environment variable rather
than the older `--allow-system-access` switch. No graphics
force flags or sandbox bypasses are set. Any later exception, including an
uninstall failure, invalidates the receipt. Keep private runtime receipts outside
the public source tree because they contain local installation paths.

## Recorded validation, 2026-11-24

The exact unsigned XPI SHA-256
`333bbef377251b35a4f1f3abffb9aa952f2d777c66da72b756e43b1ca0ce8af7`
was installed temporarily in Firefox Nightly 163.0a1, build `20261123184640`,
on Linux/Xvfb. The toolbar action opened the real `moz-extension` page; its run
button completed and its downloaded JSON matched the displayed report. WebGL
returned 16,384 actual bytes, all 4,096 pixels verified, SHA-256
`c8a7e867c5f35b0f2c288ea14145d27b3bf869539ac90f85c524d043f6bf7930`.
Both WebGPU requests were unavailable and were not accepted as rendering passes.
This establishes the extension workflow and WebGL test, not ARE native-driver
rendering or WebGPU rendering. Runtime receipt SHA-256:
`ef8f8b6ea2eb56aabb613f51f06fe8286bf27737239017a05731d271fa689479`.

Two earlier harness failures are retained separately: an incorrect assumption
about Marionette's window-list response, and the obsolete CLI method for
enabling privileged test automation. Correcting the harness did not change the
XPI. The final package raises the desktop minimum to Firefox 142 for the strict
Mozilla data-declaration compatibility check and was executed again in Nightly.
Android availability is not declared. Three additional Node control-flow tests
reproduce delayed device loss, normal destruction and missing loss notification;
they use explicitly synthetic test doubles, not runtime rendering evidence.
The WebGPU case now waits for the device's loss notification after its own
destruction before accepting the result; timeout or unexpected loss prevents a
pass. This follows the WebGPU [promise-ordering contract](https://gpuweb.github.io/gpuweb/#promise-ordering)
and [device destruction](https://gpuweb.github.io/gpuweb/#dom-gpudevice-destroy).
Four Python harness tests cover the observed build and exceptions after readback;
together with the six packaging tests and eight Node tests they all pass. A
separate real-browser negative run with an intentionally wrong expected build
recorded the actual build and exited with failure before installing the add-on
(receipt SHA-256 `e998aa8655bbfe8c8642bf1bdbcc93505bb6f771a1c72434b5368172408eb1ad`).
WebGPU rendering and device-loss behavior on an available real WebGPU device
remain unverified in this environment; unit doubles do not change that limit.
GitHub CI, signing and AMO review are independent
gates and must be checked on the submitted source revision.

## Source boundaries and license

`clients/firefox-addon/` is the client/runtime projection. `readback.mjs` verifies
observed bytes; it never supplies substitute graphics output. `tools/` and the
test modules are packaging/testing surfaces, not engine simulation or persisted
world state. The existing deterministic renderer, world seed, tick, native
driver, and server contracts are not used or changed by the extension.

The add-on uses this repository's **PolyForm Noncommercial License 1.0.0**.
The unchanged `LICENSE.md` and `NOTICE` are shipped inside the XPI. This is not
an MIT/Apache/GPL release. AMO listing fields and reviewer instructions are
prepared in [the submission draft](firefox-addon-amo-listing.md).

## Mozilla references

- [Add-on policies](https://extensionworkshop.com/documentation/publish/add-on-policies/)
- [Submission process](https://extensionworkshop.com/documentation/publish/submitting-an-add-on/)
- [Gecko ID and data collection declaration](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/browser_specific_settings)
- [Marionette protocol](https://firefox-source-docs.mozilla.org/remote/marionette/Protocol.html)

Policy and schema references were checked on 2026-11-24. Mozilla controls signing,
review, acceptance, and the eventual public listing.
