"""Real GLB admission tests for vertex colors absent from the AREMDL03 layout."""
from pathlib import Path
import tempfile
import unittest

import numpy as np

from software_gpu.research.model_probe import (
    accessor, build_model_probe, load_asset, read_glb, run_model, write_scene,
)
from software_gpu.tests.fixtures.model_fixture import make_glb


def _with_color(component_type=5126, dimensions=3, semantic='COLOR_0'):
    """Add an embedded, valid glTF RGB/RGBA accessor containing blue vertices."""
    dtype, maximum = {5126: ('<f4', 1), 5121: ('<u1', 255),
                      5123: ('<u2', 65535)}[component_type]

    def mutate(doc, binary):
        attributes = doc['meshes'][0]['primitives'][0]['attributes']
        doc['accessors'][attributes['POSITION']].update(min=[1, 2, 3], max=[2, 3, 3])
        color = [0, 0, maximum] + ([maximum] if dimensions == 4 else [])
        rows = np.asarray([color] * 3, dtype=dtype)
        # glTF vertex attribute elements must each start on a 4-byte boundary.
        stride = (rows[0].nbytes + 3) // 4 * 4
        encoded = b''.join(row.tobytes() + b'\0' * (stride - row.nbytes) for row in rows)
        binary.extend(b'\0' * (-len(binary) % 4))
        offset = len(binary)
        binary.extend(encoded)
        doc['bufferViews'].append(dict(buffer=0, byteOffset=offset, byteLength=len(encoded),
                                       byteStride=stride))
        record = dict(bufferView=len(doc['bufferViews']) - 1, componentType=component_type,
                      count=3, type=f'VEC{dimensions}')
        if component_type != 5126:
            record['normalized'] = True
        doc['accessors'].append(record)
        attributes[semantic] = len(doc['accessors']) - 1
        doc['buffers'][0]['byteLength'] = len(binary)
    return mutate


