"""Opt-in, offline KTX2/BasisU -> PNG-GLB admission for existing AREMDL03 PBR.

No native raster or material semantics change. The only decoder is a pinned,
real Khronos `ktx` executable; missing or wrong version fails closed. No URIs.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

MAGIC = b'\xabKTX 20\xbb\r\n\x1a\n'
GLB = b'glTF'
PROTOCOL = 'are.ktx2-basisu-offline-admission.v1'
MAX_GLB_BYTES = 256 * 1024 * 1024
MAX_ENCODED_KTX = 64 * 1024 * 1024
MAX_SOURCE_LICENSE = 64 * 1024
SLOTS = {'baseColorTexture': 'srgb', 'emissiveTexture': 'srgb',
         'metallicRoughnessTexture': 'linear', 'normalTexture': 'linear',
         'occlusionTexture': 'linear'}
REQUIRED_BUDGET = {'max_dimension', 'max_pixels', 'max_texture_bytes',
                   'max_lod_bytes', 'max_mip_bytes'}


def _need(test, code):
    if not test:
        raise ValueError(code)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _valid_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _unique_object(pairs):
    result = {}
    for k, v in pairs:
        _need(k not in result, 'KTX2_JSON_DUPLICATE')
        result[k] = v
    return result


def _budget(budget):
    _need(isinstance(budget, dict) and set(budget) == REQUIRED_BUDGET,
          'KTX2_BUDGET_FIELDS')
    for k, limit in {'max_dimension': 4096, 'max_pixels': 4096**2,
                     'max_texture_bytes': 64 * 1024 * 1024,
                     'max_lod_bytes': 128 * 1024 * 1024,
                     'max_mip_bytes': 64 * 1024 * 1024}.items():
        _need(type(budget[k]) is int and 1 <= budget[k] <= limit,
              'KTX2_BUDGET_VALUE')
    return budget


def _kvd(raw, offset, length):
    if not length:
        _need(offset == 0, 'KTX2_KVD_INDEX')
        return {}
    _need(length <= 8192 and offset % 4 == 0, 'KTX2_KVD_BUDGET')
    keys = {}
    cursor, end = offset, offset + length
    while cursor < end:
        _need(cursor + 4 <= end, 'KTX2_KVD_TRUNCATED')
        size, = struct.unpack_from('<I', raw, cursor)
        cursor += 4
        _need(size >= 2 and cursor + size <= end, 'KTX2_KVD_RANGE')
        data = raw[cursor:cursor + size]
        cursor += size
        cursor += (-cursor) % 4
        _need(cursor <= end and b'\x00' in data, 'KTX2_KVD_RANGE')
        key, value = data.split(b'\x00', 1)
        _need(key in (b'KTXorientation', b'KTXwriter', b'KTXwriterScParams')
              and key not in keys, 'KTX2_KVD_UNSUPPORTED')
        keys[key] = value.rstrip(b'\x00')
    _need(cursor == end and keys.get(b'KTXorientation', b'rd') == b'rd',
          'KTX2_ORIENTATION')
    return keys


def inspect_ktx2(raw: bytes, budget: dict, expected_color_space: str) -> dict:
    """Validate complete bounded 2D ETC1S/UASTC framing, without decoding.

    Synthetic test vectors prove only input rejection, not BasisU rendering.
    """
    b = _budget(budget)
    _need(isinstance(raw, bytes) and len(raw) >= 104
          and len(raw) <= MAX_ENCODED_KTX, 'KTX2_SIZE')
    _need(raw[:12] == MAGIC, 'KTX2_MAGIC')
    values = struct.unpack_from('<12s13I2Q', raw, 0)
    (_, vk_format, type_size, width, height, depth, layers, faces, mip_count,
     scheme, dfd_at, dfd_len, kvd_at, kvd_len, sgd_at, sgd_len) = values
    _need(type_size == 1 and vk_format == 0 and faces == 1 and depth == 0
          and layers == 0, 'KTX2_2D_BASIS_ONLY')
    _need(1 <= width <= b['max_dimension'] and 1 <= height <= b['max_dimension'],
          'KTX2_DIMENSIONS')
    _need(width * height <= b['max_pixels'], 'KTX2_PIXELS')
    _need(1 <= mip_count <= min(13, max(width, height).bit_length()),
          'KTX2_MIP_COUNT')
    _need(scheme in (0, 1, 2), 'KTX2_SUPERCOMPRESSION')
    index_end = 80 + 24 * mip_count
    _need(index_end <= len(raw) and dfd_at >= index_end
          and dfd_len >= 24 and dfd_len <= 4096
          and dfd_at + dfd_len <= len(raw), 'KTX2_DFD_RANGE')
    _need(struct.unpack_from('<I', raw, dfd_at)[0] == dfd_len
          and 24 <= struct.unpack_from('<H', raw, dfd_at + 10)[0] <= dfd_len - 4,
          'KTX2_DFD')
    color_model = raw[dfd_at + 12]
    transfer = raw[dfd_at + 14]
    flags = raw[dfd_at + 15]
    _need((scheme == 1 and color_model == 163) or
          (scheme in (0, 2) and color_model == 166), 'KTX2_COLOR_MODEL')
    _need(flags == 0 and transfer in (1, 2), 'KTX2_DFD_TRANSFER')
    color_space = 'srgb' if transfer == 2 else 'linear'
    _need(expected_color_space in ('srgb', 'linear') and
          color_space == expected_color_space, 'KTX2_COLOR_SPACE')
    regions = [(0, index_end), (dfd_at, dfd_at + dfd_len)]
    if kvd_len:
        _need(kvd_at >= index_end and kvd_at + kvd_len <= len(raw),
              'KTX2_KVD_RANGE')
        regions.append((kvd_at, kvd_at + kvd_len))
    _kvd(raw, kvd_at, kvd_len)
    if sgd_len:
        _need(sgd_at >= index_end and sgd_at % 8 == 0
              and sgd_len <= 16 * 1024 * 1024
              and sgd_at + sgd_len <= len(raw), 'KTX2_SGD_RANGE')
        regions.append((sgd_at, sgd_at + sgd_len))
    else:
        _need(sgd_at == 0, 'KTX2_SGD_INDEX')
    _need((scheme == 1 and sgd_len > 0) or
          (scheme != 1 and sgd_len == 0), 'KTX2_SGD_REQUIREMENT')
    decoded_mips, encoded_mips = [], []
    for level in range(mip_count):
        at, size, uncompressed = struct.unpack_from('<QQQ', raw, 80 + level * 24)
        _need(size > 0 and at >= index_end and size <= MAX_ENCODED_KTX
              and at + size <= len(raw), 'KTX2_LEVEL_RANGE')
        expected_size = max(1, width >> level) * max(1, height >> level) * 4
        _need(expected_size <= b['max_mip_bytes'], 'KTX2_MIP_BUDGET')
        _need((scheme == 1 and uncompressed == 0) or
              (scheme == 0 and size == uncompressed) or
              (scheme == 2 and uncompressed > 0 and uncompressed <= MAX_ENCODED_KTX),
              'KTX2_UNCOMPRESSED_RANGE')
        decoded_mips.append(expected_size)
        encoded_mips.append(size)
        regions.append((at, at + size))
    sorted_regions = sorted(regions)
    _need(all(first[1] <= second[0] for first, second in
              zip(sorted_regions, sorted_regions[1:])), 'KTX2_MIP_OVERLAP')
    # Permit zero alignment padding, never arbitrary hidden/unindexed payloads.
    for (start_a, end_a), (start_b, end_b) in zip(sorted_regions, sorted_regions[1:]):
        gap = raw[end_a:start_b]
        _need(len(gap) <= 4096 and not any(gap), 'KTX2_UNINDEXED_BYTES')
    trailer = raw[sorted_regions[-1][1]:]
    _need(len(trailer) <= 7 and not any(trailer), 'KTX2_UNINDEXED_BYTES')
    _need(decoded_mips[0] <= b['max_texture_bytes'], 'KTX2_TEXTURE_BUDGET')
    _need(sum(decoded_mips) <= b['max_lod_bytes'], 'KTX2_LOD_BUDGET')
    return dict(dimensions=[width, height], mip_levels=mip_count,
                mip_decoded_bytes=decoded_mips, mip_encoded_bytes=encoded_mips,
                resident_level=0, resident_decoded_bytes=decoded_mips[0],
                mip_chain_decoded_bytes=sum(decoded_mips),
                compression='basis_lz_etc1s' if scheme == 1 else
                            'uastc_ldr_zstd' if scheme == 2 else 'uastc_ldr',
                color_space=color_space, source_sha256=_sha(raw),
                color_model=color_model, supercompression=scheme)


def _local_file(name, *, max_bytes, code):
    _need(isinstance(name, str) and name and '://' not in name and
          not name.startswith('file:'), code)
    path = Path(name)
    _need(path.is_absolute() and not path.is_symlink() and path.is_file()
          and 0 < path.stat().st_size <= max_bytes, code)
    return path


def _read_glb(raw):
    _need(len(raw) >= 32 and raw[:4] == GLB and
          struct.unpack_from('<II', raw, 4) == (2, len(raw)), 'KTX2_GLB_HEADER')
    offset, chunks = 12, []
    while offset < len(raw):
        _need(offset + 8 <= len(raw), 'KTX2_GLB_CHUNK')
        length, kind = struct.unpack_from('<I4s', raw, offset)
        offset += 8
        _need(length and length % 4 == 0 and offset + length <= len(raw),
              'KTX2_GLB_CHUNK')
        chunks.append((kind, raw[offset:offset + length]))
        offset += length
    _need(len(chunks) == 2 and chunks[0][0] == b'JSON'
          and chunks[1][0] == b'BIN\x00' and len(chunks[0][1]) <= 2 * 1024 * 1024,
          'KTX2_GLB_LAYOUT')
    doc = json.loads(chunks[0][1], object_pairs_hook=_unique_object,
                     parse_constant=lambda _: _need(False, 'KTX2_JSON_NONFINITE'))
    _need(doc.get('asset', {}).get('version') == '2.0' and
          len(doc.get('buffers', [])) == 1 and
          'uri' not in doc['buffers'][0], 'KTX2_GLB_ASSET')
    length = doc['buffers'][0]['byteLength']
    _need(type(length) is int and 1 <= length <= len(chunks[1][1])
          and len(chunks[1][1]) - length <= 3, 'KTX2_GLB_BUFFER')
    _need(set(doc.get('extensionsRequired', [])) <= {'KHR_texture_basisu'} and
          set(doc.get('extensionsUsed', [])) <= {'KHR_texture_basisu'},
          'KTX2_GLTF_EXTENSIONS')
    return doc, bytearray(chunks[1][1][:length])


def _byteview(doc, binary, index):
    views = doc.get('bufferViews', [])
    _need(type(index) is int and 0 <= index < len(views), 'KTX2_BUFFER_VIEW')
    view = views[index]
    offset, size = view.get('byteOffset', 0), view.get('byteLength')
    _need(type(offset) is int and type(size) is int and size > 0 and offset >= 0
          and view.get('buffer', 0) == 0 and offset + size <= len(binary),
          'KTX2_VIEW_RANGE')
    return bytes(binary[offset:offset + size])


def _texture_slots(doc):
    uses = {}
    for material in doc.get('materials', []):
        pbr = material.get('pbrMetallicRoughness', {})
        for slot, space in SLOTS.items():
            info = pbr.get(slot) if slot in ('baseColorTexture', 'metallicRoughnessTexture') else material.get(slot)
            if info is None:
                continue
            _need(isinstance(info, dict) and type(info.get('index')) is int
                  and not info.get('extensions') and info.get('texCoord', 0) == 0,
                  'KTX2_MATERIAL_REFERENCE')
            ti = info['index']
            _need(0 <= ti < len(doc.get('textures', [])), 'KTX2_TEXTURE_INDEX')
            t = doc['textures'][ti]
            e = t.get('extensions', {})
            if 'KHR_texture_basisu' in e:
                _need(set(e) == {'KHR_texture_basisu'} and
                      type(e['KHR_texture_basisu'].get('source')) is int,
                      'KTX2_TEXTURE_EXTENSION')
                ii = e['KHR_texture_basisu']['source']
                _need(0 <= ii < len(doc.get('images', [])), 'KTX2_IMAGE_INDEX')
                uses.setdefault(ii, set()).add(space)
    return uses


def _native_binary(settings):
    _need(isinstance(settings, dict) and set(settings) ==
          {'path', 'sha256', 'version'}, 'KTX2_TRANSCODER')
    path = _local_file(settings['path'], max_bytes=100 * 1024 * 1024,
                       code='KTX2_TRANSCODER_FILE')
    _need(_valid_sha(settings['sha256']) and _sha(path.read_bytes()) ==
          settings['sha256'], 'KTX2_TRANSCODER_SHA')
    _need(type(settings['version']) is str and
          re.fullmatch(r'\d+\.\d+\.\d+', settings['version']) is not None,
          'KTX2_TRANSCODER_VERSION')
    try:
        proc = subprocess.run([str(path), '--version'], capture_output=True,
                              timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('KTX2_TRANSCODER_VERSION') from exc
    version = (proc.stdout + proc.stderr).decode('utf-8', errors='replace').strip()
    token = re.escape(settings['version'])
    _need(proc.returncode == 0 and len(version) < 1024 and
          re.search(r'(?<![0-9.])' + token + r'(?![0-9.])', version) is not None,
          'KTX2_TRANSCODER_VERSION')
    return path, version


def _run_ktx(binary, command, source, output=None):
    cmd = [str(binary), command]
    if command == 'validate':
        cmd.extend(['--gltf-basisu', str(source)])
    else:
        cmd.extend(['--transcode', 'rgba8', '--level', '0', str(source), str(output)])
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('KTX2_TRANSCODER_EXECUTION') from exc
    _need(result.returncode == 0, 'KTX2_TRANSCODER_'+command.upper())


def _png_pixels(encoded, width, height, max_bytes):
    _need(0 < len(encoded) <= max_bytes, 'KTX2_OUTPUT_BUDGET')
    try:
        from PIL import Image
        with Image.open(io.BytesIO(encoded)) as png:
            _need(png.format == 'PNG' and png.size == (width, height),
                  'KTX2_PNG_DIMENSIONS')
            png.verify()
        with Image.open(io.BytesIO(encoded)) as png:
            rgba = png.convert('RGBA').tobytes()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('KTX2_PNG_DECODE') from exc
    _need(len(rgba) == width * height * 4, 'KTX2_RGBA_LENGTH')
    return _sha(rgba)


def convert_ktx2_glb(manifest: dict, output_dir: Path) -> dict:
    """Create a fresh SHA-bound PNG GLB from embedded KTX2 for the existing importer.

    File inputs are read only. Successful output needs a real ktx validate/extract.
    """
    _need(isinstance(manifest, dict) and set(manifest) ==
          {'source_glb', 'source_sha256', 'source_bytes', 'lod', 'images',
           'transcoder', 'budget'}, 'KTX2_MANIFEST')
    budget = _budget(manifest['budget'])
    _need(type(manifest['lod']) is str and
          re.fullmatch(r'[a-zA-Z0-9_-]{1,48}', manifest['lod']), 'KTX2_LOD')
    source = _local_file(manifest['source_glb'], max_bytes=MAX_GLB_BYTES,
                         code='KTX2_SOURCE_PATH')
    _need(_valid_sha(manifest['source_sha256']) and
          type(manifest['source_bytes']) is int and
          source.stat().st_size == manifest['source_bytes'], 'KTX2_SOURCE_IDENTITY')
    raw = source.read_bytes()
    _need(_sha(raw) == manifest['source_sha256'], 'KTX2_SOURCE_HASH')
    target = Path(output_dir)
    _need(not target.exists() and not target.is_symlink() and
          target.parent.is_dir(), 'KTX2_OUTPUT_PATH')
    doc, binary = _read_glb(raw)
    uses = _texture_slots(doc)
    _need(1 <= len(uses) <= 32 and isinstance(manifest['images'], list)
          and len(manifest['images']) == len(uses), 'KTX2_SOURCE_IMAGES')
    entries = {}
    for r in manifest['images']:
        _need(isinstance(r, dict) and set(r) == {'image_index', 'sha256',
              'license', 'license_path', 'license_sha256'} and
              type(r['image_index']) is int and r['image_index'] in uses and
              r['image_index'] not in entries and _valid_sha(r['sha256'])
              and _valid_sha(r['license_sha256']) and
              isinstance(r['license'], str) and re.fullmatch(r'[A-Za-z0-9.-]{2,80}', r['license']),
              'KTX2_IMAGE_LICENSE')
        license_file = _local_file(r['license_path'], max_bytes=MAX_SOURCE_LICENSE,
                                   code='KTX2_LICENSE_FILE')
        _need(_sha(license_file.read_bytes()) == r['license_sha256'],
              'KTX2_LICENSE_SHA')
        entries[r['image_index']] = r
    _need(set(entries) == set(uses), 'KTX2_IMAGE_LICENSE')
    metadata, decoded_total = {}, 0
    for ii, spaces in uses.items():
        _need(len(spaces) == 1, 'KTX2_COLOR_SPACE_AMBIGUOUS')
        image = doc['images'][ii]
        _need(isinstance(image, dict) and 'uri' not in image and
              image.get('mimeType') == 'image/ktx2', 'KTX2_EMBEDDED_ONLY')
        data = _byteview(doc, binary, image.get('bufferView'))
        _need(_sha(data) == entries[ii]['sha256'], 'KTX2_IMAGE_HASH')
        item = inspect_ktx2(data, budget, next(iter(spaces)))
        decoded_total += item['resident_decoded_bytes']
        _need(decoded_total <= budget['max_lod_bytes'], 'KTX2_LOD_BUDGET')
        metadata[ii] = dict(record=item, data=data)
    binary_exe, version = _native_binary(manifest['transcoder'])
    with tempfile.TemporaryDirectory(prefix='are-ktx2-', dir=target.parent) as scratch:
        temp = Path(scratch)
        receipts = []
        for ii in sorted(uses):
            item = metadata[ii]
            in_path = temp / f'input-{ii}.ktx2'
            out_path = temp / f'output-{ii}.png'
            in_path.write_bytes(item['data'])
            _run_ktx(binary_exe, 'validate', in_path)
            _run_ktx(binary_exe, 'extract', in_path, out_path)
            _need(out_path.is_file() and not out_path.is_symlink(), 'KTX2_OUTPUT_FILE')
            png = out_path.read_bytes()
            width, height = item['record']['dimensions']
            rgba_hash = _png_pixels(png, width, height, budget['max_texture_bytes'])
            while len(binary) % 4:
                binary.append(0)
            offset = len(binary)
            binary.extend(png)
            doc.setdefault('bufferViews', []).append(dict(buffer=0, byteOffset=offset,
                                                           byteLength=len(png)))
            doc['images'][ii] = {'bufferView': len(doc['bufferViews']) - 1,
                                 'mimeType': 'image/png'}
            receipts.append(dict(image_index=ii, original_image_sha256=entries[ii]['sha256'],
                                 image_license=entries[ii]['license'],
                                 license_evidence_sha256=entries[ii]['license_sha256'],
                                 transcoded_png_sha256=_sha(png), rgba8_sha256=rgba_hash,
                                 **item['record']))
        for t in doc.get('textures', []):
            ext = t.get('extensions', {}).get('KHR_texture_basisu')
            if ext:
                ii = ext['source']
                _need(ii in metadata, 'KTX2_TEXTURE_USAGE')
                t.pop('extensions')
                t['source'] = ii
        doc.pop('extensionsRequired', None)
        doc.pop('extensionsUsed', None)
        doc['buffers'][0]['byteLength'] = len(binary)
        encoded = _canonical(doc)
        encoded += b' ' * ((-len(encoded)) % 4)
        binary.extend(b'\x00' * ((-len(binary)) % 4))
        result = struct.pack('<4sII', GLB, 2, 12 + 8 + len(encoded) + 8 + len(binary))
        result += struct.pack('<I4s', len(encoded), b'JSON') + encoded
        result += struct.pack('<I4s', len(binary), b'BIN\x00') + binary
        _need(len(result) <= MAX_GLB_BYTES, 'KTX2_OUTPUT_BUDGET')
        output = temp / 'converted.glb'
        output.write_bytes(result)
        receipt = dict(protocol=PROTOCOL, lod=manifest['lod'],
                       source_glb_sha256=manifest['source_sha256'],
                       converted_glb_sha256=_sha(result),
                       material_json_sha256=_sha(_canonical(doc.get('materials', []))),
                       images=receipts, resident_lod_bytes=decoded_total,
                       texture_budget=budget,
                       transcoder=dict(name='Khronos KTX-Software ktx extract',
                                       binary_sha256=manifest['transcoder']['sha256'],
                                       version=version, target='rgba8'),
                       renderer_authority='unchanged_native_aremdl03_via_png_glb',
                       pbr_beauty_diff='not_measured_without_reference_render',
                       float32_depth_diff='not_measured_without_reference_render',
                       compressed_color_parity='not_claimed_lossy_basisu',
                       mip_residency=dict(resident_levels=[0], other_levels='not_loaded',
                                          streaming='not_implemented'),
                       source_uri_fetch='forbidden')
        (temp / 'receipt.json').write_bytes(
            json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False).encode('utf-8') + b'\n')
        _need(not target.exists(), 'KTX2_OUTPUT_PATH')
        # Move only the completed immutable payloads; not the temporary inputs.
        stage = temp / 'accepted'
        stage.mkdir()
        shutil.move(str(output), stage / 'converted.glb')
        shutil.move(str(temp / 'receipt.json'), stage / 'receipt.json')
        stage.rename(target)
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        path = args.manifest
        _need(not path.is_symlink() and path.is_file() and
              0 < path.stat().st_size <= 65536, 'KTX2_MANIFEST_FILE')
        doc = json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
        convert_ktx2_glb(doc, args.output_dir)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'KTX2_REJECTED:{exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
