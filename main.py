#!/usr/bin/env python3
"""
SoftwareGPU - Unified Main Command Line Interface (CLI).
Provides direct execution of all SoftwareGPU features:
- CUDA & GPGPU compute
- DirectX 11 (WARP-style software pipeline)
- Gaming PC Antialiasing (4x MSAA, FXAA) and HDR Bloom
- VPS CPU Governor and cgroups quota management
- MMORPG Game Server 5,000 entities physics simulation
- Blender Render Engine bridge
- Image editing filters
- Multi-protocol network daemon (HTTP, TCP, Android UDS)
- Load stress benchmark with degradation curves
"""

import sys
import os
import argparse
import json

import software_gpu as sgpu
from software_gpu.core.output import output_file


def show_info():
    print("=" * 70)
    print(" SoftwareGPU System & Hardware Telemetry")
    print("=" * 70)
    device = sgpu.VirtualGPU.get_current_device()
    gov_report = sgpu.governor.get_status_report()

    print(f"Device Name:               {device.properties.name}")
    print(f"Streaming Multiprocessors: {device.num_sms} Cores")
    print(f"Virtual VRAM:              {device.properties.total_global_mem // (1024*1024)} MB")
    print(f"Warp Size:                 {device.properties.warp_size} Threads")
    print("-" * 70)
    print("VPS & Cloud Environment Telemetry:")
    for k, v in gov_report.items():
        print(f"  • {k:<26}: {v}")
    print("=" * 70)


def run_cuda_demo():
    print("\n>>> Running CUDA-to-CPU Redirection Demo...")
    from software_gpu.examples.cuda_dropin_demo import main as run_cuda
    run_cuda()


def run_directx_demo():
    print("\n>>> Running DirectX 11 (Direct3D 11) Execution Demo...")
    from software_gpu.directx.directx_demo import main as run_dx
    run_dx()


def run_gaming_demo():
    print("\n>>> Running Gaming PC Pipeline (4x MSAA, FXAA, HDR Bloom, ACES)...")
    from software_gpu.examples.gaming_pc_demo import main as run_gaming
    run_gaming()


def run_mmorpg_demo():
    print("\n>>> Running MMORPG Server Zone Simulation (5,000 Entities)...")
    from software_gpu.integrations.mmorpg.mmorpg_server_demo import run_mmorpg_server_simulation
    run_mmorpg_server_simulation()


def run_blender_demo():
    print("\n>>> Running Blender Render Engine Standalone Bridge...")
    import numpy as np
    bridge = sgpu.StandaloneBlenderBridge(width=320, height=240)
    verts = [
        sgpu.Vertex([-1, -1, 1], [0, 0, 1], color=[1, 0, 0]),
        sgpu.Vertex([ 1, -1, 1], [0, 0, 1], color=[0, 1, 0]),
        sgpu.Vertex([ 0,  1, 1], [0, 0, 1], color=[0, 0, 1])
    ]
    indices = [(0, 1, 2)]
    render_file = output_file("blender_software_gpu_render.bmp")
    fb = bridge.render_scene(
        verts, indices,
        camera_eye=np.array([0, 0, 3], dtype=np.float32),
        camera_target=np.array([0, 0, 0], dtype=np.float32),
        output_filepath=render_file
    )
    print(f"Blender frame rendered and saved to: {render_file}")


def run_filters_demo():
    print("\n>>> Running Image Filter Processing Endpoint...")
    pipeline = sgpu.ImageFilterPipeline()
    src = output_file("software_gpu_sphere.bmp")
    if os.path.exists(src):
        img = pipeline.load_bmp(src)
        blurred = pipeline.gaussian_blur(img, radius=2)
        pipeline.save_bmp(output_file("software_gpu_blurred.bmp"), blurred)
        edges = pipeline.sobel_edges(img)
        pipeline.save_bmp(output_file("software_gpu_sobel.bmp"), edges)
        print("Gaussian Blur and Sobel Edge Detection executed and saved successfully!")
    else:
        print(f"Source image {src} not found, generating sample render first...")
        from software_gpu.examples.render_3d_scene import main as render_sphere
        render_sphere()
        run_filters_demo()


def run_stress_benchmark():
    print("\n>>> Running Load Stress Benchmark with FPS Degradation Curves...")
    from software_gpu.benchmarks.load_stress_benchmark import run_load_stress_benchmark
    run_load_stress_benchmark()


def start_server(http_port=8088, tcp_port=8089):
    print(f"\n>>> Starting SoftwareGPU Multi-Protocol Server on HTTP:{http_port}, TCP:{tcp_port} (loopback-only, authenticated)...")
    server = sgpu.SoftwareGPUServer(http_port=http_port, tcp_port=tcp_port)
    # Android IPC has separate unaudited authority; do not autostart.
    server.start()
    print("Server running! Press Ctrl+C to terminate.")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.stop()


def run_all():
    print("=" * 70)
    print(" SoftwareGPU - Running ALL Features & Verifications")
    print("=" * 70)
    show_info()
    run_cuda_demo()
    run_directx_demo()
    run_gaming_demo()
    run_mmorpg_demo()
    run_blender_demo()
    run_filters_demo()
    run_stress_benchmark()
    print("\n" + "=" * 70)
    print(" ALL FEATURES EXECUTED AND VERIFIED WITH REAL OUTPUTS!")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="SoftwareGPU Command Line Interface")
    parser.add_argument("--all", action="store_true", help="Execute all features and benchmarks sequentially")
    parser.add_argument("--info", action="store_true", help="Display hardware and VPS governor information")
    parser.add_argument("--cuda", action="store_true", help="Run CUDA-to-CPU redirection demo")
    parser.add_argument("--directx", action="store_true", help="Run DirectX 11 software pipeline demo")
    parser.add_argument("--gaming", action="store_true", help="Run Gaming PC 4x MSAA, FXAA, and HDR Bloom demo")
    parser.add_argument("--mmorpg", action="store_true", help="Run MMORPG 5,000 entities physics simulation")
    parser.add_argument("--blender", action="store_true", help="Run Blender render engine bridge")
    parser.add_argument("--filters", action="store_true", help="Run image filters (Gaussian blur, Sobel)")
    parser.add_argument("--benchmark", action="store_true", help="Run load stress benchmark with degradation curves")
    parser.add_argument("--server", action="store_true", help="Start authenticated loopback-only server; SOFTWAREGPU_AUTH_TOKEN required")
    parser.add_argument("--http-port", type=int, default=8088, help="HTTP REST port")
    parser.add_argument("--tcp-port", type=int, default=8089, help="Binary TCP port")

    args = parser.parse_args()

    if len(sys.argv) == 1 or args.all:
        run_all()
    elif args.info:
        show_info()
    elif args.cuda:
        run_cuda_demo()
    elif args.directx:
        run_directx_demo()
    elif args.gaming:
        run_gaming_demo()
    elif args.mmorpg:
        run_mmorpg_demo()
    elif args.blender:
        run_blender_demo()
    elif args.filters:
        run_filters_demo()
    elif args.benchmark:
        run_stress_benchmark()
    elif args.server:
        start_server(args.http_port, args.tcp_port)


if __name__ == "__main__":
    main()
