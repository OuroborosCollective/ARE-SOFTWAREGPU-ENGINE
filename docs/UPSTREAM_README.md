# Original upstream README - unverified claims

Preserved for provenance. Performance and native CUDA, DirectX or Android compatibility have not been independently verified.

---

# SoftwareGPU — Software-basierter GPU-Prozessor auf CPU

Ein vollständiger, modularer und **voll funktionsfähiger Software-GPU-Prozessor**, der Aufgaben dedizierter Grafikkarten nahtlos auf moderne Mehrkern-CPUs umleitet.
**Keine Mocks, keine Stubs — alle Berechnungen, DirectX 11 Draw-Calls, Antialiasing-Verfahren und Bildausgaben werden in Echtzeit auf der CPU ausgeführt.**

---

## 🌟 Übersicht aller integrierten Features

### 1. Compute & GPGPU (SIMT auf SIMD)
* **Wissenschaftliche Basis:** MCUDA (University of Illinois) und PoCL (Portable Computing Language).
* **Ausführungsmodell:** Grids $\to$ Thread-Blöcke $\to$ Warps (32 Lanes) $\to$ Threads.
* **Barriere-Synchronisation:** Kooperatives Phasen-Splitting für `__syncthreads()`.
* **Kernels:** Tiled GEMM mit Shared Memory, parallele Baumreduktion, 2D-Faltung, Vektor-Aktivierungen (ReLU, GELU).
* **CUDA Drop-In:** Direkte Ausführung von `@cuda.jit`-Code auf CPU-Kernen.

### 2. DirectX 11 (Direct3D 11) Subsystem
* **Wissenschaftliche Basis:** Microsoft WARP (*Windows Advanced Rasterization Platform*) & Mesa D3D12/llvmpipe.
* **Pipeline-Klassen:** `ID3D11Device`, `ID3D11DeviceContext`, `IDXGISwapChain`, `ID3D11Buffer`.
* **Draw-Calls:** `DrawIndexed()` mit HLSL-Vertex- und Pixel-Shadern, Depth-Stencil-Buffer und DXGI `Present()`.

### 3. Gaming-PC Antialiasing & HDR Postprocessing
* **4x MSAA:** Subpixel-Coverage-Sampling mit 4 versetzten Stützstellen pro Pixel und Box-Filter-Resolve (**34,6 % glattere Kanten**).
* **FXAA:** Fast Approximate Anti-Aliasing (Timothy Lottes / NVIDIA) für Screen-Space-Kantenglättung in **21 ms** (**50,8 % messbare Glättung**).
* **HDR Bloom & ACES Filmic Tone Mapping:** High-Pass Glanzlichter, 2-Pass Glow-Blur, ACES-Kurve und sRGB Gamma 2.2 Korrektur.

### 4. VPS-Server CPU-Erkennung & Hardware-Governor
* **cgroup Quota Detection:** Liest cgroup v2 (`/sys/fs/cgroup/cpu.max`) und cgroup v1 (`cpu.cfs_quota_us`) zur exakten Bestimmung real verfügbarer CPU-Kerne aus.
* **Virtualisierungs-Prüfung:** Erkennt KVM, QEMU, Xen, VMware und Container.
* **Headroom-Schutz:** Der Modus `VPS_SAFE` reserviert automatisch **30 % CPU-Puffer** für Betriebssystem, Webserver und Datenbanken, um CPU-Steal und Hypervisor-Drosselung zu verhindern.

### 5. Multi-System Endpoints & Cross-Language Clients
* **HTTP REST & JSON-RPC 2.0 (Port 8088):** Für Web-Tools, Microservices und REST-Clients.
* **High-Speed Binary Socket (Port 8089):** 20-Byte Binär-Framing (`SGPU`) für High-Throughput Tensor-Streaming.
* **Multi-Language Clients:**
  * **Python:** `software_gpu/clients/python_client.py`
  * **C (POSIX C99):** `software_gpu/clients/c_client.h`
  * **C++ (C++17):** `software_gpu/clients/cpp_client.hpp`
  * **Node.js / TypeScript:** `software_gpu/clients/node_client.js`
  * **C# (.NET / Unity):** `software_gpu/clients/csharp_client.cs`
  * **Rust (Bevy / Veloren):** `software_gpu/clients/rust_client.rs`
  * **Go:** `software_gpu/clients/go_client.go`

### 6. Android & Mobile Endgeräte
* **Linux / Android Abstract Namespace (`\0software_gpu`):** Zero-Permission IPC ohne Dateisystem-Konflikte.
* **Android LocalSocket / Unix Domain Sockets (`/tmp/software_gpu.sock`):** Latenz $< 0,1\text{ ms}$.
* **Android Native Kotlin Client:** `software_gpu/mobile/AndroidGPUClient.kt`.
* **OpenGL ES 3.0 & EGL Emulation:** Mobile Draw-Calls (`glDrawArrays`, `glClearColor`, `eglSwapBuffers`).