class TestModelVertexColor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='are-model-vertex-color-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_pbr_rejects_valid_rgb_and_rgba_color_encodings(self):
        for component_type in (5126, 5121, 5123):
            for dimensions in (3, 4):
                with self.subTest(component_type=component_type, dimensions=dimensions):
                    source = self.root / 'colored.glb'
                    entry = make_glb(source, static=True, surface=True,
                                     mutate=_with_color(component_type, dimensions))
                    doc, binary = read_glb(source, entry['sha256'], entry['bytes'])
                    index = doc['meshes'][0]['primitives'][0]['attributes']['COLOR_0']
                    record = doc['accessors'][index]
                    view = doc['bufferViews'][record['bufferView']]
                    expected_stride = {(5126, 3): 12, (5126, 4): 16,
                                       (5121, 3): 4, (5121, 4): 4,
                                       (5123, 3): 8, (5123, 4): 8}[component_type, dimensions]
                    self.assertEqual(view['byteStride'], expected_stride)
                    self.assertEqual(record.get('byteOffset', 0) % 4, 0)
                    for vertex in range(record['count']):
                        self.assertEqual((view['byteOffset'] + record.get('byteOffset', 0)
                                          + vertex * view['byteStride']) % 4, 0)
                    blue = [0, 0, 1] + ([1] if dimensions == 4 else [])
                    np.testing.assert_array_equal(accessor(doc, binary, index), [blue] * 3)
                    with self.assertRaisesRegex(ValueError, '^MODEL_VERTEX_COLOR_SUBSET$'):
                        load_asset(source, entry, profile='pbr')

    def test_pbr_rejects_invalid_color_references_instead_of_importing(self):
        for reference in (999999, -1, True, None, '1'):
            with self.subTest(reference=reference):
                def mutate(doc, binary):
                    doc['meshes'][0]['primitives'][0]['attributes']['COLOR_0'] = reference
                source = self.root / 'invalid-color.glb'
                entry = make_glb(source, static=True, surface=True, mutate=mutate)
                with self.assertRaisesRegex(ValueError, '^MODEL_VERTEX_COLOR_SUBSET$'):
                    load_asset(source, entry, profile='pbr')

    def test_pbr_rejects_additional_color_semantics(self):
        source = self.root / 'additional-color.glb'
        entry = make_glb(source, static=True, surface=True, mutate=_with_color(semantic='COLOR_1'))
        with self.assertRaisesRegex(ValueError, '^MODEL_VERTEX_COLOR_SUBSET$'):
            load_asset(source, entry, profile='pbr')

    def test_rejected_import_does_not_replace_existing_scene(self):
        source = self.root / 'plain.glb'
        entry = make_glb(source, static=True, surface=True)
        plain = load_asset(source, entry, profile='pbr')
        target = self.root / 'scene.aremdl'
        write_scene(target, [dict(asset=plain, clip=None)], [0], 64, 16,
                    projection='perspective', render_profile='pbr')
        existing = target.read_bytes()
        entry = make_glb(source, static=True, surface=True, mutate=_with_color())
        with self.assertRaisesRegex(ValueError, '^MODEL_VERTEX_COLOR_SUBSET$'):
            asset = load_asset(source, entry, profile='pbr')
            write_scene(target, [dict(asset=asset, clip=None)], [0], 64, 16,
                        projection='perspective', render_profile='pbr')
        self.assertEqual(target.read_bytes(), existing)

    def test_native_uncolored_pbr_and_explicit_diagnostic_contract_remain(self):
        plain_path, color_path = self.root / 'plain.glb', self.root / 'blue.glb'
        plain_entry = make_glb(plain_path, static=True, surface=True)
        color_entry = make_glb(color_path, static=True, surface=True, mutate=_with_color())
        plain = load_asset(plain_path, plain_entry, profile='pbr')
        executable, _ = build_model_probe(self.root / 'native')
        request = self.root / 'pbr.aremdl'
        metadata = write_scene(request, [dict(asset=plain, clip=None)], [0], 64, 16,
                               projection='perspective', render_profile='pbr')
        self.assertEqual(metadata['protocol'], 'are.model-input.v3')
        self.assertEqual(request.read_bytes()[:8], b'AREMDL03')
        one = run_model(executable, request, workers=1, repeats=1, render_profile='pbr')
        four = run_model(executable, request, workers=4, repeats=1, render_profile='pbr')
        self.assertTrue(one['receipt']['full_buffer_parity'])
        self.assertTrue(four['receipt']['full_buffer_parity'])
        self.assertGreater(np.count_nonzero(one['frames'][0, :, :, :3]), 0)
        for key in ('frames', 'resolved', 'depth'):
            np.testing.assert_array_equal(one[key], four[key])

        # This profile deliberately uses instance diagnostic colors, not GLB materials.
        diagnostic_plain = load_asset(plain_path, plain_entry, profile='diagnostic')
        diagnostic_color = load_asset(color_path, color_entry, profile='diagnostic')
        for projection, magic in (('orthographic', b'AREMDL01'), ('perspective', b'AREMDL02')):
            with self.subTest(projection=projection):
                requests = []
                for name, asset in (('plain', diagnostic_plain), ('blue', diagnostic_color)):
                    path = self.root / f'{name}-{projection}.aremdl'
                    write_scene(path, [dict(asset=asset, clip=None)], [0], 64, 16,
                                projection=projection, render_profile='diagnostic')
                    requests.append(path)
                self.assertEqual(requests[0].read_bytes(), requests[1].read_bytes())
                self.assertEqual(requests[0].read_bytes()[:8], magic)
                outputs = [run_model(executable, path, workers=1, repeats=1) for path in requests]
                for key in ('frames', 'resolved', 'depth'):
                    np.testing.assert_array_equal(outputs[0][key], outputs[1][key])


if __name__ == '__main__':
    unittest.main()
