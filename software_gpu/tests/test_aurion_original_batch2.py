"""Original-file SHA pinned, complete (two-level) Aurion fixture contracts."""
import json
from pathlib import Path
import unittest

from software_gpu.integrations.aurion.offline_lod_worker import read_manifest


class TestAurionOriginalBatch2(unittest.TestCase):
    def test_original_pairs_are_complete_with_two_lods(self):
        root=Path(__file__).resolve().parents[2]/"fixtures"/"aurion"
        cases={"arena_courtyard":([2781,1818],[4776,3233]),
               "fountain":([2132,1053],[2791,1698])}
        for family,(triangles,vertices) in cases.items():
            with self.subTest(family=family):
                path=root/family/"manifest.json"
                fixture=read_manifest(path)
                self.assertEqual(fixture["fixture_id"],family)
                self.assertEqual(fixture["available_lods"],[1,2])
                self.assertEqual(fixture["absence_of_other_lods"],"NOT_CREATED_NOT_REQUIRED")
                self.assertEqual([x["lod"] for x in fixture["lods"]],[1,2])
                self.assertEqual([x["triangles"] for x in fixture["lods"]],triangles)
                self.assertEqual([x["vertices"] for x in fixture["lods"]],vertices)
                self.assertTrue(all(len(x["source_sha256"])==64 for x in fixture["lods"]))
                self.assertLess(fixture["lods"][1]["triangles"],fixture["lods"][0]["triangles"])
                self.assertFalse(fixture["independent_reference"].get("pipeline","").startswith("ARE"))

    def test_extra_nonexistent_lod_rejected(self):
        root=Path(__file__).resolve().parents[2]/"fixtures"/"aurion"
        import tempfile
        for family in ("arena_courtyard","fountain"):
            doc=json.loads((root/family/"manifest.json").read_text())
            doc["lods"].append({**doc["lods"][-1],"lod":3})
            with tempfile.TemporaryDirectory() as tmp:
                manifest=Path(tmp)/"manifest.json"
                manifest.write_text(json.dumps(doc))
                with self.assertRaisesRegex(ValueError,"ONLY_ORIGINAL_LOD1_LOD2_EXIST"):
                    read_manifest(manifest)

    def test_street_lamp_four_lods_remain_supported(self):
        root=Path(__file__).resolve().parents[2]/"fixtures"/"aurion"
        doc=read_manifest(root/"street_lamp"/"manifest.json")
        self.assertEqual([x["lod"] for x in doc["lods"]],[0,1,2,3])


if __name__=="__main__":
    unittest.main()
