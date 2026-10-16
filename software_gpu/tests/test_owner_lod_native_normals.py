"""Pure offline tests of exact-geometry, source-bound GLB native PBR admission."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np
from tools.owner_lod_native_normals import NativeLodError, repair_lod, inspect_lod


def simple_glb(*, include_normal=False, malformed_index=False, degenerate=False,
               extension=False, skin=False, encoding=5126):
    """Real standalone glTF2 binary, never a fake parser return."""
    vertices = np.array([[0, 0, 0], [1, 0, 0],
                         [0, 0, 0] if degenerate else [0, 1, 0]], dtype='<f4')
    uvs = np.array([[0, 0], [1, 0], [0, 1]], dtype='<f4')
    faces = np.array([0, 1, 8 if malformed_index else 2], dtype='<u4')
    buf = bytearray()
    views = []
    accessors = []

    def add(value, component_type, kind):
        buf.extend(b'\0' * (-len(buf) % 4))
        offset = len(buf)
        raw = value.tobytes()
        buf.extend(raw)
        views.append(dict(buffer=0, byteOffset=offset, byteLength=len(raw)))
        accessors.append(dict(bufferView=len(views)-1,
                              componentType=component_type, count=len(value), type=kind))
        return len(accessors)-1

    pos = add(vertices, encoding, 'VEC3')
    uv = add(uvs, 5126, 'VEC2')
    attrs = {'POSITION': pos, 'TEXCOORD_0': uv}
    if include_normal:
        attrs['NORMAL'] = add(np.tile([0, 0, 1], (3, 1)).astype('<f4'), 5126, 'VEC3')
    idx = add(faces, 5125, 'SCALAR')
    # The binary bytes are a sentinel: append must leave all original image,
    # material, UV and geometry view bytes unchanged.
    image = b'FAKEPNG-CONTENT-SENTINEL'
    buf.extend(image)
    views.append(dict(buffer=0, byteOffset=len(buf)-len(image), byteLength=len(image)))
    doc = dict(asset={'version': '2.0'}, buffers=[{'byteLength': len(buf)}],
               bufferViews=views, accessors=accessors,
               images=[dict(bufferView=len(views)-1, mimeType='image/png')],
               materials=[dict(doubleSided=True, pbrMetallicRoughness=dict(baseColorFactor=[1, 1, 1, 1]))],
               meshes=[{'primitives': [dict(attributes=attrs, indices=idx, material=0)]}],
               nodes=[{'mesh': 0}], scenes=[{'nodes': [0]}], scene=0)
    if extension:
        doc['extensionsRequired'] = ['EXT_untrusted']
    if skin:
        doc['skins'] = [{'joints': [0]}]
    buf.extend(b'\0' * (-len(buf) % 4))
    json_bytes = json.dumps(doc, separators=(',', ':')).encode()
    json_bytes += b' ' * (-len(json_bytes) % 4)
    return b''.join((struct.pack('<4sII', b'glTF', 2, 28 + len(json_bytes) + len(buf)),
                     struct.pack('<I4s', len(json_bytes), b'JSON'), json_bytes,
                     struct.pack('<I4s', len(buf), b'BIN\0'), buf))


class TestOwnerLodNativeNormals(unittest.TestCase):
    def test_missing_normals_is_a_real_pbr_blocker_and_repaired(self):
        original = simple_glb()
        with self.assertRaisesRegex(NativeLodError, 'NATIVE_LOD_MISSING_NORMAL'):
            inspect_lod(original, pbr=True)
        fixed, receipt = repair_lod(original, hashlib.sha256(original).hexdigest())
        parsed = inspect_lod(fixed, pbr=True)
        self.assertEqual(1, parsed['triangles'])
        self.assertEqual(3, parsed['vertices'])
        self.assertEqual(receipt['before_sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(receipt['after_sha256'], hashlib.sha256(fixed).hexdigest())
        self.assertEqual('generated-area-weighted-normals', receipt['operation'])
        self.assertEqual(1, len(parsed['materials']))
        self.assertEqual(1, len(parsed['images']))

    def test_preserves_prior_bin_payload_material_uv_and_image_views(self):
        original = simple_glb()
        fixed, _ = repair_lod(original, hashlib.sha256(original).hexdigest())
        prior = inspect_lod(original, pbr=False, include_parts=True)
        post = inspect_lod(fixed, pbr=True, include_parts=True)
        self.assertEqual(prior['bin_payload'], post['bin_payload'][:len(prior['bin_payload'])])
        self.assertEqual(prior['doc']['materials'], post['doc']['materials'])
        self.assertEqual(prior['doc']['images'], post['doc']['images'])
        self.assertEqual(prior['doc']['bufferViews'], post['doc']['bufferViews'][:-1])
        self.assertEqual(prior['doc']['accessors'], post['doc']['accessors'][:-1])
        self.assertEqual(prior['doc']['meshes'][0]['primitives'][0]['attributes']['POSITION'],
                         post['doc']['meshes'][0]['primitives'][0]['attributes']['POSITION'])
        self.assertEqual(prior['doc']['meshes'][0]['primitives'][0]['attributes']['TEXCOORD_0'],
                         post['doc']['meshes'][0]['primitives'][0]['attributes']['TEXCOORD_0'])
        self.assertEqual(prior['doc']['meshes'][0]['primitives'][0]['indices'],
                         post['doc']['meshes'][0]['primitives'][0]['indices'])

    def test_generated_normals_have_nonzero_unit_length(self):
        raw = simple_glb()
        fixed, _ = repair_lod(raw, hashlib.sha256(raw).hexdigest())
        parsed = inspect_lod(fixed, pbr=True, include_parts=True)
        attr = parsed['doc']['meshes'][0]['primitives'][0]['attributes']['NORMAL']
        accessor = parsed['doc']['accessors'][attr]
        view = parsed['doc']['bufferViews'][accessor['bufferView']]
        offset = view['byteOffset'] + accessor.get('byteOffset', 0)
        normals = np.frombuffer(parsed['bin_payload'], '<f4', count=9, offset=offset).reshape(3, 3)
        np.testing.assert_allclose(normals, [[0, 0, 1]] * 3, atol=1e-6)
        np.testing.assert_allclose(np.linalg.norm(normals, axis=1), np.ones(3), atol=1e-6)

    def test_wrong_source_hash_or_corrupt_header_fails_closed(self):
        raw = simple_glb()
        with self.assertRaisesRegex(NativeLodError, 'NATIVE_LOD_SOURCE_SHA'):
            repair_lod(raw, '0' * 64)
        with self.assertRaises(NativeLodError):
            inspect_lod(b'BAD' + raw[3:], pbr=False)
        with self.assertRaises(NativeLodError):
            inspect_lod(raw[:-20], pbr=False)

    def test_rejects_unsupported_geometry_and_broken_topology(self):
        for kind, raw in [('has_normals', simple_glb(include_normal=True)),
                          ('bad_index', simple_glb(malformed_index=True)),
                          ('degenerate', simple_glb(degenerate=True)),
                          ('extensions', simple_glb(extension=True)),
                          ('skin', simple_glb(skin=True)),
                          ('wrong_position_type', simple_glb(encoding=5125))]:
            with self.subTest(kind=kind), self.assertRaises(NativeLodError):
                repair_lod(raw, hashlib.sha256(raw).hexdigest())

    def test_deterministic_bytes_and_identical_receipts(self):
        raw = simple_glb()
        a, ra = repair_lod(raw, hashlib.sha256(raw).hexdigest())
        b, rb = repair_lod(raw, hashlib.sha256(raw).hexdigest())
        self.assertEqual(a, b)
        self.assertEqual(ra, rb)

    def test_static_no_network_and_only_explicit_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / 'source.glb'
            src.write_bytes(simple_glb())
            target = Path(folder) / 'native.glb'
            from tools.owner_lod_native_normals import convert_file
            result = convert_file(src, target, hashlib.sha256(src.read_bytes()).hexdigest())
            self.assertEqual(result['after_sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertEqual(src.read_bytes(), simple_glb())


if __name__ == '__main__':
    unittest.main()
