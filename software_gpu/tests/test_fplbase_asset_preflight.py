"""Isolated synthetic FlatBuffer fixtures; not production/runtime evidence."""
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from tools.fplbase_asset_preflight import PreflightError, inspect_asset


def put(blob, offset, fmt, *values):
    struct.pack_into('<' + fmt, blob, offset, *values)


def make_mesh(material='materials/character.fplmat', *, version=1, malformed=False):
    """Hand-built FlatBuffer wire fixture for schema fields 0, 1, 2 and 15."""
    blob = bytearray(320)
    put(blob, 0, 'I', 40)
    blob[4:8] = b'FMSH'
    put(blob, 280, 'HHH', 36, 16, 4)
    put(blob, 280 + 4 + 15 * 2, 'H', 12)
    put(blob, 40, 'iIIH', -240, 36, 0, version)
    put(blob, 80, 'II', 1, 36)
    put(blob, 104, 'HHHHH', 10, 16, 4, 8, 0)
    put(blob, 120, 'iIII', 16, 60, 72, 0)
    put(blob, 184, 'IHHH', 3, 0, 1, 2)
    data = material.encode('utf-8')
    put(blob, 200, 'I', len(data))
    blob[204:204+len(data)] = data
    blob[204+len(data)] = 0
    if malformed:
        put(blob, 84, 'I', 0xFFFFFFFF)
    return bytes(blob)


def make_material(textures=('textures/skin.png',)):
    blob = bytearray(600)
    put(blob, 0, 'I', 40)
    blob[4:8] = b'FMAT'
    put(blob, 20, 'HHH', 6, 8, 4)
    put(blob, 40, 'iI', 20, 36)
    put(blob, 80, 'I', len(textures))
    offset = 120
    for i, name in enumerate(textures):
        slot = 84 + 4 * i
        put(blob, slot, 'I', offset - slot)
        b = name.encode('utf-8')
        put(blob, offset, 'I', len(b))
        blob[offset+4:offset+4+len(b)] = b
        blob[offset+4+len(b)] = 0
        offset += len(b) + 16
    return bytes(blob[:max(100, offset)])


class FplbasePreflightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'materials').mkdir()
        (self.root / 'textures').mkdir()
        self.mesh = self.root / 'character.fplmesh'
        self.mat = self.root / 'materials/character.fplmat'
        self.texture = self.root / 'textures/skin.png'
        self.mesh.write_bytes(make_mesh())
        self.mat.write_bytes(make_material())
        self.texture.write_bytes(b'not-a-real-image; resolver verifies bytes only')

    def check_error(self, error):
        with self.assertRaises(PreflightError) as ctx:
            inspect_asset(self.root, 'character.fplmesh')
        self.assertEqual(str(ctx.exception), error)

    def test_resolve_material_texture_sha_provenance(self):
        first = inspect_asset(self.root, 'character.fplmesh')
        self.assertEqual(first['protocol'], 'are.fplbase-preflight.v1')
        self.assertEqual(first['authority'], 'offline-derived')
        self.assertEqual(first['mesh']['path'], 'character.fplmesh')
        self.assertEqual(first['mesh']['sha256'], hashlib.sha256(self.mesh.read_bytes()).hexdigest())
        self.assertEqual([m['path'] for m in first['materials']], ['materials/character.fplmat'])
        self.assertEqual([t['path'] for t in first['textures']], ['textures/skin.png'])
        self.assertEqual(first['textures'][0]['sha256'], hashlib.sha256(self.texture.read_bytes()).hexdigest())
        self.assertEqual(first, inspect_asset(self.root, 'character.fplmesh'))
        self.assertEqual(first, json.loads(json.dumps(first, sort_keys=True)))

    def test_file_magic_rejected(self):
        self.mesh.write_bytes(b'bad!' + self.mesh.read_bytes()[4:])
        self.check_error('FPLBASE_ROOT_INVALID')

    def test_identifier_rejected(self):
        blob = bytearray(self.mesh.read_bytes())
        blob[4:8] = b'FMAT'
        self.mesh.write_bytes(blob)
        self.check_error('FPLBASE_IDENTIFIER_INVALID')

    def test_out_of_bounds_uoffset_rejected(self):
        self.mesh.write_bytes(make_mesh(malformed=True))
        self.check_error('FPLBASE_OFFSET_INVALID')

    def test_missing_material_rejected(self):
        self.mat.unlink()
        self.check_error('FPLBASE_FILE_MISSING')

    def test_missing_texture_rejected(self):
        self.texture.unlink()
        self.check_error('FPLBASE_FILE_MISSING')

    def test_traversal_material_rejected(self):
        self.mesh.write_bytes(make_mesh('../unsafe.fplmat'))
        self.check_error('FPLBASE_PATH_INVALID')

    def test_absolute_material_rejected(self):
        self.mesh.write_bytes(make_mesh('/tmp/unsafe.fplmat'))
        self.check_error('FPLBASE_PATH_INVALID')

    def test_traversal_texture_rejected(self):
        self.mat.write_bytes(make_material(('../unsafe.png',)))
        self.check_error('FPLBASE_PATH_INVALID')

    def test_symlink_escape_rejected(self):
        self.texture.unlink()
        outside = self.root.parent / ('outside-' + self.root.name)
        outside.write_bytes(b'secret')
        self.addCleanup(outside.unlink, True)
        self.texture.symlink_to(outside)
        self.check_error('FPLBASE_PATH_INVALID')

    def test_duplicate_material_reference_is_deterministic(self):
        self.mat.write_bytes(make_material(('textures/skin.png', 'textures/skin.png')))
        doc = inspect_asset(self.root, 'character.fplmesh')
        self.assertEqual(len(doc['textures']), 1)

    def test_unrecognized_mesh_version_rejected(self):
        self.mesh.write_bytes(make_mesh(version=2))
        self.check_error('FPLBASE_MESH_VERSION_UNSUPPORTED')

    def test_input_file_is_not_rewritten(self):
        before = (self.mesh.read_bytes(), self.mat.read_bytes(), self.texture.read_bytes())
        inspect_asset(self.root, 'character.fplmesh')
        self.assertEqual(before, (self.mesh.read_bytes(), self.mat.read_bytes(), self.texture.read_bytes()))


