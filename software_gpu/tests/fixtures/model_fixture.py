"""Tiny real GLB with twelve influences, three animated properties and a skin.

No external data or simulated compiler/renderer outputs are used.
"""
import hashlib
import io
import json
import struct
import numpy as np
from PIL import Image


def make_glb(path, mutate=None, static=False, repeated_faces=1, interleaved=False, surface=False):
    binary = bytearray()
    doc = dict(asset={'version': '2.0'}, buffers=[{'byteLength': 0}], bufferViews=[], accessors=[],
               scenes=[{'nodes': list(range(13))}], scene=0,
               nodes=[{'mesh': 0, 'skin': 0, 'translation': [100, 0, 0]}] +
                     [{'translation': [j, 0, 0]} for j in range(1, 13)],
               materials=[{'doubleSided': True}], meshes=[{'primitives': []}],
               skins=[{'joints': list(range(1, 13))}], animations=[])

    def acc(data, dtype, kind, normalized=False, stride=False):
        a = np.asarray(data, dtype=dtype)
        while len(binary) % 4:
            binary.append(0)
        start = len(binary)
        if stride:
            a = np.column_stack([a, np.full(len(a), 123, dtype=dtype)])
        binary.extend(a.tobytes())
        view = dict(buffer=0, byteOffset=start, byteLength=len(binary)-start)
        if stride:
            view['byteStride'] = a.shape[1]*a.dtype.itemsize
        doc['bufferViews'].append(view)
        item = dict(bufferView=len(doc['bufferViews'])-1, componentType={'<f4':5126, '<u4':5125, '<u2':5123, '<u1':5121}[dtype], count=len(a), type=kind)
        if normalized:
            item['normalized'] = True
        doc['accessors'].append(item)
        return len(doc['accessors'])-1

    positions = [[1, 2, 3], [2, 2, 3], [1, 3, 3]]
    attrs = {'POSITION': acc(positions, '<f4', 'VEC3', stride=interleaved)}
    if surface:
        attrs['NORMAL'] = acc([[0,0,1]]*3, '<f4', 'VEC3')
        attrs['TEXCOORD_0'] = acc([[0,0],[1,0],[0,1]], '<f4', 'VEC2')
    indices = np.zeros((repeated_faces, 3), dtype='u4')
    indices[-1] = [0, 1, 2]  # Last face detects truncated uint16 bin IDs.
    primitive = {'attributes': attrs, 'indices': acc(indices.reshape(-1), '<u4', 'SCALAR'), 'material': 0}
    doc['meshes'][0]['primitives'] = [primitive]
    if surface:
        def png(pixels):
            stream=io.BytesIO();Image.fromarray(np.asarray(pixels,dtype=np.uint8),'RGBA').save(stream,format='PNG')
            while len(binary)%4:binary.append(0)
            start=len(binary);encoded=stream.getvalue();binary.extend(encoded)
            doc['bufferViews'].append(dict(buffer=0,byteOffset=start,byteLength=len(encoded)))
            return len(doc['bufferViews'])-1
        base_view=png([[[255,0,0,255],[0,255,0,255]],[[0,0,255,255],[255,255,255,255]]])
        normal_view=png([[[128,128,255,255]]*2]*2)
        mr_view=png([[[0,128,64,255]]*2]*2)
        doc['images']=[dict(bufferView=base_view,mimeType='image/png'),
                       dict(bufferView=normal_view,mimeType='image/png'),
                       dict(bufferView=mr_view,mimeType='image/png')]
        doc['samplers']=[dict(magFilter=9729,minFilter=9987,wrapS=10497,wrapT=10497)]
        doc['textures']=[dict(sampler=0,source=i) for i in range(3)]
        doc['materials']=[dict(doubleSided=True,emissiveFactor=[0,0,0],
            pbrMetallicRoughness=dict(baseColorFactor=[.8,.7,.6,1],baseColorTexture=dict(index=0),
                metallicFactor=.5,roughnessFactor=.7,metallicRoughnessTexture=dict(index=2)),
            normalTexture=dict(index=1,scale=.8))]
    if static:
        doc['nodes'] = [{'mesh': 0, 'matrix': np.eye(4).reshape(-1).tolist()}]
        doc['scenes'] = [{'nodes': [0]}]
        doc.pop('skins')
    else:
        for k in range(3):
            attrs[f'JOINTS_{k}'] = acc(np.tile(np.arange(4*k, 4*k+4), (3,1)), '<u2', 'VEC4')
            attrs[f'WEIGHTS_{k}'] = acc(np.tile(np.arange(4*k+1, 4*k+5)/78, (3,1)), '<f4', 'VEC4')
        doc['skins'][0]['inverseBindMatrices'] = acc(np.tile(np.eye(4).reshape(1,16), (12,1)), '<f4', 'MAT4')
        times = acc([0, 2], '<f4', 'SCALAR')
        rot = acc([[0,0,0,1], [0,0,-1,0]], '<f4', 'VEC4')
        tr = acc([[2,0,0], [2,1,0]], '<f4', 'VEC3')
        scale = acc([[1,1,1], [1,2,1]], '<f4', 'VEC3')
        doc['animations'] = [dict(name='twelve-influence-motion',
             samplers=[dict(input=times, output=rot), dict(input=times, output=tr, interpolation='STEP'), dict(input=times, output=scale)],
             channels=[dict(sampler=0, target=dict(node=12,path='rotation')),
                       dict(sampler=1, target=dict(node=2,path='translation')),
                       dict(sampler=2, target=dict(node=3,path='scale'))])]
    doc['buffers'][0]['byteLength'] = len(binary)
    if mutate:
        mutate(doc, binary)
    data = json.dumps(doc, separators=(',', ':')).encode()
    data += b' ' * (-len(data)%4)
    binary.extend(b'\0' * (-len(binary)%4))
    raw = struct.pack('<4sII', b'glTF', 2, 28+len(data)+len(binary))
    raw += struct.pack('<I4s',len(data),b'JSON')+data+struct.pack('<I4s',len(binary),b'BIN\0')+binary
    path.write_bytes(raw)
    return {'file':path.name, 'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}
