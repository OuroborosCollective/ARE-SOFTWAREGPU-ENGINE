"""Read-only validation of the eight owner-confirmed production male GLB fixtures."""
import json
from pathlib import Path
import tempfile
import unittest

from software_gpu.integrations.aurion.npc_fallback_audit import load_original, accessor

MANIFEST = Path(__file__).resolve().parents[2] / "fixtures/aurion/npc_production_male/manifest.json"


def check_manifest(path=MANIFEST):
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("protocol") != "are.aurion.production-male-fixtures.v1" or doc.get("authority") != "offline-read-only":
        raise ValueError("PRODUCTION_MANIFEST_INVALID")
    if doc.get("physical_to_logical_lod") != {"1": 0, "2": 1, "3": 2, "4": 3}:
        raise ValueError("LOD_MAPPING_INVALID")
    if len(doc.get("families", [])) != 2:
        raise ValueError("FAMILY_COUNT_INVALID")
    for family in doc["families"]:
        if [x["physical_lod"] for x in family["lods"]] != [1, 2, 3, 4]:
            raise ValueError("PHYSICAL_LOD_INVALID")
        if [x["logical_lod"] for x in family["lods"]] != [0, 1, 2, 3]:
            raise ValueError("LOGICAL_LOD_INVALID")
        if not all(x["file"].startswith(family["displayName"] + " - LOD") for x in family["lods"]):
            raise ValueError("SOURCE_NAME_INVALID")
        if not all(len(x["sha256"]) == 64 and int(x["sha256"], 16) >= 0 for x in family["lods"]):
            raise ValueError("SOURCE_HASH_INVALID")
        if not all(family["lods"][i]["triangles"] > family["lods"][i + 1]["triangles"] for i in range(3)):
            raise ValueError("NOT_REDUCING_GEOMETRY")
        if [x["texture_max_dimension"] for x in family["lods"]] != [1024, 512, 256, 128]:
            raise ValueError("TEXTURE_LOD_INVALID")
    return doc


class TestMaleProductionFixtures(unittest.TestCase):
    def test_complete_two_families_four_real_lods(self):
        doc = check_manifest()
        self.assertEqual(len({x["sha256"] for f in doc["families"] for x in f["lods"]}), 8)
        self.assertEqual(doc["live_deployment_status"], "UNVERIFIED_REQUIRES_APPROVED_RUNTIME_CATALOG_SHA_READBACK")
        self.assertFalse(doc["originals_available_in_github_ci"])

    def test_fail_closed_on_invented_fifth_lod(self):
        doc = check_manifest()
        doc["families"][0]["lods"].append({**doc["families"][0]["lods"][-1], "physical_lod": 5})
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "manifest.json"
            p.write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PHYSICAL_LOD_INVALID"):
                check_manifest(p)

    def test_no_mock_binary_substitute(self):
        doc = check_manifest()
        entry = doc["families"][0]["lods"][0]
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / entry["file"]
            with self.assertRaisesRegex(ValueError, "SOURCE_SIZE_OR_FILE_INVALID"):
                load_original(missing, entry={"bytes":entry["bytes"], "sha256":entry["sha256"]})
            missing.write_bytes(b"x" * entry["bytes"])
            with self.assertRaisesRegex(ValueError, "SOURCE_HASH_MISMATCH"):
                load_original(missing, entry={"bytes":entry["bytes"], "sha256":entry["sha256"]})


if __name__ == "__main__":
    unittest.main()
