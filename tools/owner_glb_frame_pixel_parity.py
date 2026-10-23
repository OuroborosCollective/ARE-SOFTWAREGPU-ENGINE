"""Fail-closed exact RGBA8 comparison of equivalent captured 3D game frames.

Only checks an identical capture contract and exact pixels. It never silently
scales, tonemaps, crops, color-corrects or alters an image to force parity.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from PIL import Image

FIELDS=('protocol','source_glb_sha256','scene_revision','frame_tick',
    'animation_seconds','camera_view','camera_projection','lighting_sha256',
    'material_profile_sha256','environment_sha256','color_space','tone_mapping',
    'texture_filter','texture_compression','alpha_premultiplied','samples','viewport')

def _digest(value:bytes)->str:
    return hashlib.sha256(value).hexdigest()

def _capture(path):
    obj=json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(obj,dict) or not isinstance(obj.get('capture'),dict) or not isinstance(obj.get('renderer'),str) or not obj['renderer']:
        raise ValueError('CAPTURE_RECORD_INVALID')
    capture=obj['capture']
    if set(FIELDS)-set(capture):
        raise ValueError('CAPTURE_FIELD_MISSING')
    if capture['protocol']!='are.game-frame-capture.v1':
        raise ValueError('CAPTURE_PROTOCOL_INVALID')
    for name in ('source_glb_sha256','lighting_sha256','material_profile_sha256','environment_sha256'):
        value=capture[name]
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('CAPTURE_SHA256_INVALID')
    for name in ('camera_view','camera_projection'):
        seq=capture[name]
        if not isinstance(seq,list) or len(seq)!=16 or not all(type(x) in (float,int) and math.isfinite(x) for x in seq):
            raise ValueError('CAPTURE_MATRIX_INVALID')
    size=capture['viewport']
    if not isinstance(size,list) or len(size)!=2 or any(type(v) is not int or not 1<=v<=4096 for v in size):
        raise ValueError('CAPTURE_VIEWPORT_INVALID')
    if (type(capture['frame_tick']) is not int or capture['frame_tick']<0 or
        type(capture['samples']) is not int or not 1<=capture['samples']<=64 or
        type(capture['animation_seconds']) not in (float,int) or
        not math.isfinite(capture['animation_seconds']) or capture['animation_seconds']<0 or
        type(capture['alpha_premultiplied']) is not bool):
        raise ValueError('CAPTURE_TIME_OR_SAMPLES_INVALID')
    return obj

def _load_rgba(path,expected):
    p=Path(path)
    with p.open('rb') as f:
        if f.read(8)!=b'\x89PNG\r\n\x1a\n':raise ValueError('PNG_REQUIRED')
    with Image.open(p) as im:
        if im.format!='PNG' or im.mode not in ('RGB','RGBA'):
            raise ValueError('RGB_OR_RGBA_PNG_REQUIRED')
        if im.size!=tuple(expected):
            raise ValueError('IMAGE_DIMENSIONS_MISMATCH')
        rgba=im.convert('RGBA').tobytes() if im.mode=='RGB' else im.tobytes()
    return rgba

def compare(reference_png,candidate_png,reference_capture,candidate_capture):
    """Return PASS iff independently captured equal-contract framebuffers match."""
    reference=_capture(reference_capture)
    candidate=_capture(candidate_capture)
    if reference['capture']!=candidate['capture']:
        raise ValueError('CAPTURE_CONTRACT_MISMATCH')
    contract=reference['capture']
    target=_load_rgba(reference_png,contract['viewport'])
    actual=_load_rgba(candidate_png,contract['viewport'])
    mismatches=0
    first=None
    maxdelta=0
    w=contract['viewport'][0]
    for i in range(0,len(target),4):
        differences=[abs(target[i+j]-actual[i+j]) for j in range(4)]
        if any(differences):
            mismatches+=1
            if first is None:
                pixel=i//4
                first=[pixel%w,pixel//w]
            maxdelta=max(maxdelta,*differences)
    return {'protocol':'are.glb-exact-game-frame-parity.v1',
            'status':'PASS' if mismatches==0 else 'FAIL',
            'pixel_count':len(target)//4,'mismatch_pixels':mismatches,
            'first_difference':first,'max_channel_delta':maxdelta,
            'reference_rgba_sha256':_digest(target),
            'candidate_rgba_sha256':_digest(actual),
            'capture_sha256':_digest(json.dumps(contract,sort_keys=True,separators=(',',':'),allow_nan=False).encode()),
            'reference_renderer':reference['renderer'],
            'candidate_renderer':candidate['renderer'],
            'source_glb_sha256':contract['source_glb_sha256'],
            'pixel_equal_to_game':mismatches==0 and reference['renderer'].startswith('godot')}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--reference-contract',type=Path,required=True)
    p.add_argument('--candidate-contract',type=Path,required=True)
    p.add_argument('--receipt',type=Path)
    a=p.parse_args(argv)
    try:
        report=compare(a.reference,a.candidate,a.reference_contract,a.candidate_contract)
    except (ValueError,KeyError,OSError,json.JSONDecodeError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc)}))
        return 2
    if a.receipt:
        a.receipt.parent.mkdir(parents=True,exist_ok=True)
        a.receipt.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,sort_keys=True))
    return 0 if report['status']=='PASS' else 1

if __name__=='__main__':
    raise SystemExit(main())
