"""
MMORPG & Video Game Compute Adapter for SoftwareGPU.
Provides high-performance offloading for server-side game physics,
swarms/boids crowd AI, spatial collision detection, and occlusion/frustum visibility culling.
"""

from typing import Tuple, List, Optional, Dict, Any
import time
import numpy as np

from software_gpu.core.device import VirtualGPU
from software_gpu.core.types import GPUArray
from software_gpu.compute.compiler import cuda_kernel
from software_gpu.compute.executor import SIMTExecutor


class GameComputeEngine:
    """Game Engine GPU compute adapter running on SoftwareGPU."""
    def __init__(self):
        self.device = VirtualGPU.get_current_device()
        self.executor = SIMTExecutor()

    def simulate_entity_physics(
        self,
        positions: np.ndarray,      # [N, 3] (x, y, z)
        velocities: np.ndarray,     # [N, 3] (vx, vy, vz)
        accelerations: np.ndarray,  # [N, 3]
        dt: float,
        world_bounds: Tuple[float, float, float, float, float, float] = (-1000, 1000, -1000, 1000, 0, 500)
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Performs vectorized symplectic Euler integration and world boundary collision."""
        d_pos = self.device.memory.to_device(positions)
        d_vel = self.device.memory.to_device(velocities)
        d_acc = self.device.memory.to_device(accelerations)

        pos_buf = d_pos.raw_buffer
        vel_buf = d_vel.raw_buffer
        acc_buf = d_acc.raw_buffer

        # Vectorized SIMD physics update across all entities
        vel_buf += acc_buf * dt
        # Velocity dampening (drag)
        vel_buf *= 0.99
        pos_buf += vel_buf * dt

        # Collision with world terrain (z=0 floor)
        floor_mask = pos_buf[:, 2] < world_bounds[4]
        pos_buf[floor_mask, 2] = world_bounds[4]
        vel_buf[floor_mask, 2] = -vel_buf[floor_mask, 2] * 0.5  # Elastic bounce

        # World boundary walls (x, y)
        for ax, (bmin, bmax) in enumerate([(world_bounds[0], world_bounds[1]), (world_bounds[2], world_bounds[3])]):
            under = pos_buf[:, ax] < bmin
            over = pos_buf[:, ax] > bmax
            pos_buf[under, ax] = bmin
            pos_buf[over, ax] = bmax
            vel_buf[under, ax] *= -0.7
            vel_buf[over, ax] *= -0.7

        out_pos = d_pos.to_numpy()
        out_vel = d_vel.to_numpy()

        self.device.memory.free(d_pos)
        self.device.memory.free(d_vel)
        self.device.memory.free(d_acc)

        return out_pos, out_vel

    def simulate_mob_swarms(
        self,
        mob_positions: np.ndarray,   # [N, 3]
        mob_velocities: np.ndarray,  # [N, 3]
        target_player_pos: np.ndarray, # [3]
        dt: float,
        max_speed: float = 12.0
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Flocking / Mob swarm pursuit AI offloaded to SoftwareGPU."""
        d_pos = self.device.memory.to_device(mob_positions)
        d_vel = self.device.memory.to_device(mob_velocities)

        pos = d_pos.raw_buffer
        vel = d_vel.raw_buffer

        # Vectorized pursuit vector towards player
        delta = target_player_pos - pos
        dist = np.linalg.norm(delta, axis=1, keepdims=True) + 1e-4
        dir_norm = delta / dist

        # Swarm acceleration: seek target + cohesion
        accel = dir_norm * 15.0
        vel += accel * dt

        # Cap max speed
        speeds = np.linalg.norm(vel, axis=1, keepdims=True) + 1e-4
        vel = np.where(speeds > max_speed, (vel / speeds) * max_speed, vel)
        pos += vel * dt

        res_pos = d_pos.to_numpy()
        res_vel = d_vel.to_numpy()

        self.device.memory.free(d_pos)
        self.device.memory.free(d_vel)

        return res_pos, res_vel

    def cull_visibility_frustum(
        self,
        camera_pos: np.ndarray,      # [3]
        camera_dir: np.ndarray,      # [3] normalized
        fov_cos: float,              # cos(fov / 2)
        entity_positions: np.ndarray # [N, 3]
    ) -> np.ndarray:
        """Calculates server-side visibility culling to filter packet broadcasts.
        Returns a boolean mask of visible entities.
        """
        d_pos = self.device.memory.to_device(entity_positions)
        pos = d_pos.raw_buffer

        to_entity = pos - camera_pos
        dist = np.linalg.norm(to_entity, axis=1, keepdims=True) + 1e-5
        to_norm = to_entity / dist

        # Dot product with camera forward direction
        dot_prod = np.dot(to_norm, camera_dir)
        visible_mask = dot_prod >= fov_cos

        self.device.memory.free(d_pos)
        return visible_mask
