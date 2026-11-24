# AMO submission draft — ARE SoftwareGPU Diagnostics

This is reviewable listing material, not evidence of AMO registration or
approval. Submit only the tested XPI and retain its package receipt. The account
owner must use the correct existing Mozilla account and review Mozilla's terms.

| Field | Proposed value |
| --- | --- |
| Name | ARE SoftwareGPU Diagnostics |
| Version | 0.1.0 |
| Requested slug | are-softwaregpu-diagnostics (subject to availability) |
| Summary | Test local WebGL and WebGPU rendering, verify every returned pixel, and save a private graphics report. |
| Primary category | Web Development, if available in the submission form |
| Platforms | Firefox desktop; no Android compatibility claim |
| Source | https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE |
| Project homepage | https://arelogic.space/projects/are-softwaregpu-engine/ |
| Support website | https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/issues |
| Author | Thomas Markgraf (pseudonym: OuroborosCollective) |
| License | Custom: PolyForm Noncommercial License 1.0.0; use the exact repository LICENSE.md text |
| Data collection | None; `required: ["none"]` declared in the manifest |

Do not invent a support email, organization registration, ownership credential,
store status, Firefox endorsement, performance result, or native-driver claim.

## Description

Check what this Firefox session can actually render. ARE SoftwareGPU
Diagnostics compiles shaders, draws a small test image through WebGL and
WebGPU, and verifies all 4,096 returned pixels. WebGPU is checked with both the
default adapter request and an explicit fallback-adapter request.

Open the extension from Firefox's extensions menu, select **Run graphics
checks**, and inspect each result. Unsupported APIs and unavailable adapters
are shown separately. **Save results as JSON** saves the local report,
including graphics information, API errors, hashes, and the test-image bytes.

Everything runs locally. The extension uses no analytics, makes no diagnostic
network request, reads no browsing history, and requests no website permissions.

The extension is a diagnostic companion to the ARE SoftwareGPU Engine project.
It does not install or select a native GPU driver, add missing browser graphics
features, or claim that a CPU/Mesa label proves the ARE engine is active. A pass
confirms the small test operation for that browser session, not full graphics
API conformance or a performance benchmark.

Source and project information are linked in the extension:

- https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE
- https://arelogic.space/projects/are-softwaregpu-engine/

## Reviewer instructions

1. Install the submitted XPI in desktop Firefox 142 or later. No account,
   credentials, API key, backend, or optional permission is needed.
2. Open Firefox's extensions menu and select **ARE SoftwareGPU Diagnostics**.
   Its toolbar action opens the packaged diagnostics page in a new tab.
3. Confirm that nothing has run and the save button is disabled.
4. Select **Run graphics checks**. Each supported case draws a red triangle on
   a blue background and checks every pixel. WebGPU can legitimately return
   `Unavailable` on a machine without a browser-exposed adapter; that is not
   reported as a graphics pass.
5. Expand **Detailed local report** and select **Save results as JSON**.
   The download contains the same report shown on the page.
6. Run again if desired. Fresh canvases prevent previous results from being
   reused. No remote service is contacted by any diagnostic case.

All packaged JavaScript, shaders, CSS, HTML and SVG are readable original
source. There are no generated or bundled JavaScript dependencies. The source
ZIP includes a dependency-free Python packaging script, tests, and rebuild
instructions. The XPI ships the repository's exact license and notice.

The add-on provides its complete diagnostic function locally; the project
links are supplemental. It is not a website launcher or native-driver installer.

## Release notes

Initial local graphics diagnostic: WebGL and WebGPU shader/draw/readback
checks, complete 64 × 64 pixel verification, explicit unavailable/error states,
and a local JSON export.
