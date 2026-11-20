# OuroborosCollective ARE SoftwareGPU Engine

**CPU-only graphics and compute research for Python 3.11/3.12 on Linux and Windows.**

- Project: https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE
- Real tests and source-bound rendering evidence: https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/actions
- Usage: https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/blob/main/docs/QUICKSTART.md
- Issues and support: https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/issues

## Install from official PyPI (after initial verified release)

Linux (Python 3.11 or 3.12):

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ouroboroscollective-softwaregpu
software-gpu --help
software-gpu --info
```

Windows PowerShell (Python 3.11 or 3.12):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install ouroboroscollective-softwaregpu
.\.venv\Scripts\software-gpu.exe --help
.\.venv\Scripts\software-gpu.exe --info
```

Import the real CPU Python renderer with `import software_gpu`. The installed
CLI remains `software-gpu`; the PyPI distribution name is deliberately unique.
The optional `[jit]` extra uses Numba/LLVM, and `[model-pbr]` adds Pillow.

### What is not included

The native **C++17** rasterizer source/binaries are **not included** in the
Python wheel. They require the separately documented source build. This
package is **not a GPU driver**, CUDA replacement, DirectX system driver,
a general-purpose game engine or a guaranteed FPS accelerator. The Python
API has experimental features; consult the repository contracts.

The separately published npm
`@ouroboroscollective/softwaregpu-gradio-client` provides only a Node.js
HTTPS Gradio probe/launcher. It does not install the renderer or host a server.

### Distribution and security

This project is source-available under **PolyForm Noncommercial 1.0.0**,
not OSI open source. Noncommercial research and permitted personal use are
allowed according to the actual license. Commercial use requires separate
permission. Redistributions must retain **LICENSE.md** and the exact
`Required Notice:` line from **NOTICE**.

The official PyPI publishing workflow runs only for a strict version tag
pointing to a fully tested `main` commit. It builds and verifies a real
wheel and source archive before uploading with PyPI Trusted Publishing.
GitHub Releases carry their own SHA-bound release assets. Until the PyPI
publisher is configured and the initial upload has been independently
read back, no live PyPI availability is claimed.

Do not expose experimental HTTP/Gradio servers to the public without
a separate security review and real authentication.

### Ashen Crypt World Forge

After both main-push CI suites pass, every new first-parent integration after
`22c436385fad7bf79d074d9eaf2cce458a81810e` gets a stable patch release in
the 1.2 series. CI on an open PR builds and tests without publishing.
The Trusted Publisher uploads the same wheel and sdist served by the GitHub release.

On the World Forge VPS, run `sudo bash ops/worldforge/install.sh` once.
A five-minute timer checks PyPI against the GitHub wheel digest, installs in a new
versioned environment and switches the existing CLI link after smoke tests.
To inspect the active version and commit, read `/opt/are-media/learning-current/release.json`.
Previous environments and the local learning database are retained.

The independent review timer reads completed Blender receipts and their hashes.
It writes six static silhouette images and a JSON comparison under
`~unityarpg/.local/share/are-arpg/worldforge-are/<job>/<version>/<receipt-sha>/`.
For a single export, run `are-worldforge review <completed-job> <review-directory>`.
The two lower-detail candidates are geometry-only vertex clusters evaluated from two fixed
views. Animation, skins and unsupported geometry require manual review. The
recommended preview level describes silhouette fidelity at 96 pixels. Original
Unity assets, materials, LODGroups and gameplay are managed by World Forge.
