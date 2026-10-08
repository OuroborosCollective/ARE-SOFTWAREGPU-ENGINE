"""Real CPU raster + exact GLB binary parsing regression; no mocks."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from software_gpu.integrations.aurion.offline_lod_worker import (
    load_glb, read_manifest, render_lod, run_isolated,
)


def synthetic_glb():
    # A visible front-facing double-sided triangle in real glTF2 binary.
    v = np.array([[-.2, 0.1, 0], [.2, 0.1, 0], [0, 1.6, 0]], dtype="<f4")
    idx = np.array([0, 1, 2], dtype="<u2")
    binary = v.tobytes() + idx.tobytes() + b"\0\0"
    obj = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength":len(binary)}],
        "bufferViews":[
            {"buffer":0,"byteOffset":0,"byteLength":len(v.tobytes())},
            {"buffer":0,"byteOffset":len(v.tobytes()),"byteLength":len(idx.tobytes())}
        ],
        "accessors":[
            {"bufferView":0,"componentType":5126,"count":3,"type":"VEC3"},
            {"bufferView":1,"componentType":5123,"count":3,"type":"SCALAR"}
        ],
        "meshes":[{"primitives":[{"attributes":{"POSITION":0},"indices":1}]}],
        "nodes":[{"mesh":0}],
        "scenes":[{"nodes":[0]}],
        "scene":0
    }
    meta=json.dumps(obj,separators=(",",":")).encode()
    meta+=b" " *((-len(meta))%4)
    return (struct.pack("<4sII",b"glTF",2,12+8+len(meta)+8+len(binary))
            +struct.pack("<I4s",len(meta),b"JSON")+meta
            +struct.pack("<I4s",len(binary),b"BIN\0")+binary)


class TestAurionOffline(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.src=self.root/"Aurion_Street_Lamp_LOD0.glb"
        self.binary=synthetic_glb()
        self.src.write_bytes(self.binary)
        self.entry={
            "lod":0,"file":self.src.name,"bytes":len(self.binary),
            "source_sha256":hashlib.sha256(self.binary).hexdigest(),
            "vertices":3,"triangles":1,"meshes":1,"materials":0,"images":0,
        }
        self.camera={"yaw_degrees":0,"pitch_degrees":0,"center_y":.8,
                     "x_half_extent":.5,"y_half_extent":1}

    def test_real_glb_geometry_and_image_replay(self):
        verts,faces,digest=load_glb(self.src,self.entry)
        self.assertEqual(verts.shape,(3,3))
        self.assertEqual(faces.shape,(1,3))
        self.assertEqual(digest,self.entry["source_sha256"])
        result=render_lod(self.src,self.entry,self.camera,self.root/"out",pixels=96,repeats=2)
        self.assertTrue(result["repeat_byte_identical"])
        self.assertGreater(result["covered_pixels"],50)
        self.assertEqual((self.root/"out"/result["image_file"]).read_bytes()[:2],b"BM")
        self.assertEqual(len(result["samples"]),2)

    def test_isolated_worker_real_process(self):
        result=run_isolated(self.src,self.entry,self.camera,self.root/"worker",
                            pixels=64,repeats=2,timeout=25,memory_mb=3072)
        self.assertGreater(result["covered_pixels"],20)

    def test_wrong_hash_fails_closed(self):
        self.entry["source_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"SOURCE_SHA256_MISMATCH"):
            load_glb(self.src,self.entry)

    def test_truncated_and_malformed_glb_fail(self):
        for forged in (self.binary[:-2],b"FAIL"+self.binary[4:]):
            self.src.write_bytes(forged)
            self.entry["bytes"]=len(forged)
            self.entry["source_sha256"]=hashlib.sha256(forged).hexdigest()
            with self.assertRaises(ValueError):
                load_glb(self.src,self.entry)

    def test_limits(self):
        with self.assertRaisesRegex(ValueError,"PIXEL_BUDGET_INVALID"):
            run_isolated(self.src,self.entry,self.camera,self.root,pixels=1024)
        with self.assertRaisesRegex(ValueError,"RESOURCE_BUDGET_INVALID"):
            run_isolated(self.src,self.entry,self.camera,self.root,memory_mb=99999)

    def test_pinned_original_fixture_manifest(self):
        repo=Path(__file__).resolve().parents[2]
        fixture=read_manifest(repo/"fixtures/aurion/street_lamp/manifest.json")
        self.assertEqual(len(fixture["lods"]),4)
        self.assertEqual([x["triangles"] for x in fixture["lods"]],
                         [4172,3128,2086,1042])
        self.assertEqual(len(set(x["source_sha256"] for x in fixture["lods"])),4)


if __name__=="__main__":
    unittest.main()
