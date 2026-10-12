"""Exact existing-renderer oracles for all native bio architecture ablations."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from software_gpu.research.bio_workrooms import (POLICIES, build_bio_workrooms,
    run_bio_workrooms, validate_bio_receipt)
from software_gpu.research.native_symbolic import FLAGS, NATIVE, compiler
from software_gpu.research.workrooms import descriptor, encode_request
from software_gpu.tests.test_workrooms import renderer_oracle, scene_fixture


def sparse_scene():
    scene = []
    # 32 small quads, 64 primitives; spatial bins must preserve shared edges.
    for y in range(4):
        for x in range(8):
            left, bottom = -.97+x*.24, -.96+y*.48
            right, top = left+.12, bottom+.22
            rgba = [(x*37+11) % 256, (y*67+23) % 256, (x*19+y*31+71) % 256, 125+x*15]
            z = (x+y-5)*.05
            scene += [dict(vertices=[[left,bottom,z,1],[right,bottom,z,1],[right,top,z,1]],rgba=rgba),
                      dict(vertices=[[left,bottom,z,1],[right,top,z,1],[left,top,z,1]],rgba=rgba)]
    return scene


class TestBioWorkRooms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='are-bio-workrooms-')
        cls.exe, cls.build = build_bio_workrooms(cls.temp.name)
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_every_policy_matches_independent_oracle_and_repeated_frames(self):
        for width,height,tile,workers,scene in [(19,17,1,4,scene_fixture()),
                                               (19,17,3,8,scene_fixture()),
                                               (23,21,8,1,sparse_scene()),
                                               (13,11,64,2,sparse_scene())]:
            ref, final = renderer_oracle(width,height,scene)
            for policy in POLICIES:
                with self.subTest(policy=policy,tile=tile,workers=workers):
                    out = run_bio_workrooms(self.exe,descriptor(width,height,tile,19),scene,
                                            workers,3,policy)
                    self.assertEqual(out['resolved'],ref.color_buffer.tobytes())
                    self.assertEqual(out['rgba'],final.color_buffer.tobytes())
                    self.assertEqual(out['depth'],final.depth_buffer.astype('<f4').tobytes())
                    self.assertEqual(len(out['receipt']['baseline_samples_ms']),3)
                    self.assertEqual(out['receipt']['baseline_workers'],workers)

    def test_halos_culling_geometry_and_first_submission_ties(self):
        for seed in range(5):
            rng = np.random.default_rng(seed+41)
            scene = scene_fixture()
            for _ in range(9):
                w = rng.uniform(.5,2,3)
                xyz = rng.uniform(-1,1,(3,3))
                scene.append(dict(vertices=np.column_stack((xyz*w[:,None],w)).tolist(),
                                  rgba=rng.integers(0,256,4).tolist()))
            scene += [dict(vertices=[[0,0,0,1]]*3,rgba=[255]*4)]
            ref,final = renderer_oracle(27,25,scene)
            for tile in (1,4,7):
                for policy in ('combined','without-checkpoints','without-frontier','locality'):
                    out = run_bio_workrooms(self.exe,descriptor(27,25,tile),scene,8,2,policy)
                    self.assertEqual(out['resolved'],ref.color_buffer.tobytes(),(seed,tile,policy))
                    self.assertEqual(out['rgba'],final.color_buffer.tobytes(),(seed,tile,policy))
                    self.assertEqual(out['depth'],final.depth_buffer.astype('<f4').tobytes(),(seed,tile,policy))

    def test_checkpoint_rejections_and_sleeping_worker_generation_recovery(self):
        probe = Path(self.temp.name)/'checkpoint_probe'
        source = Path(__file__).parent/'fixtures/bio_checkpoint_probe.cpp'
        subprocess.run([compiler(),*FLAGS,'-pthread','-I',str(NATIVE),str(source),'-o',str(probe)],
                       check=True,capture_output=True,timeout=120)
        result = subprocess.run([str(probe)],check=True,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.stdout,'CHECKPOINTS_AND_WORKERS_OK\n')

    def test_native_and_boundary_reject_invalid_policies_and_evidence(self):
        request = encode_request(descriptor(),scene_fixture())
        for args,data in [(['4','1','unknown'],request),(['0','1','combined'],request),
                          (['4','31','combined'],request),(['4','1','combined'],request[:-1]),
                          (['4','1','combined'],request+b'x'),(['4','1'],request)]:
            p = subprocess.run([str(self.exe),*args],input=data,capture_output=True,timeout=10)
            self.assertEqual(p.returncode,2);self.assertEqual(p.stdout,b'')
        for kwargs in (dict(policy='unknown'),dict(policy=True),dict(workers=True),dict(repeats=0)):
            with self.assertRaises(ValueError):run_bio_workrooms(self.exe,descriptor(),scene_fixture(),**kwargs)
        outside = [dict(vertices=[[2,0,0,1],[0,1,0,1],[0,0,0,1]],rgba=[255]*4)]
        with self.assertRaisesRegex(RuntimeError,'ROOM_REQUIRES_FINITE_CLIPPED_GEOMETRY'):
            run_bio_workrooms(self.exe,descriptor(),outside,2,1)
        good = run_bio_workrooms(self.exe,descriptor(),scene_fixture(),2,2,'combined')['receipt']
        for field,value in [('policy','reuse'),('baseline_workers',1),('warmups',1),
                            ('paired_order','unpaired'),('frontier_shared_stage_interval',False),
                            ('baseline_samples_ms',[1]),('samples_ms',[0,1]),
                            ('cpu_samples_ms',[float('nan'),1]),('baseline_cpu_samples_ms',[True,1]),
                            ('candidate_construction_ms',-1),('spatial_references',True)]:
            bad = copy.deepcopy(good);bad[field] = value
            with self.assertRaises(ValueError):validate_bio_receipt(bad,'combined',2,2)

    def test_build_rejects_corrupted_reference_core_and_real_compiler_failure(self):
        # Redirect only the filesystem/build boundary; execute the real compiler.
        with tempfile.TemporaryDirectory(prefix='are-bio-build-admission-') as tmp:
            root = Path(tmp);native = root/'native/symbolic';native.mkdir(parents=True)
            fixtures = root/'software_gpu/tests/fixtures';fixtures.mkdir(parents=True)
            for name in ('core.hpp','model_material.hpp','workrooms.hpp','workrooms_wire.hpp','bio_workrooms.hpp','bio_workrooms_main.cpp'):
                (native/name).write_bytes((NATIVE/name).read_bytes())
            frozen = fixtures/'workrooms-baseline-87ff.hpp'
            original = (Path(__file__).parent/'fixtures/workrooms-baseline-87ff.hpp').read_bytes()
            frozen.write_bytes(original+b'// corruption\n')
            with patch('software_gpu.research.bio_workrooms.NATIVE',native):
                with self.assertRaisesRegex(ValueError,'ROOM_FROZEN_BASELINE_MISMATCH'):
                    build_bio_workrooms(root/'output')
                frozen.write_bytes(original)
                core = (native/'core.hpp').read_bytes();(native/'core.hpp').write_bytes(core+b'// corruption\n')
                with self.assertRaisesRegex(ValueError,'ROOM_FROZEN_CORE_MISMATCH'):
                    build_bio_workrooms(root/'output')
                (native/'core.hpp').write_bytes(core)
                with (native/'bio_workrooms_main.cpp').open('a') as f:f.write('\n#error intentional_build_rejection_probe\n')
                with self.assertRaisesRegex(RuntimeError,'ROOM_BIO_BUILD_FAILED'):
                    build_bio_workrooms(root/'output')


if __name__ == '__main__':
    unittest.main()
