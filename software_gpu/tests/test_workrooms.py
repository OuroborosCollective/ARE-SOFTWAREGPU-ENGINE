"""Actual C++ rendering against the independent existing MSAA/FXAA renderer."""
import copy
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

import numpy as np
from software_gpu.graphics.postprocess import MSAAFramebuffer, MSAARasterizer, FXAAPass
from software_gpu.graphics.shader import Shader, Vertex
from software_gpu.research.workrooms import (build_workrooms, descriptor, parse_descriptor,
    encode_request, decode_response, run_workrooms, to_framebuffer)


def scene_fixture():
    # Shared diagonal, unequal clip w, depth overlap, alpha and first-wins tie.
    return [
        dict(vertices=[[-.9, -.9, .3, 1], [.9, -.9, .3, 1], [.9, .9, .3, 1]], rgba=[40, 170, 240, 255]),
        dict(vertices=[[-.9, -.9, .3, 1], [.9, .9, .3, 1], [-.9, .9, .3, 1]], rgba=[240, 140, 30, 200]),
        dict(vertices=[[-.35, -.45, -.4, 1], [1.1, -.5, .1, 2], [-.1, .8, .2, 1]], rgba=[220, 45, 120, 255]),
        dict(vertices=[[-.35, -.45, -.4, 1], [1.1, -.5, .1, 2], [-.1, .8, .2, 1]], rgba=[0, 255, 0, 255]),
    ]


class FlatShader(Shader):
    def __init__(self, rgba):
        self.rgba = rgba
    def vertex_shader(self, vertex):
        return vertex.position, {}
    def fragment_shader(self, varyings):
        return self.rgba


def renderer_oracle(width, height, scene):
    fb = MSAAFramebuffer(width, height)
    fb.clear(0, 0, 0, 255)
    raster = MSAARasterizer(fb)
    for triangle in scene:
        raster.draw_mesh([Vertex(v) for v in triangle['vertices']], [(0, 1, 2)], FlatShader(triangle['rgba']))
    resolved = fb.resolve()
    return resolved, FXAAPass.apply(resolved)


