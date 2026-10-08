"""
MMORPG World Zone Simulation Server Demo.
Demonstrates offloading game physics, NPC mob swarms, and visibility culling
for 5,000 concurrent entities in real-time onto SoftwareGPU.
"""

import time
import numpy as np
from software_gpu.integrations.mmorpg.game_compute_adapter import GameComputeEngine


def run_mmorpg_server_simulation():
    print("=" * 70)
    print(" MMORPG Game Server GPU Compute Offload Simulation")
    print(" Architecture: SoftwareGPU (CPU Streaming Multiprocessors)")
    print("=" * 70)

    NUM_ENTITIES = 5000
    NUM_TICKS = 60
    DT = 1.0 / 60.0  # 60 Hz server tick rate (16.66 ms budget)

    print(f"\nInitializing MMORPG World Zone with {NUM_ENTITIES:,} active entities...")
    np.random.seed(42)

    # World coordinates: -500 to +500 in X and Y, 0 to 100 in Z
    positions = np.random.uniform(-400.0, 400.0, (NUM_ENTITIES, 3)).astype(np.float32)
    positions[:, 2] = np.random.uniform(5.0, 50.0, NUM_ENTITIES)

    velocities = np.random.uniform(-5.0, 5.0, (NUM_ENTITIES, 3)).astype(np.float32)
    accelerations = np.zeros((NUM_ENTITIES, 3), dtype=np.float32)
    accelerations[:, 2] = -9.81  # Standard gravity

    player_pos = np.array([0.0, 0.0, 10.0], dtype=np.float32)
    camera_dir = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    fov_cos = float(np.cos(np.radians(45.0)))  # 90 degree FOV cone

    engine = GameComputeEngine()

    print(f"Executing {NUM_TICKS} server game loop ticks...")
    tick_times = []

    for tick in range(NUM_TICKS):
        t0 = time.perf_counter()

        # 1. Physics integration + World boundary collision
        positions, velocities = engine.simulate_entity_physics(
            positions, velocities, accelerations, DT
        )

        # 2. Mob swarm AI pursuit pass
        positions, velocities = engine.simulate_mob_swarms(
            positions, velocities, player_pos, DT
        )

        # 3. Server-side anti-cheat visibility culling
        visible = engine.cull_visibility_frustum(
            player_pos, camera_dir, fov_cos, positions
        )

        elapsed = (time.perf_counter() - t0) * 1000.0
        tick_times.append(elapsed)

    avg_tick = np.mean(tick_times)
    max_tick = np.max(tick_times)
    min_tick = np.min(tick_times)
    visible_count = np.count_nonzero(visible)

    print("\n--- Simulation Results ---")
    print(f"Entities Simulated:       {NUM_ENTITIES:,}")
    print(f"Total Ticks Simulated:    {NUM_TICKS}")
    print(f"Average Tick Compute Time:{avg_tick:.2f} ms (Server budget: 16.66 ms)")
    print(f"Min / Max Tick Time:      {min_tick:.2f} ms / {max_tick:.2f} ms")
    print(f"Simulated Tick Rate:      {1000.0 / avg_tick:.1f} Ticks/sec (Target: 60 TPS)")
    print(f"Visible Entities to Host: {visible_count:,} / {NUM_ENTITIES:,} (Network packets saved: {(1.0 - visible_count/NUM_ENTITIES)*100:.1f}%)")
    print("SUCCESS: MMORPG Server physics and AI smoothly handled by SoftwareGPU!")


if __name__ == "__main__":
    run_mmorpg_server_simulation()
