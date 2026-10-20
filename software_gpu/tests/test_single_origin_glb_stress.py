"""A generated real, indexed GLB with 28,800 nondegenerate triangles.

GLB model-raster stress and time-window pulse are separate offline paths:
this test does NOT claim production GLB pulse compositing or owner-mask wiring.
"""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from software_gpu.research.model_probe import (
    build_model_probe, load_asset, run_model, write_scene,
)


def make_grid_glb(path, segments=120):
    """Construct valid glTF2 BIN-backed POSITION and indices, never a fake model."""
    vertices=[]
    for y in range(segments+1):
        for x in range(segments+1):
            xx=2.*x/segments-1.
            yy=2.*y/segments-1.
            vertices.append((xx, yy, .08*float(np.sin(7*xx)*np.cos(5*yy))))
    positions=np.asarray(vertices,dtype="<f4")
    indices=[]
    for y in range(segments):
        for x in range(segments):
            a=y*(segments+1)+x
            indices.extend((a,a+1,a+segments+1,
                            a+1,a+segments+2,a+segments+1))
    faces=np.asarray(indices,dtype="<u4")
    binary=positions.tobytes()+faces.tobytes()
    pos_bytes=positions.nbytes
    doc={
        "asset":{"version":"2.0"},
        "buffers":[{"byteLength":len(binary)}],
        "bufferViews":[
            {"buffer":0,"byteOffset":0,"byteLength":pos_bytes},
            {"buffer":0,"byteOffset":pos_bytes,"byteLength":faces.nbytes}
        ],
        "accessors":[
            {"bufferView":0,"componentType":5126,"count":len(positions),"type":"VEC3"},
            {"bufferView":1,"componentType":5125,"count":len(faces),"type":"SCALAR"}
        ],
        "materials":[{"doubleSided":True}],
        "meshes":[{"primitives":[{"attributes":{"POSITION":0},"indices":1,"material":0}]}],
        "nodes":[{"mesh":0,"matrix":np.eye(4).reshape(-1).tolist()}],
        "scenes":[{"nodes":[0]}],"scene":0,
    }
    encoded=json.dumps(doc,separators=(",",":")).encode()
    encoded+=b" "*((-len(encoded))%4)
    header=struct.pack("<4sII",b"glTF",2,28+len(encoded)+len(binary))
    raw=header+struct.pack("<I4s",len(encoded),b"JSON")+encoded
    raw+=struct.pack("<I4s",len(binary),b"BIN\0")+binary
    Path(path).write_bytes(raw)
    return {"file":Path(path).name,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}


class TestSingleOriginGlbStress(unittest.TestCase):
    def test_real_28800_triangle_glb_admitted_and_rendered_by_native_workers(self):
        with tempfile.TemporaryDirectory(prefix="are-wave-glb-stress-") as temp:
            root=Path(temp)
            source=root/"grid-28800.glb"
            entry=make_grid_glb(source)
            asset=load_asset(source,entry)
            self.assertEqual(len(asset["faces"]),28800)
            self.assertEqual(len(asset["positions"]),14641)
            self.assertEqual(len(set(map(tuple,asset["faces"][:100]))),100)
            request=root/"scene.aremdl"
            write_scene(request,[{"asset":asset,"clip":None}],[0.,0.],
                        pixels=128,tile=32,render_profile="diagnostic")
            executable,build=build_model_probe(root/"native")
            self.assertFalse(build["python_in_runtime"])
            first=run_model(executable,request,workers=1,repeats=2,timeout=180)
            parallel=run_model(executable,request,workers=4,repeats=2,timeout=180)
            np.testing.assert_array_equal(first["frames"],parallel["frames"])
            np.testing.assert_array_equal(first["resolved"],parallel["resolved"])
            np.testing.assert_array_equal(first["depth"],parallel["depth"])
            self.assertTrue(parallel["receipt"]["full_buffer_parity"])
            self.assertFalse(parallel["receipt"]["hardware_gpu_submitted"])
            self.assertEqual(parallel["receipt"]["triangles"],28800)
            self.assertGreater(sum(parallel["receipt"]["sample_writes"]),0)
            self.assertEqual(parallel["receipt"]["frame_sha256"][0],
                             parallel["receipt"]["frame_sha256"][1])
            self.assertEqual(parallel["receipt"]["frame_sha256"],
                             first["receipt"]["frame_sha256"])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                             entry["sha256"])


if __name__=="__main__":
    unittest.main()