class TestWorkRooms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='are-workrooms-')
        cls.exe, cls.build = build_workrooms(cls.temp.name)
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_framebuffer_oracle_tiling_workers_and_handoff(self):
        scene = scene_fixture()
        reference, final = renderer_oracle(19, 17, scene)
        for tile, workers in [(1, 1), (3, 4), (8, 2), (64, 8)]:
            with self.subTest(tile=tile, workers=workers):
                out = run_workrooms(self.exe, descriptor(19, 17, tile, 7), scene, workers, 2)
                self.assertEqual(out['resolved'], reference.color_buffer.tobytes())
                self.assertEqual(out['rgba'], final.color_buffer.tobytes())
                self.assertEqual(out['depth'], final.depth_buffer.astype('<f4').tobytes())
                fb = to_framebuffer(out)
                np.testing.assert_array_equal(fb.color_buffer, final.color_buffer)
                np.testing.assert_array_equal(fb.depth_buffer, final.depth_buffer)
                nt = ((19+tile-1)//tile)*((17+tile-1)//tile)
                self.assertEqual(out['receipt']['rooms_executed'], 4+3*nt)
                self.assertEqual(out['receipt']['address_examples'][-1][-2:], [3, 7])
                self.assertFalse(out['receipt']['hardware_gpu_submitted'])

    def test_seeded_geometry_culling_and_strict_depth(self):
        for seed in range(6):
            rng = np.random.default_rng(seed)
            scene = scene_fixture()[:2]
            for _ in range(4):
                xyz = rng.uniform(-.9, .9, (3, 3))
                w = rng.uniform(.5, 2, 3)
                vertices = np.column_stack((xyz*w[:, None], w)).tolist()
                scene.append(dict(vertices=vertices, rgba=rng.integers(0, 256, 4).tolist()))
            scene += [dict(vertices=[[0, 0, 0, 1]]*3, rgba=[255]*4)]
            ref, final = renderer_oracle(13, 11, scene)
            out = run_workrooms(self.exe, descriptor(13, 11, 3), scene, 4)
            self.assertEqual(out['resolved'], ref.color_buffer.tobytes(), seed)
            self.assertEqual(out['rgba'], final.color_buffer.tobytes(), seed)
            self.assertEqual(out['depth'], final.depth_buffer.astype('<f4').tobytes(), seed)
        # Full coverage with shared diagonal has no cracks; exact equal depth
        # retains first submission, including its alpha byte.
        scene = [dict(vertices=[[-1, -1, 0, 1], [1, -1, 0, 1], [1, 1, 0, 1]], rgba=[11, 22, 33, 44]),
                 dict(vertices=[[-1, -1, 0, 1], [1, 1, 0, 1], [-1, 1, 0, 1]], rgba=[11, 22, 33, 44])]
        scene += [dict(vertices=t['vertices'], rgba=[255]*4) for t in scene]
        out = run_workrooms(self.exe, descriptor(8, 8, 1), scene, 4)
        self.assertEqual(out['resolved'], bytes([11, 22, 33, 44])*64)

    def test_native_rejects_untrusted_wire_before_handoff(self):
        request = encode_request(descriptor(), scene_fixture())
        cases = [request[:-1], request+b'x', b'BADINPUT'+request[8:], request[:20]]
        bad = bytearray(request); struct.pack_into('<I', bad, 40, 0); cases.append(bad)
        bad = bytearray(request); struct.pack_into('<I', bad, 56, 0xffffffff); cases.append(bad)
        for value in [float('nan'), float('inf'), 2.0]:
            bad = bytearray(request); struct.pack_into('<f', bad, 60, value); cases.append(bad)
        bad = bytearray(request); struct.pack_into('<f', bad, 72, 0.0); cases.append(bad)
        for data in cases:
            p = subprocess.run([str(self.exe), '4', '1'], input=data, capture_output=True, timeout=10)
            self.assertEqual(p.returncode, 2)
            self.assertEqual(p.stdout, b'')
            self.assertIn(b'NATIVE_REJECTED:', p.stderr)
        for args in [[], ['0', '1'], ['9', '1'], ['1', '31'], ['2x', '1']]:
            p = subprocess.run([str(self.exe), *args], input=request, capture_output=True, timeout=10)
            self.assertEqual(p.returncode, 2)

    def test_parser_and_transport_fail_closed(self):
        ir = descriptor()
        self.assertEqual(parse_descriptor(json.dumps(ir)), ir)
        self.assertEqual(parse_descriptor((Path(__file__).parent/'fixtures/workrooms-plan.json').read_text()), ir)
        for change in [dict(width=True), dict(width=2048), dict(tile=0), dict(frame=-1),
                       dict(stages=list(reversed(ir['stages']))), dict(coordinates=['x', 'y', 'z', 'w']),
                       dict(execute='anything')]:
            with self.assertRaises(ValueError):
                parse_descriptor(json.dumps(dict(ir, **change)))
        for source in ['[]', '{}', 'x'*4097, '{"width":2,"width":3}']:
            with self.assertRaises(ValueError): parse_descriptor(source)
        for scene in [[], scene_fixture()*17, [dict(vertices=[[0]*4]*3, rgba=[256]*4)],
                      [dict(vertices=[[float('nan')]*4]*3, rgba=[0]*4)],
                      [dict(vertices=[[1e300]*4]*3, rgba=[0]*4)],
                      [dict(vertices=[[0]*4]*2, rgba=[0]*4)], [dict(code='Run')]]:
            with self.assertRaises(ValueError): encode_request(ir, scene)
        for kwargs in [dict(workers=0), dict(workers=True), dict(repeats=31)]:
            with self.assertRaises(ValueError): run_workrooms(self.exe, ir, scene_fixture(), **kwargs)
        request = encode_request(ir, scene_fixture())
        raw = subprocess.run([str(self.exe), '2', '1'], input=request, capture_output=True, check=True).stdout
        decode_response(raw, request)
        badshape = bytearray(raw); struct.pack_into('<I', badshape, 40, 999)
        for bad in [b'', b'BADMAGIC'+raw[8:], raw[:8]+bytes(32)+raw[40:], raw[:-1], raw+b'x', raw[:100], badshape]:
            with self.assertRaises(ValueError): decode_response(bad, request)
        end = 48+32*32*12
        receipt = json.loads(raw[end+4:])
        for field, value in [('handoff_ready', False), ('rooms_executed', 1), ('hardware_gpu_submitted', True)]:
            edited = dict(receipt, **{field: value}); data = json.dumps(edited).encode()
            with self.assertRaises(ValueError): decode_response(raw[:end]+struct.pack('<I', len(data))+data, request)
        edited = copy.deepcopy(receipt); edited['waves'][0]['worker_jobs'] = [0, 0]
        data = json.dumps(edited).encode()
        with self.assertRaises(ValueError): decode_response(raw[:end]+struct.pack('<I', len(data))+data, request)


if __name__ == '__main__':
    unittest.main()
