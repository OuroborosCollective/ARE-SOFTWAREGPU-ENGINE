"""Exact frame parity requires matching capture metadata and RGBA8 bytes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.owner_glb_frame_pixel_parity import compare

class TestExactPixelParity(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.ref=self.root/'godot.png'
        self.candidate=self.root/'are.png'
        self.ref_meta=self.root/'godot.json'
        self.candidate_meta=self.root/'are.json'
        profile={'protocol':'are.game-frame-capture.v1','source_glb_sha256':'a'*64,'scene_revision':'b'*40,
                 'frame_tick':42,'animation_seconds':1.25,'camera_view':[1.]*16,'camera_projection':[2.]*16,
                 'lighting_sha256':'c'*64,'material_profile_sha256':'d'*64,'environment_sha256':'e'*64,
                 'color_space':'srgb','tone_mapping':'linear','texture_filter':'linear-mipmap-linear',
                 'texture_compression':'lossless','alpha_premultiplied':False,'samples':1,
                 'viewport':[4,4]}
        self.ref_meta.write_text(json.dumps({'renderer':'godot4-gl-compatibility','capture':profile}))
        self.candidate_meta.write_text(json.dumps({'renderer':'are-softwaregpu','capture':profile}))
        Image.new('RGBA',(4,4),(4,8,16,255)).save(self.ref)
        Image.new('RGBA',(4,4),(4,8,16,255)).save(self.candidate)
    def tearDown(self):self.tmp.cleanup()
    def run_gate(self):return compare(self.ref,self.candidate,self.ref_meta,self.candidate_meta)
    def test_identical_rgba_and_capture_contract(self):
        result=self.run_gate()
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['mismatch_pixels'],0)
        self.assertEqual(result['pixel_count'],16)
    def test_single_channel_deviation_rejects_parity(self):
        image=Image.open(self.candidate).convert('RGBA')
        image.putpixel((1,2),(5,8,16,255))
        image.save(self.candidate)
        result=self.run_gate()
        self.assertEqual(result['status'],'FAIL')
        self.assertEqual(result['mismatch_pixels'],1)
        self.assertEqual(result['first_difference'],[1,2])
        self.assertEqual(result['max_channel_delta'],1)
    def test_rejects_capture_drift_and_image_resize(self):
        meta=json.loads(self.candidate_meta.read_text())
        meta['capture']['tone_mapping']='aces'
        self.candidate_meta.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError,'CAPTURE_CONTRACT_MISMATCH'):self.run_gate()
        self.candidate_meta.write_text(self.ref_meta.read_text())
        Image.new('RGBA',(5,4),(4,8,16,255)).save(self.candidate)
        with self.assertRaisesRegex(ValueError,'IMAGE_DIMENSIONS_MISMATCH'):self.run_gate()
    def test_rejects_non_png_and_missing_fields(self):
        Image.new('RGB',(4,4),(4,8,16)).save(self.candidate,format='JPEG')
        with self.assertRaisesRegex(ValueError,'PNG_REQUIRED'):self.run_gate()
        Image.new('RGBA',(4,4),(4,8,16,255)).save(self.candidate)
        meta=json.loads(self.ref_meta.read_text())
        meta['capture'].pop('texture_compression')
        self.ref_meta.write_text(json.dumps(meta))
        self.candidate_meta.write_text(json.dumps(meta))
        with self.assertRaisesRegex(ValueError,'CAPTURE_FIELD_MISSING'):self.run_gate()

if __name__=='__main__':
    unittest.main()
