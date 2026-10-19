"""Real-frame and fail-closed receipt tests for #113 shader impact.

The production benchmark itself performs 15 measured alternating pairs;
the short draw here is a correctness smoke, not a speedup estimate.
"""
import copy
import hashlib
import subprocess
import unittest

import numpy as np

from software_gpu.benchmarks.compare_shader_frames import (
    PreviousVertexColor, measure_case, validate, make_digest, SCENES, MODES, ROOT, SOURCES
)
from software_gpu.graphics.batch_shader import VertexColorShader


class FullFrameShaderImpactContracts(unittest.TestCase):
    def test_previous_scalar_and_batch_are_real_numpy_reference(self):
        old=PreviousVertexColor()
        new=VertexColorShader()
        color=np.array([.2,.5,1.5],dtype=np.float32)
        np.testing.assert_array_equal(
            old.fragment_shader({"color":color}),
            tuple(int(x) for x in np.clip(color*255,0,255).astype(np.uint8))+(255,)
        )
        self.assertEqual(old.fragment_shader({"color":color}),
                         new.fragment_shader({"color":color}))
        rows=np.array([[.5,-1.,.2],[1.2,.3,.9]],dtype=np.float32)
        np.testing.assert_array_equal(old.fragment_shader_batch({"color":rows}),
                                      new.fragment_shader_batch({"color":rows}))
        np.testing.assert_array_equal(rows, np.array([[.5,-1.,.2],[1.2,.3,.9]],dtype=np.float32))

    def test_real_frame_rgba_depth_parity_on_both_execution_modes(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                result=measure_case("smoke",8,.8,mode,pixels=48,workers=1,repeats=1)
                self.assertEqual(len(result["pairs"]),1)
                self.assertEqual(len(result["rgba_sha256"]),64)
                self.assertEqual(len(result["depth_sha256"]),64)
                self.assertGreater(result["covered_pixels"],10)
                self.assertEqual(result["pairs"][0]["hashes"],
                                 {"rgba_sha256":result["rgba_sha256"],
                                  "depth_sha256":result["depth_sha256"]})
                if mode=="plan-batch":
                    self.assertGreater(result["min_batch_fragment_samples"],0)

    def test_report_contract_blocks_timing_tamper_or_incomplete_pairs(self):
        pair1={"order":["previous","current"],"previous_ms":1.,
               "current_ms":.75,
               "hashes":{"rgba_sha256":"a"*64,"depth_sha256":"b"*64}}
        pair2={"order":["current","previous"],"previous_ms":1.,
               "current_ms":.75,"hashes":pair1["hashes"]}
        cases=[]
        for name,count,_ in SCENES:
            for mode in MODES:
                cases.append({"scene":name,"mode":mode,"triangles":count,
                              "pixels":96,"workers":2,"covered_pixels":20,
                              "min_batch_fragment_samples":1 if mode=="plan-batch" else 0,
                              "pairs":[copy.deepcopy(pair1 if i%2==0 else pair2)
                                       for i in range(15)],
                              "rgba_sha256":"a"*64,"depth_sha256":"b"*64,
                              "median_previous_ms":1.0,"median_current_ms":0.75,
                              "iqr_previous_ms":0.0,"iqr_current_ms":0.0,
                              "mad_previous_ms":0.0,"mad_current_ms":0.0,
                              "paired_median_speedup":4/3,"faster_pairs":15})
        report={"protocol":"are.shader.full-frame-abba.v1",
                "repeats":15,"pixels":96,"workers":2,
                "head_sha":subprocess.check_output(
                    ["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
                "source_sha256":{s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest()
                                 for s in SOURCES},
                "scope":"full draw_mesh CPU; RGBA8 and float32 depth parity",
                "host":{"platform":"unit-test","python":"test",
                        "numpy":np.__version__,"logical_cpus":2},
                "cases":cases}
        report["sha256"]=make_digest(report)
        self.assertTrue(validate(report))

        mutated=copy.deepcopy(report)
        mutated["cases"][0]["pairs"][0]["current_ms"]=0
        with self.assertRaisesRegex(ValueError,"SHADER_FRAME_RECEIPT_DIGEST"):
            validate(mutated)
        mutated["sha256"]=make_digest(mutated)
        with self.assertRaisesRegex(ValueError,"SHADER_FRAME_RECEIPT_PAIRS"):
            validate(mutated)
        mutated=copy.deepcopy(report)
        mutated["cases"][0]["pairs"].pop()
        mutated["sha256"]=make_digest(mutated)
        with self.assertRaisesRegex(ValueError,"SHADER_FRAME_RECEIPT_PAIRS"):
            validate(mutated)

        # A self-consistent digest is not evidence of a genuine commit,
        # unmodified sources, or truthful summaries.
        def head_tamper(r):
            r["head_sha"]="0"*40

        def source_tamper(r):
            r["source_sha256"][SOURCES[0]]="f"*64

        def source_schema_tamper(r):
            r["source_sha256"]["untracked.py"]="f"*64

        def median_tamper(r):
            r["cases"][0]["median_current_ms"]=1.

        def spread_tamper(r):
            r["cases"][0]["iqr_current_ms"]=999.

        def case_tamper(r):
            r["cases"][0]["pixels"]=64

        def batch_tamper(r):
            r["cases"][1]["min_batch_fragment_samples"]=0

        for name,change,error in (
            ("head",head_tamper,"HEAD"),
            ("source",source_tamper,"SOURCE"),
            ("source-schema",source_schema_tamper,"SOURCE"),
            ("median",median_tamper,"TIMINGS"),
            ("spread",spread_tamper,"TIMINGS"),
            ("case-metadata",case_tamper,"CASES"),
            ("unexercised-batch",batch_tamper,"CASES"),
        ):
            with self.subTest(tamper=name):
                bad=copy.deepcopy(report)
                change(bad)
                bad["sha256"]=make_digest(bad)
                with self.assertRaisesRegex(ValueError,"SHADER_FRAME_RECEIPT_"+error):
                    validate(bad)


if __name__=="__main__":
    unittest.main()
