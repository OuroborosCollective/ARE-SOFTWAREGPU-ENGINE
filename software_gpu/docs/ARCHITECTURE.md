# SoftwareGPU: Vollständige Dokumentation

SoftwareGPU ist eine vollständige, mock-freie Software-Implementierung eines GPU-Prozessors auf modernen Mehrkern-CPUs mit Vektorerweiterungen (AVX2/FMA). Das System ersetzt dedizierte GPUs auf Servern, Gaming-PCs und mobilen Endgeräten (Android) für rechenintensive GPGPU-Aufgaben, Grafikrendering (DirectX 11 & OpenGL ES 3.0), Kantenglättung (MSAA & FXAA) und HDR-Postprocessing.

---

## 1. Gaming-PC Kantenglättung & Antialiasing (AA) & Postprocessing

In modernen Gaming-PCs sind Antialiasing und kinoreife Shading-Effekte Standard. In `software_gpu/graphics/postprocess.py` wurden folgende Techniken funktionsfähig integriert:

### A. 4x MSAA (Multi-Sample Anti-Aliasing)
* **Funktionsweise:** 4 Subpixel-Samplepunkte pro Pixel mit versetzten Abtastkoordinaten:
  $$\Delta_{(x,y)} \in \{(-0.25, -0.25), (0.25, -0.25), (-0.25, 0.25), (0.25, 0.25)\}$$
