"""Strict offline decoder for the AREMDL03 opaque glTF metallic-roughness subset."""
from __future__ import annotations
import io
from pathlib import Path
import numpy as np

MAX_IMAGE_DIMENSION = 4096
MAX_ASSET_DECODED_BYTES = 128 * 1024 * 1024
WRAPS = (10497, 33071, 33648)
MAGS = (9728, 9729)
MINS = (9728, 9729, 9984, 9985, 9986, 9987)


def _need(ok, code):
    if not ok:
        raise ValueError(code)


def _array(value, size, code, low=-1e12, high=1e12):
    a = np.asarray(value, dtype='<f8')
    _need(a.shape == (size,) and np.isfinite(a).all() and (a >= low).all() and (a <= high).all(), code)
    return a


def _image_bytes(doc, binary, image_index):
    images = doc.get('images', [])
    _need(isinstance(images, list) and 0 <= image_index < len(images), 'MODEL_IMAGE_INDEX')
    image = images[image_index]
    _need(isinstance(image, dict) and 'uri' not in image and 'bufferView' in image,
          'MODEL_EXTERNAL_IMAGE')
    mime = image.get('mimeType')
    _need(mime in ('image/png', 'image/jpeg'), 'MODEL_IMAGE_MIME')
    views = doc.get('bufferViews', [])
    vi = image['bufferView']
    _need(type(vi) is int and 0 <= vi < len(views), 'MODEL_IMAGE_BUFFER_VIEW')
    view = views[vi]
    _need(view.get('buffer', 0) == 0, 'MODEL_IMAGE_BUFFER')
    offset, length = view.get('byteOffset', 0), view.get('byteLength')
    _need(type(offset) is int and type(length) is int and offset >= 0 and length > 0
          and offset + length <= len(binary), 'MODEL_IMAGE_BOUNDS')
    return bytes(binary[offset:offset + length]), mime


def _decode_image(encoded, mime):
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError('MODEL_PBR_PILLOW_REQUIRED:install software_gpu[model-pbr]') from exc
    try:
        with Image.open(io.BytesIO(encoded)) as image:
            fmt = image.format
            width, height = image.size
            _need((mime, fmt) in (('image/png', 'PNG'), ('image/jpeg', 'JPEG')),
                  'MODEL_IMAGE_FORMAT')
            _need(1 <= width <= MAX_IMAGE_DIMENSION and 1 <= height <= MAX_IMAGE_DIMENSION
                  and width * height <= MAX_IMAGE_DIMENSION * MAX_IMAGE_DIMENSION,
                  'MODEL_IMAGE_DIMENSIONS')
            image.verify()  # validates PNG chunks/CRC and JPEG structure before full decode
        with Image.open(io.BytesIO(encoded)) as image:
            rgba = np.asarray(image.convert('RGBA'), dtype=np.uint8).copy()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('MODEL_IMAGE_DECODE') from exc
    _need(rgba.shape == (height, width, 4), 'MODEL_IMAGE_DECODE_SHAPE')
    return np.ascontiguousarray(rgba), width, height


def _texture_info(info, doc, decoded, resources, resource_ids, srgb):
    _need(isinstance(info, dict) and 'extensions' not in info and 'index' in info,
          'MODEL_TEXTURE_INFO')
    _need(info.get('texCoord', 0) == 0, 'MODEL_TEXTURE_UV_SET')
    textures = doc.get('textures', [])
    ti = info['index']
    _need(type(ti) is int and 0 <= ti < len(textures), 'MODEL_TEXTURE_INDEX')
    texture = textures[ti]
    _need(isinstance(texture, dict) and 'extensions' not in texture and 'source' in texture,
          'MODEL_TEXTURE_SUBSET')
    image_index = texture['source']
    _need(type(image_index) is int and 0 <= image_index < len(doc.get('images', [])),
          'MODEL_TEXTURE_SOURCE')
    sampler_index = texture.get('sampler')
    if sampler_index is None:
        sampler = {}
    else:
        samplers = doc.get('samplers', [])
        _need(type(sampler_index) is int and 0 <= sampler_index < len(samplers),
              'MODEL_SAMPLER_INDEX')
        sampler = samplers[sampler_index]
    wrap_s, wrap_t = sampler.get('wrapS', 10497), sampler.get('wrapT', 10497)
    mag, min_filter = sampler.get('magFilter', 9729), sampler.get('minFilter', 9987)
    _need(wrap_s in WRAPS and wrap_t in WRAPS, 'MODEL_TEXTURE_WRAP')
    _need(mag in MAGS and min_filter in MINS, 'MODEL_TEXTURE_FILTER')
    key = (ti, bool(srgb))
    if key not in resource_ids:
        if image_index not in decoded:
            encoded, mime = _image_bytes(doc, decoded['binary'], image_index)
            pixels, width, height = _decode_image(encoded, mime)
            decoded['bytes'] += pixels.nbytes
            _need(decoded['bytes'] <= MAX_ASSET_DECODED_BYTES, 'MODEL_IMAGE_BUDGET')
            decoded[image_index] = (pixels, width, height)
        pixels, width, height = decoded[image_index]
        resource_ids[key] = len(resources)
        resources.append(dict(width=width, height=height, rgba=pixels,
                              wrap_s=wrap_s, wrap_t=wrap_t, min_filter=min_filter,
                              mag_filter=mag, srgb=bool(srgb), source_image=image_index,
                              source_texture=ti))
    return resource_ids[key]


