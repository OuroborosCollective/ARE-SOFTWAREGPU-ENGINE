"""Synthetic offline reference only; real Wolfram rendering not asserted."""
import json
import tempfile
import unittest
from pathlib import Path
from scripts.wolfram_multiview import generate, make_script


class MultiviewReferenceTest(unittest.TestCase):
    def setUp(self):
        self.mesh = {'schema':'are.offline-mesh.v1','source_revision':'a'*40,
                     'vertices':[[0,0,0],[1,0,0],[0,1,0]],'triangles':[[0,1,2]]}

    def test_script_is_pinned_and_static(self):
        script = make_script(self.mesh, '/tmp/preview.png')
        self.assertIn('ResourceVersion -> "1.0.0"', script)
        self.assertIn('"ThreeView"', script)
        self.assertIn('"CameraInteraction" -> None', script)
        self.assertIn('faces = {{1,2,3}}', script)

    def test_invalid_inputs_fail_closed(self):
        for changed in ({'source_revision':'main'}, {'triangles':[[0,0,1]]},
                        {'triangles':[[0,1,3]]}, {'vertices':[[0,0,float('nan')]]},
                        {'schema':'invalid'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                make_script({**self.mesh, **changed}, '/tmp/out.png')

    def test_script_receipt_is_not_render_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            source=folder/'mesh.json'; source.write_text(json.dumps(self.mesh))
            output=folder/'view.wl'; png=folder/'image.png'
            receipt=generate(source, output, png)
            self.assertEqual(receipt['status'], 'SCRIPT_ONLY_UNRENDERED')
            self.assertFalse(png.exists())
            self.assertTrue(output.exists())
            self.assertEqual(json.loads((folder/'view.wl.receipt.json').read_text()), receipt)
            with self.assertRaises(FileExistsError):
                generate(source, output, png)

if __name__ == '__main__':
    unittest.main()
