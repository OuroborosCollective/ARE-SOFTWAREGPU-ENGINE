"""Independent native projection/clipping contract tests for the model profile."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from software_gpu.research.native_symbolic import FLAGS, NATIVE, compiler


HARNESS = r'''#include "model_projection.hpp"
#include <iomanip>
#include <iostream>
using namespace are::models::projection;
int main(){
    Camera c; c.eye={0,0,0}; c.target={0,0,-1}; c.up={0,1,0};
    c.fov_y_degrees=90; c.near_plane=1; c.far_plane=10;
    const auto n=project({0,0,-1},c,1.0);
    const auto r=project({1,0,-1},c,1.0);
    const auto f=project({0,0,-10},c,1.0);
    bool invalid_camera=false;Camera bad=c;bad.far_plane=bad.near_plane;
    try{(void)make_projector(bad,1.0);}catch(const std::runtime_error&){invalid_camera=true;}
    std::cout<<std::setprecision(9)<<"{\"near\":["<<n.x<<','<<n.y<<','<<n.z<<','<<n.w
             <<"],\"right\":["<<r.x<<','<<r.y<<','<<r.z<<','<<r.w
             <<"],\"far\":["<<f.x<<','<<f.y<<','<<f.z<<','<<f.w<<"],\"invalid_camera\":"
             <<(invalid_camera?"true":"false")<<",\"counts\":[";
    for(unsigned plane=0;plane<6;++plane){
        std::array<Vertex,3> t{{{-0.5f,-0.5f,0,1},{0.5f,-0.5f,0,1},{0,0.5f,0,1}}};
        switch(plane){case 0:t[0].x=-2;break;case 1:t[0].x=2;break;case 2:t[0].y=-2;break;
            case 3:t[0].y=2;break;case 4:t[0].z=-2;break;default:t[0].z=2;break;}
        std::size_t count=0;
        clip_triangle(t,[&](const auto& tri){++count;for(const auto& v:tri)for(unsigned p=0;p<6;++p)
            if(distance(v,p)<-2e-6 || !(v.w>0))throw std::runtime_error("outside clip volume");});
        if(plane)std::cout<<',';std::cout<<count;
    }
    std::array<Vertex,3> outside{{{-2,-.2f,0,1},{-2,.2f,0,1},{-2,0,.5f,1}}};
    std::size_t rejected=0;clip_triangle(outside,[&](const auto&){++rejected;});
    std::cout<<"],\"outside\":"<<rejected<<"}\n";
}
'''


class TestNativeModelProjection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='are-model-projection-')
        root=Path(cls.temp.name);source=root/'projection.cpp';source.write_text(HARNESS)
        exe=root/'projection'
        result=subprocess.run([compiler(),*FLAGS,f'-I{NATIVE}',str(source),'-o',str(exe)],capture_output=True,text=True,timeout=120)
        if result.returncode:
            raise RuntimeError('MODEL_PROJECTION_TEST_BUILD:'+result.stderr[-4000:])
        cls.result=json.loads(subprocess.check_output([str(exe)],text=True))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_perspective_projection_maps_near_and_far_to_opengl_clip_depth(self):
        near=self.result['near'];right=self.result['right'];far=self.result['far']
        self.assertEqual(near[0:2],[0,0]);self.assertAlmostEqual(near[2]/near[3],-1,places=6)
        self.assertAlmostEqual(right[0]/right[3],1,places=6)
        self.assertAlmostEqual(far[2]/far[3],1,places=6)

    def test_all_six_frustum_planes_clip_and_fully_outside_triangle_culls(self):
        self.assertEqual(self.result['counts'],[2,2,2,2,2,2])
        self.assertEqual(self.result['outside'],0)

    def test_camera_rejects_invalid_clip_range(self):
        self.assertTrue(self.result['invalid_camera'])


if __name__=='__main__':
    unittest.main()
