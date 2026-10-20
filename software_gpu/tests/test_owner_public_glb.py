"""SHA admission negative contract tests; originals are optional."""
import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from tools.owner_public_glb_audit import verify

class TestOwnerPublicGLB(unittest.TestCase):
    def test_tiny_actual_glb_and_fail_closed_mutations(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/"fixture.glb"
            payload=json.dumps({"asset":{"version":"2.0"},"meshes":[{"primitives":[{"attributes":{"POSITION":0},"indices":1}]}],"accessors":[{"count":3},{"count":3}]},separators=(",",":")).encode()
            payload+=b" "*((-len(payload))%4)
            binbytes=b"\0"*12
            raw=struct.pack("<4sII",b"glTF",2,28+len(payload)+len(binbytes))+struct.pack("<I4s",len(payload),b"JSON")+payload+struct.pack("<I4s",len(binbytes),b"BIN\0")+binbytes
            file.write_bytes(raw)
            entry={"alias":"fixture","bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"vertices":3,"triangles":1,"animation_clips":0,"skin_joints":0}
            self.assertTrue(verify(file,entry)["verified"])
            with self.assertRaisesRegex(ValueError,"OWNER_SOURCE_HASH"):
                verify(file,{**entry,"sha256":"0"*64})
            with self.assertRaisesRegex(ValueError,"OWNER_SOURCE_SIZE"):
                verify(file,{**entry,"bytes":len(raw)+1})
            with self.assertRaisesRegex(ValueError,"OWNER_GLB_GEOMETRY"):
                verify(file,{**entry,"triangles":2})
            file.write_bytes(b"BAD!"+raw[4:])
            with self.assertRaisesRegex(ValueError,"OWNER_SOURCE_HASH"):
                verify(file,entry)
            damaged={**entry,"sha256":hashlib.sha256(file.read_bytes()).hexdigest()}
            with self.assertRaisesRegex(ValueError,"OWNER_GLB_HEADER"):
                verify(file,damaged)

if __name__=="__main__":unittest.main()