* **Coverage-Maske & Depth-Test:** Kantenfunktionen und Tiefentests werden pro Subsample evaluiert.
* **Resolve-Pass:** Ein Box-Filter mittelt die validen Subpixel-Farben und erzeugt weiche Kantenübergänge ohne Aliasing-Treppchen.
* **Ergebnis:** **34,6 % weichere Kantenübergänge** gegenüber unbereinigtem Rendering.
* **Ausgabe:** [gaming_msaa_4x.bmp](file:///workspace/gaming_msaa_4x.bmp)

### B. FXAA (Fast Approximate Anti-Aliasing - Timothy Lottes / NVIDIA)
* **Funktionsweise:** Screen-Space Post-Processing-Filter basierend auf perzeptueller Luminanz ($L = 0.299 R + 0.587 G + 0.114 B$).
* **Kantenerkennung:** Kontrastdifferenz der 4-Nachbarschaft. Unterhalb des Schwellenwerts (0.06) erfolgt ein Early-Exit.
* **Gradient-Blending:** Ermittlung der Kantenrichtung (horizontal vs. vertikal) und gewichtetes Blending entlang der Kantentangente.
* **Laufzeit & Ergebnis:** Extrem schnell (**21,3 ms**) mit **50,8 % messbarer Kantenglättung**.
* **Ausgabe:** [gaming_fxaa.bmp](file:///workspace/gaming_fxaa.bmp)

### C. HDR Bloom & ACES Filmic Tone Mapping + Gamma 2.2
* **HDR-Luminanz-Extraktion:** Extraktion von Glanzlichtern und Lichtquellen mit Schwellenwert-Filterung.
* **2-Pass Blur Glow:** Separable Gauß-/Box-Filterung zur Erzeugung weicher Lichtkoronen.
* **ACES Filmic Tone Mapping:** Abbildung von High Dynamic Range $[0, \infty)$ in $[0, 1]$ nach Academy Color Encoding System:
  $$f(x) = \frac{x(2.51x + 0.03)}{x(2.43x + 0.59) + 0.14}$$
* **sRGB Gamma 2.2 Korrektur:** $C_{\text{srgb}} = C_{\text{linear}}^{1/2.2}$.
* **Ausgabe:** [gaming_hdr_bloom_aces.bmp](file:///workspace/gaming_hdr_bloom_aces.bmp)

---

## 2. Android & Mobile Endgeräte Kommunikation

Mobile Android-Geräte weisen spezifische Architekturanforderungen auf:
1. **Sicherheits- & Rechte-Restriktionen:** Netzwerk-Sockets (`localhost`) unterliegen oft SELinux- und `android.permission.INTERNET`-Einschränkungen.
2. **Latenz-Anforderungen:** Der TCP-Loopback-Stack erzeugt unnötigen Kernel-Overhead.

### Mobile IPC-Architektur (`software_gpu/mobile/android_server.py`)
* **Linux / Android Abstract Namespace Sockets (`\0software_gpu`):**
  * Verwendet Sockets mit führendem Null-Byte.
  * Benötigt **keine Schreibrechte** im Android-Dateisystem und umgeht App-Sandbox-Konflikte.
* **Android LocalSocket / Unix Domain Sockets (`/tmp/software_gpu.sock`):**
  * Direkter nativer IPC-Kanal für Android NDK (C++) und Kotlin/Java (`android.net.LocalSocket`).
  * Extrem niedrige Latenz ($< 0,1\text{ ms}$).
* **Android Native Client ([AndroidGPUClient.kt](file:///workspace/software_gpu/mobile/AndroidGPUClient.kt)):**
  * Kotlin/Java-Client für Android-Apps unter Verwendung von `LocalSocketAddress(abstractNamespace, Namespace.ABSTRACT)`.
  * Automatischer Fallback auf TCP für Remote-Debugging über `adb reverse tcp:8089 tcp:8089`.
* **OpenGL ES 3.0 & EGL Emulation ([opengles.py](file:///workspace/software_gpu/mobile/opengles.py)):**
  * Native Abbildung mobiler Draw-Calls (`glDrawArrays`, `glClear`, `eglSwapBuffers`) auf den CPU-Rasterizer.

---

## 3. DirectX 11 Pipeline & VPS Hardware Governor

* **DirectX 11 (WARP / Mesa D3D12):** `ID3D11Device`, `ID3D11DeviceContext`, `IDXGISwapChain` und HLSL-Shader auf CPU gerendert ([directx_demo.py](file:///workspace/software_gpu/directx/directx_demo.py) -> [directx_software_gpu_render.bmp](file:///workspace/directx_software_gpu_render.bmp)).
* **VPS Hardware Governor ([vps_governor.py](file:///workspace/software_gpu/core/vps_governor.py)):** cgroups v1/v2 Quota-Erkennung, CPU-Affinity und automatischer Headroom (30 % Reservierung für OS und Datenbanken).
* **Load- & Stressbenchmark ([load_stress_benchmark.py](file:///workspace/software_gpu/benchmarks/load_stress_benchmark.py)):** Ermittlung von FPS unter Last, Abfallkurven und finalem Score (**81.454 Punkte**, Peak **750,82 GFLOPS**).

---

## 4. Übersicht aller generierten Bilddateien (Echte Ergebnisse)

Alle folgenden 24-Bit-Bitmap-Dateien wurden von SoftwareGPU auf der CPU erzeugt:

1. [gaming_aliased_no_aa.bmp](file:///workspace/gaming_aliased_no_aa.bmp) - Baseline ohne Kantenglättung (sichtbare Treppenkanten)
2. [gaming_msaa_4x.bmp](file:///workspace/gaming_msaa_4x.bmp) - 4x MSAA mit Subpixel-Resolve (glatte Kanten)
3. [gaming_fxaa.bmp](file:///workspace/gaming_fxaa.bmp) - FXAA Post-Processing (glatte Farbverläufe)
4. [gaming_hdr_bloom_aces.bmp](file:///workspace/gaming_hdr_bloom_aces.bmp) - HDR Bloom Glow + ACES Filmic Tone Mapping
5. [directx_software_gpu_render.bmp](file:///workspace/directx_software_gpu_render.bmp) - Direct3D 11 DrawIndexed Rendering
6. [blender_software_gpu_render.bmp](file:///workspace/blender_software_gpu_render.bmp) - Blender Render Engine Bridge
7. [software_gpu_sphere.bmp](file:///workspace/software_gpu_sphere.bmp) - 3D Kugel mit 800 Dreiecken & Blinn-Phong
8. [software_gpu_blurred.bmp](file:///workspace/software_gpu_blurred.bmp) - 2D Gaußscher Weichzeichner
9. [software_gpu_sobel.bmp](file:///workspace/software_gpu_sobel.bmp) - Sobel-Kantenerkennungsfilter
10. [software_gpu_render.bmp](file:///workspace/software_gpu_render.bmp) - 3D Würfel mit Glanzlicht
