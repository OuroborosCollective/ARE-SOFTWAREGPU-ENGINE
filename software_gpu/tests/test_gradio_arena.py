"""Real offline render and fail-closed UI input regression tests."""
import os
from unittest import TestCase, mock

from plugins.gradio_arena.app import BACKENDS, execute, main, make_job


class TestGradioArena(TestCase):
    def test_bounded_job_keeps_offline_authority(self):
        job = make_job(686.0, 64, "tiles")
        self.assertEqual(job["authority"], "offline-read-only")
        self.assertEqual(job["render"]["repeats"], 3)
        self.assertEqual(job["budget"]["memory_mb"], 2048)
        self.assertEqual(job["fixture"]["kind"], "procedural")
        self.assertEqual(job["fixture"]["seed"], 686)

    def test_bad_controls_cannot_spawn_a_worker(self):
        invalid = ((True,128,"tiles"), (-1,128,"tiles"), (2**31,128,"tiles"),
                   (1.5,128,"tiles"), (0,1024,"tiles"), (0,True,"tiles"),
                   (0,128,"native-cpp"), (0,128,"tiles-jit"))
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                make_job(*args)

    def test_authentication_is_mandatory(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SystemExit, "SET_ARE_GRADIO_USER"):
                main()
        with mock.patch.dict(os.environ,
                             {"ARE_GRADIO_USER":"test","ARE_GRADIO_PASSWORD":"short"},
                             clear=True):
            with self.assertRaisesRegex(SystemExit, "SET_ARE_GRADIO_USER"):
                main()

    def test_real_cpu_render_and_sha_readback(self):
        image, receipt = execute(686, 64, "tiles")
        self.assertEqual(image.size, (64,64))
        self.assertEqual(receipt["authority"], "offline-read-only")
        self.assertEqual(receipt["errors"], [])
        self.assertTrue(receipt["outcome"]["repeat_byte_identical"])
        self.assertEqual(receipt["outcome"]["repeats"], 3)
        self.assertGreater(receipt["outcome"]["covered_pixels"], 0)
        self.assertEqual(len(receipt["outcome"]["image_bmp_sha256"]), 64)
