import json
import tempfile
import unittest
from pathlib import Path
from scripts.wolfram_multiview import validate_mesh, build_script, generate
from scripts.miha_evidence_similarity import analyze, save_result

class WolframOfflineToolsTests(unittest.TestCase):
    def test_multiview_three_views_only_from_pinned_input(self):
        mesh = {"schema": "are.offline-mesh.v1", "source_revision": "a"*40,
                "vertices": [[0,0,0],[1,0,0],[0,1,0]], "triangles": [[0,1,2]]}
        script = build_script(validate_mesh(mesh), "/tmp/static.png")
        self.assertIn('ResourceVersion -> "1.0.0"', script)
        self.assertIn('"ThreeView"', script)
        self.assertIn('"CameraInteraction" -> None', script)
        with tempfile.TemporaryDirectory() as d:
            source = Path(d)/"mesh.json"; source.write_text(json.dumps(mesh))
            out = Path(d)/"view.wl"
            receipt = generate(source, out, Path(d)/"static.png")
            self.assertEqual(receipt["status"], "SCRIPT_ONLY_UNRENDERED")
            self.assertFalse((Path(d)/"static.png").exists())
            with self.assertRaises(FileExistsError):
                generate(source, out, Path(d)/"static.png")

    def test_multiview_invalid_geometry_rejected(self):
        mesh = {"schema":"are.offline-mesh.v1", "source_revision":"a"*40,
                "vertices":[[0,0,0],[1,0,0],[0,1,0]], "triangles":[[0,1,2]]}
        for override in ({"source_revision":"main"}, {"triangles":[[0,1,3]]},
                         {"triangles":[[1,1,2]]}):
            with self.assertRaises(ValueError):
                validate_mesh({**mesh, **override})

    def test_dice_exact_multisets_and_missing_comparisons(self):
        rows = [{"id":"a", "source_ids":["x","x","y"]},
                {"id":"b", "source_ids":["x","y","y"]},
                {"id":"c", "source_ids":[]}]
        data = {"schema":"miha.source-multisets.v1","dataset_revision":"b"*40,
                "records":rows}
        out = analyze(data, "c"*64)
        self.assertEqual(out["status"], "CANDIDATE_ONLY_NOT_PROOF")
        self.assertEqual(out["pairs"][0]["dice_dissimilarity"],"1/3")
        self.assertEqual(out["insufficient_evidence_pairs"],2)
        self.assertEqual(out["pairs"],analyze({**data, "records":list(reversed(rows))},"c"*64)["pairs"])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"receipt.json"; save_result(path,out)
            self.assertEqual(json.loads(path.read_text()),out)
            with self.assertRaises(FileExistsError): save_result(path,out)

    def test_unpinned_and_duplicate_miha_records_rejected(self):
        data={"schema":"miha.source-multisets.v1","dataset_revision":"main",
              "records":[{"id":"a","source_ids":[]},{"id":"a","source_ids":[]}]}
        with self.assertRaises(ValueError): analyze(data,"c"*64)
        data["dataset_revision"]="a"*40
        with self.assertRaises(ValueError): analyze(data,"c"*64)