class PreflightBoundaryCoverage(unittest.TestCase):
    def setUp(self):
        self.inner = FplbasePreflightTest('test_resolve_material_texture_sha_provenance')
        self.inner.setUp()
        self.addCleanup(self.inner.doCleanups)
        self.root = self.inner.root
        self.mesh = self.inner.mesh
        self.mat = self.inner.mat

    def test_invalid_field_offset(self):
        data = bytearray(self.mesh.read_bytes())
        put(data, 284, 'H', 1)
        self.mesh.write_bytes(data)
        with self.assertRaisesRegex(PreflightError, 'FPLBASE_FIELD_INVALID'):
            inspect_asset(self.root, 'character.fplmesh')

    def test_required_surface(self):
        data = bytearray(self.mesh.read_bytes())
        put(data, 284, 'H', 0)
        self.mesh.write_bytes(data)
        with self.assertRaisesRegex(PreflightError, 'FPLBASE_REQUIRED_FIELD'):
            inspect_asset(self.root, 'character.fplmesh')

    def test_utf8_name_invalid(self):
        data = bytearray(self.mat.read_bytes())
        data[124] = 0xff
        self.mat.write_bytes(data)
        with self.assertRaisesRegex(PreflightError, 'FPLBASE_STRING_ENCODING_INVALID'):
            inspect_asset(self.root, 'character.fplmesh')

    def test_cli_success_output_file(self):
        from tools.fplbase_asset_preflight import main
        out = self.root / 'report.json'
        self.assertEqual(main(['--root', str(self.root), '--mesh', 'character.fplmesh', '--output', str(out)]), 0)
        self.assertEqual(json.loads(out.read_text())['protocol'], 'are.fplbase-preflight.v1')

    def test_cli_stdout(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from tools.fplbase_asset_preflight import main
        buf = StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(['--root', str(self.root), '--mesh', 'character.fplmesh']), 0)
        self.assertEqual(json.loads(buf.getvalue())['mesh']['path'], 'character.fplmesh')

    def test_cli_rejects(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from tools.fplbase_asset_preflight import main
        buf = StringIO()
        with redirect_stderr(buf):
            self.assertEqual(main(['--root', str(self.root), '--mesh', 'missing.fplmesh']), 2)
        self.assertIn('FPLBASE_PREFLIGHT_REJECTED', buf.getvalue())

    def test_bad_asset_dir(self):
        with self.assertRaises((NotADirectoryError, PreflightError)):
            inspect_asset(self.mesh, 'character.fplmesh')

    def test_texture_extension_rejected(self):
        self.mat.write_bytes(make_material(('textures/rogue.py',)))
        with self.assertRaisesRegex(PreflightError, 'FPLBASE_TEXTURE_EXTENSION_INVALID'):
            inspect_asset(self.root, 'character.fplmesh')


if __name__ == '__main__':
    unittest.main()
