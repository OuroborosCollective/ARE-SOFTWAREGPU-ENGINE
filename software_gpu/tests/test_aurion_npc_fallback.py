"""NPC fallback fixtures: real manifest validation and negative GLB-byte checks."""
from pathlib import Path
import json
import tempfile
import unittest

from software_gpu.integrations.aurion.npc_fallback_audit import (
    read_manifest, load_original, _digest, EXPECTED_ANIMATIONS, SLOTS
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "fixtures" / "aurion" / "npc_fallback" / "manifest.json"


class TestNpcFallback(unittest.TestCase):
    def test_ten_pinned_originals_and_rig_clips(self):
        doc = read_manifest(MANIFEST)
        self.assertEqual(len(doc["families"]), 5)
        self.assertEqual(doc["skin_joint_count"], 65)
        self.assertEqual(doc["animation_names"], list(EXPECTED_ANIMATIONS))
        self.assertEqual(doc["expected_explicit_equipment_slot_names"], list(SLOTS))
        self.assertFalse(doc["originals_available_in_actions"])
        for item in doc["families"]:
            self.assertEqual([x["lod"] for x in item["lods"]], [0, 1])
            self.assertLess(item["lods"][1]["triangles"], item["lods"][0]["triangles"])
            self.assertEqual(len(item["animation_stream_sha256"]),64)
            self.assertEqual(len(item["rig_structure_sha256"]),64)
        named = [i["name"] for i in doc["families"] if i["explicit_equipment_slots"]]
        self.assertEqual(named,["Base_Male","Reference_Female_SimpleParted","Reference_Male_SimpleParted"])
        self.assertEqual(sum(len(i["lods"]) for i in doc["families"]),10)

    def test_fake_additional_lod_is_not_permitted(self):
        doc = read_manifest(MANIFEST)
        doc["families"][0]["lods"][1]["lod"]=2
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"manifest.json"
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError,"LOD_PAIR_INVALID"):
                read_manifest(path)

    def test_unavailable_original_must_not_count_as_pass(self):
        doc = read_manifest(MANIFEST)
        with tempfile.TemporaryDirectory() as tmp:
            item=doc["families"][0]["lods"][0]
            with self.assertRaisesRegex(ValueError,"SOURCE_SIZE_OR_FILE_INVALID"):
                load_original(Path(tmp)/item["file"],item)
            fake=Path(tmp)/item["file"]
            fake.write_bytes(b"x"*item["bytes"])
            with self.assertRaisesRegex(ValueError,"SOURCE_HASH_MISMATCH"):
                load_original(fake,item)

    def test_manifest_fail_closed_for_path_traversal(self):
        doc=read_manifest(MANIFEST)
        doc["families"][0]["lods"][0]["file"]="../../sneaky.glb"
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"manifest.json"
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError,"MANIFEST_FILE_INVALID"):
                read_manifest(path)

    def test_receipt_digest_stable(self):
        obj={"z":3,"a":[1,2]}
        self.assertEqual(_digest(obj),_digest({"a":[1,2],"z":3}))


if __name__ == "__main__":
    unittest.main()