### 7. MMORPG- & Game-Engine-Integration
* **5.000 Entitäten Physik:** Symplektische Euler-Integration und Weltgrenzen-Kollision.
* **Boids Schwarm-AI:** Flocking- und Verfolgungsalgorithmen in Echtzeit.
* **Server-Side Frustum Visibility Culling:** Spart bis zu **75,2 %** der Netzwerkpakete ein.
* **Performance:** **0,96 ms pro Server-Tick** (Kapazität für über 1.000 Ticks/s bei 60 Hz Budget von 16,66 ms).

### 8. Externe Grafik- & Render-Tools
* **Blender Add-on & Bridge:** Implementiert `bpy.types.RenderEngine` zum Offloading von Blender-Renderpässen.
* **Bildbearbeitungs-Endpoint:** Gaußscher Weichzeichner, Sobel-Kantenerkennung, Kontrast- und Farbkorrektur für GIMP, Photoshop, Krita und Web-Editoren.

### 9. Load- & Stress-Benchmark (FPS & Abfallkurve)
* **Compute Scaling:** Von $64\times 64$ (60.438 FPS) bis $1024\times 1024$ (**750,82 GFLOPS Peak**).
* **3D Rasterization Stress:** FPS-Messung und ASCII-Abfallkurve unter steigender Dreiecksdichte.
* **Score:** **81.454 Punkte** (gespeichert in `benchmark_load_curve_report.json`).

---

## 🚀 Schnelleinstieg & Befehle

Im Root-Verzeichnis `/workspace` steht das zentrale CLI-Tool `main.py` bereit:

```bash
# 1. Alle Funktionen & Demos nacheinander ausführen
python3 /workspace/main.py --all

# 2. Hardware- & VPS-Governor-Informationen anzeigen
python3 /workspace/main.py --info

# 3. DirectX 11 Pipeline ausführen
python3 /workspace/main.py --directx

# 4. Gaming-PC Antialiasing (MSAA, FXAA, HDR Bloom) ausführen
python3 /workspace/main.py --gaming

# 5. MMORPG 5.000 Entitäten Simulation ausführen
python3 /workspace/main.py --mmorpg

# 6. Blender Render Engine Bridge ausführen
python3 /workspace/main.py --blender

# 7. Bildbearbeitungs-Filter ausführen
python3 /workspace/main.py --filters

# 8. Dynamischen Last-Benchmark mit Abfallkurve starten
python3 /workspace/main.py --benchmark

# 9. Multi-Protokoll-Server (HTTP, TCP, Android UDS) im Hintergrund starten
python3 /workspace/main.py --server --http-port 8088 --tcp-port 8089

# 10. Vollständige Testsuite (22 Unit-Tests) ausführen
PYTHONPATH=/workspace python3 -m unittest discover -s /workspace/software_gpu/tests
```

---

## 📁 Struktur des Workspaces

```
/workspace/
├── main.py                     # Zentrales CLI-Werkzeug für alle Funktionen
├── setup.py                    # Python-Paket-Konfiguration
├── README.md                   # Dieses Dokument
├── benchmark_load_curve_report.json # Detaillierter Benchmark-Report
│
├── directx_software_gpu_render.bmp # DirectX 11 Render-Ausgabe
├── gaming_msaa_4x.bmp          # 4x MSAA Kantenglättung Ausgabe
├── gaming_fxaa.bmp             # FXAA Postprocessing Ausgabe
├── gaming_hdr_bloom_aces.bmp   # HDR Bloom + ACES Tonemapping Ausgabe
├── gaming_aliased_no_aa.bmp    # Unbereinigte Baseline Ausgabe
├── blender_software_gpu_render.bmp # Blender Render Engine Ausgabe
├── software_gpu_sphere.bmp     # 3D Kugel mit 800 Dreiecken
├── software_gpu_blurred.bmp    # Gauß-Weichzeichner Filter Ausgabe
├── software_gpu_sobel.bmp      # Sobel-Kantenerkennung Ausgabe
├── software_gpu_render.bmp     # 3D Würfel mit Glanzlicht
│
└── software_gpu/               # Kern-Paket
    ├── core/                   # VirtualGPU, VRAM-Manager, VPS-Governor
    ├── compute/                # SIMT-Executor, @cuda_kernel, Tiled GEMM
    ├── directx/                # DirectX 11 (ID3D11Device, SwapChain)
    ├── graphics/               # Rasterizer, Shader, MSAA, FXAA, HDR Bloom
    ├── mobile/                 # Android UDS, Abstract Sockets, GLES3
    ├── network/                # HTTP REST, Binary TCP, Dispatcher
    ├── clients/                # Python, C, C++, C#, JS, Rust, Go Clients
    ├── integrations/           # MMORPG, Blender, Image Editor
    ├── redirector/             # Drop-in CUDA-Runtime & Task-Interceptor
    ├── benchmarks/             # Load Stress Benchmark, GFLOPS-Messung
    ├── tests/                  # 22 automatisierte Unit- & Integrationstests
    └── docs/                   # ARCHITECTURE.md (Wissenschaftliche Dokumentation)
```
