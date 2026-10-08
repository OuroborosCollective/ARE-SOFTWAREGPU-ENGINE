"""CPU-only regression for returned swarm velocity and displacement."""
import unittest

import numpy as np

from software_gpu.integrations.mmorpg.game_compute_adapter import GameComputeEngine


class TestSwarmVelocity(unittest.TestCase):
    def test_capped_velocity_matches_displacement(self):
        engine = GameComputeEngine()
        positions = np.array([[0., 0., 0.], [1., 0., 0.]], dtype=np.float32)
        velocities = np.array([[500., 0., 0.], [-500., 0., 0.]], dtype=np.float32)
        target = np.array([10., 0., 0.], dtype=np.float32)
        delta_time = 0.1
        limit = 12.0

        updated_positions, updated_velocities = engine.simulate_mob_swarms(
            positions, velocities, target, delta_time, limit
        )
        self.assertTrue(
            np.all(np.linalg.norm(updated_velocities, axis=1) <= limit + 1e-4)
        )
        np.testing.assert_allclose(
            updated_positions, positions + updated_velocities * delta_time,
            rtol=1e-5, atol=1e-5,
        )
        np.testing.assert_array_equal(
            velocities,
            np.array([[500., 0., 0.], [-500., 0., 0.]], dtype=np.float32),
        )

    def test_empty_swarm(self):
        engine = GameComputeEngine()
        updated_positions, updated_velocities = engine.simulate_mob_swarms(
            np.empty((0, 3), dtype=np.float32),
            np.empty((0, 3), dtype=np.float32),
            np.zeros(3, dtype=np.float32),
            0.1, 12.0,
        )
        self.assertEqual(updated_positions.shape, (0, 3))
        self.assertEqual(updated_velocities.shape, (0, 3))


if __name__ == "__main__":
    unittest.main()
