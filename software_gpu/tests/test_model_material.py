"""Independent numerical tests for the AREMDL03 native material contract."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from software_gpu.research.native_symbolic import FLAGS, NATIVE, compiler
from tools.model_surface_reference import perspective_attribute, cook_torrance

HARNESS = r'''#include "model_material.hpp"
#include <iomanip>
#include <iostream>
using namespace are::rooms;
int main(){
    const std::array<float,3> lambda{.2f,.3f,.5f},invw{1,.5f,.25f};
    const std::array<SurfaceV2,3> uow{{{0,0},{.5f,0},{0,.25f}}};
    const auto uv=surface_perspective_interpolate<2>(lambda,invw,uow);
    SurfaceTexture t;t.srgb=true;t.wrap_s=t.wrap_t=10497;t.mag_filter=9729;t.min_filter=9729;
    SurfaceMip m;m.width=m.height=2;m.rgba={255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,255,255};
    t.mips.push_back(std::move(m));t.build_mips();
    const auto center=surface_sample(t,.5,.5,-1),negative=surface_sample(t,-.25,.25,-1),positive=surface_sample(t,.75,.25,-1);
    SurfaceTexture normal;normal.wrap_s=normal.wrap_t=10497;normal.mag_filter=9729;normal.min_filter=9729;
    SurfaceMip nm;nm.width=nm.height=1;nm.rgba={255,128,255,255};normal.mips.push_back(std::move(nm));normal.build_mips();
    SurfaceMaterial mat;mat.base_color={.8f,.7f,.6f,1};mat.metallic=.5f;mat.roughness=.7f;mat.normal_scale=.5f;mat.normal_texture=0;
    SurfaceLighting lighting;lighting.camera={0,0,4};
    const auto color=surface_pbr(mat,std::vector<SurfaceTexture>{normal},{.5f,.5f},{0,0,1},{1,0,0},{0,1,0},
                                 {0,0,0},{0,0},{0,0},lighting);
    std::cout<<std::setprecision(17)<<"{\"uv\":["<<uv[0]<<','<<uv[1]<<"],\"center\":[";
    for(int k=0;k<4;++k){if(k)std::cout<<',';std::cout<<center[k];}
    std::cout<<"],\"mip\":["<<unsigned(t.mips[1].rgba[0])<<','<<unsigned(t.mips[1].rgba[1])<<','<<unsigned(t.mips[1].rgba[2])
             <<"],\"repeat_delta\":[";
    for(int k=0;k<4;++k){if(k)std::cout<<',';std::cout<<negative[k]-positive[k];}
    std::cout<<"],\"pbr\":["<<color[0]<<','<<color[1]<<','<<color[2]<<"]}\n";
}
'''


class TestNativeModelMaterial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='are-model-material-')
        root=Path(cls.temp.name);source=root/'material.cpp';source.write_text(HARNESS)
        exe=root/'material'
        result=subprocess.run([compiler(),*FLAGS,f'-I{NATIVE}',str(source),'-o',str(exe)],capture_output=True,text=True,timeout=120)
        if result.returncode:
            raise RuntimeError('MODEL_MATERIAL_TEST_BUILD:'+result.stderr[-6000:])
        cls.result=json.loads(subprocess.check_output([str(exe)],text=True))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_perspective_correct_uv_differs_from_affine_interpolation(self):
        expected=perspective_attribute([.2,.3,.5],[1,2,4],[[0,0],[1,0],[0,1]])
        self.assertAlmostEqual(self.result['uv'][0],expected[0],places=6)
        self.assertAlmostEqual(self.result['uv'][1],expected[1],places=6)
        self.assertGreater(abs(expected[0]-.3)+abs(expected[1]-.5),.2)

    def test_srgb_bilinear_repeat_wrap_and_linear_mip_generation(self):
        for value in self.result['center'][:3]:
            self.assertAlmostEqual(value,.5,places=6)
        self.assertAlmostEqual(self.result['center'][3],1,places=6)
        self.assertEqual(self.result['mip'],[188,188,188])
        for delta in self.result['repeat_delta']:
            self.assertAlmostEqual(delta,0,places=7)

    def test_cook_torrance_ggx_and_normal_map_match_independent_oracle(self):
        expected=cook_torrance([.8,.7,.6],.5,.7,[0,0,1],[1,0,0],[0,1,0],
                               normal_map=(1,128/255,1),normal_scale=.5)
        for actual,oracle in zip(self.result['pbr'],expected):
            self.assertAlmostEqual(actual,oracle,places=6)


if __name__=='__main__':
    unittest.main()