def load_surface_subset(doc, binary, primitive, accessor):
    """Return bounded render attributes, decoded texture records and one core material."""
    attrs = primitive.get('attributes', {})
    _need('NORMAL' in attrs and 'TEXCOORD_0' in attrs, 'MODEL_SURFACE_ATTRIBUTES')
    _need('TANGENT' not in attrs, 'MODEL_TANGENT_SUBSET')  # target GLBs have no tangents; TBN is derived per triangle
    normals = accessor(doc, binary, attrs['NORMAL'])
    uvs = accessor(doc, binary, attrs['TEXCOORD_0'])
    _need(normals.shape[1] == 3 and len(normals) > 0 and normals.dtype.kind == 'f'
          and np.isfinite(normals).all() and (np.abs(normals) <= 1.001).all(), 'MODEL_NORMALS')
    lengths = np.linalg.norm(normals.astype('<f8'), axis=1)
    _need((lengths > 1e-10).all(), 'MODEL_NORMALS_DEGENERATE')
    _need(uvs.shape[1] == 2 and len(uvs) == len(normals) and uvs.dtype.kind == 'f'
          and np.isfinite(uvs).all() and (np.abs(uvs) <= 1e6).all(), 'MODEL_UV')

    material_index = primitive.get('material')
    materials = doc.get('materials', [])
    _need(type(material_index) is int and 0 <= material_index < len(materials), 'MODEL_MATERIAL_INDEX')
    material = materials[material_index]
    _need(isinstance(material, dict) and not material.get('extensions')
          and material.get('alphaMode', 'OPAQUE') == 'OPAQUE'
          and type(material.get('doubleSided', False)) is bool, 'MODEL_MATERIAL_SUBSET')
    pbr = material.get('pbrMetallicRoughness', {})
    _need(isinstance(pbr, dict) and not pbr.get('extensions'), 'MODEL_PBR_SUBSET')
    base = _array(pbr.get('baseColorFactor', [1, 1, 1, 1]), 4, 'MODEL_BASE_COLOR', 0, 1)
    emissive = _array(material.get('emissiveFactor', [0, 0, 0]), 3, 'MODEL_EMISSIVE', 0, 1e4)
    metallic = pbr.get('metallicFactor', 1.0)
    roughness = pbr.get('roughnessFactor', 1.0)
    _need(type(metallic) in (int, float) and np.isfinite(metallic) and 0 <= metallic <= 1,
          'MODEL_METALLIC_FACTOR')
    _need(type(roughness) in (int, float) and np.isfinite(roughness) and 0 <= roughness <= 1,
          'MODEL_ROUGHNESS_FACTOR')
    normal_scale, occlusion_strength = 1.0, 1.0
    normal = material.get('normalTexture')
    if normal is not None:
        _need(not normal.get('extensions'), 'MODEL_TEXTURE_TRANSFORM')
        normal_scale = normal.get('scale', 1.0)
        _need(type(normal_scale) in (int, float) and np.isfinite(normal_scale)
              and abs(normal_scale) <= 100, 'MODEL_NORMAL_SCALE')
    occlusion = material.get('occlusionTexture')
    if occlusion is not None:
        _need(not occlusion.get('extensions'), 'MODEL_TEXTURE_TRANSFORM')
        occlusion_strength = occlusion.get('strength', 1.0)
        _need(type(occlusion_strength) in (int, float) and np.isfinite(occlusion_strength)
              and 0 <= occlusion_strength <= 1, 'MODEL_OCCLUSION_STRENGTH')
    for slot in ('emissiveTexture',):
        if material.get(slot) is not None:
            _need(not material[slot].get('extensions'), 'MODEL_TEXTURE_TRANSFORM')
    for slot in ('baseColorTexture', 'metallicRoughnessTexture'):
        if pbr.get(slot) is not None:
            _need(not pbr[slot].get('extensions'), 'MODEL_TEXTURE_TRANSFORM')

    resources, ids = [], {}
    decoded = {'binary': binary, 'bytes': 0}
    def bind(info, srgb):
        return -1 if info is None else _texture_info(info, doc, decoded, resources, ids, srgb)
    material_out = dict(base_color=base.tolist(), emissive=emissive.tolist(),
                        metallic=float(metallic), roughness=float(roughness),
                        normal_scale=float(normal_scale), occlusion_strength=float(occlusion_strength),
                        base_texture=bind(pbr.get('baseColorTexture'), True),
                        mr_texture=bind(pbr.get('metallicRoughnessTexture'), False),
                        normal_texture=bind(normal, False),
                        emissive_texture=bind(material.get('emissiveTexture'), True),
                        occlusion_texture=bind(occlusion, False),
                        double_sided=material.get('doubleSided', False))
    if any(i >= 0 for i in (material_out['base_texture'], material_out['mr_texture'],
                             material_out['normal_texture'], material_out['emissive_texture'],
                             material_out['occlusion_texture'])):
        _need(len(uvs) == len(normals), 'MODEL_UV')
    return dict(normals=np.ascontiguousarray(normals, dtype='<f4'),
                uvs=np.ascontiguousarray(uvs, dtype='<f4'), textures=resources,
                material=material_out, decoded_image_bytes=decoded['bytes'])
