import unittest
import numpy as np

class TestGeometryAreaParity(unittest.TestCase):
    def test_area_calculation_parity(self):
        F = 100
        width = 800
        height = 600
        fpos = np.random.rand(F, 3, 4)
        w = fpos[..., 3]
        inv_w = 1.0 / w
        ndc = fpos[..., :3] * inv_w[..., None]

        sx = (ndc[..., 0] + 1.0) * 0.5 * width
        sy = (1.0 - ndc[..., 1]) * 0.5 * height

        # Old area calculation
        screen_old = np.stack([sx, sy, ndc[..., 2]], axis=-1).astype(np.float32)
        area_old = ((screen_old[:, 2, 0] - screen_old[:, 0, 0]) * (screen_old[:, 1, 1] - screen_old[:, 0, 1])
                - (screen_old[:, 2, 1] - screen_old[:, 0, 1]) * (screen_old[:, 1, 0] - screen_old[:, 0, 0]))

        # New area calculation
        sx32 = sx.astype(np.float32)
        sy32 = sy.astype(np.float32)
        area_new = ((sx32[:, 2] - sx32[:, 0]) * (sy32[:, 1] - sy32[:, 0])
                - (sy32[:, 2] - sy32[:, 0]) * (sx32[:, 1] - sx32[:, 0]))

        np.testing.assert_array_equal(area_old, area_new, err_msg="Area calculation does not maintain byte parity")

if __name__ == '__main__':
    unittest.main()
