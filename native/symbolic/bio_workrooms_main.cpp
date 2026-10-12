// Paired native A/B driver. No Python linkage; consumes every full frame.
#include "bio_workrooms.hpp"
#include <ctime>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
// Exact historical source supplied by the build boundary, hash-bound in receipt.
namespace frozen {
using ::are::require_environment;
#include "frozen_workrooms.hpp"
}
#include "workrooms_wire.hpp"
using namespace are::rooms::wire;
int main(int argc,char** argv) {
    try {
        binary_mode();
        if(argc!=4)throw std::runtime_error("USAGE: bio_workrooms workers repeats policy");
        const unsigned workers=bounded(argv[1],1,8),repeats=bounded(argv[2],1,30);
        const auto policy=are::rooms::bio_policy(argv[3]);
        const auto request=read_request(workers);const auto c=request.config;
        const auto& scene=request.scene;const auto count=scene.size();
        std::vector<frozen::are::rooms::Triangle> frozen_scene(count);
        for(std::size_t i=0;i<count;++i){frozen_scene[i].rgba=scene[i].rgba;
            for(unsigned k=0;k<3;++k){const auto& v=scene[i].v[k];frozen_scene[i].v[k]={v.x,v.y,v.z,v.w};}}
        const frozen::are::rooms::Config frozen_config{c.width,c.height,c.tile,c.frame};
        const auto before_baseline=std::chrono::steady_clock::now();
        frozen::are::rooms::Pipeline baseline(frozen_config,frozen_scene,workers);
        const auto baseline_construction_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-before_baseline).count();
        const auto before_candidate=std::chrono::steady_clock::now();
        are::rooms::BioPipeline pipeline(c,scene,workers,policy);
        const auto candidate_construction_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-before_candidate).count();
        frozen::are::rooms::Pipeline reference(frozen_config,frozen_scene,1);reference.execute();
        for(unsigned i=0;i<3;++i){baseline.execute();pipeline.execute();same(reference,baseline);same(reference,pipeline);}
        std::vector<double> milliseconds,cpu_ms,baseline_ms,baseline_cpu_ms;
        auto timed=[](auto& renderer,std::vector<double>& wall,std::vector<double>& cpu) {
            const auto cpu_start=std::clock();const auto start=std::chrono::steady_clock::now();renderer.execute();
            wall.push_back(std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count());
            cpu.push_back(1000.0*double(std::clock()-cpu_start)/CLOCKS_PER_SEC);
        };
        for(unsigned i=0;i<repeats;++i) {
            if(i%2==0){timed(baseline,baseline_ms,baseline_cpu_ms);timed(pipeline,milliseconds,cpu_ms);}
            else{timed(pipeline,milliseconds,cpu_ms);timed(baseline,baseline_ms,baseline_cpu_ms);}
            same(reference,baseline);same(reference,pipeline);
        }
        std::ostringstream receipt;receipt<<std::setprecision(17)
            <<"{\"protocol\":\"are.workrooms.receipt.v1\",\"python_in_runtime\":false,"
            <<"\"workers\":"<<workers<<",\"frame\":"<<c.frame<<",\"triangles\":"<<count
            <<",\"tile\":"<<c.tile<<",\"rooms_executed\":"<<pipeline.room_count()
            <<",\"handoff_ready\":true,\"hardware_gpu_submitted\":false,\"worker_parity\":true,"
            <<"\"policy\":\""<<policy.name<<"\",\"paired_order\":\"alternating-baseline-first\""
            <<",\"baseline_workers\":"<<workers<<",\"baseline_construction_ms\":"<<baseline_construction_ms
            <<",\"candidate_construction_ms\":"<<candidate_construction_ms
            <<",\"spatial_references\":"<<pipeline.spatial_references()
            <<",\"frontier_shared_stage_interval\":"<<(policy.frontier?"true":"false")
            <<",\"warmups\":3,\"baseline_samples_ms\":";values(receipt,baseline_ms);
        receipt<<",\"baseline_cpu_samples_ms\":";values(receipt,baseline_cpu_ms);
        receipt<<",\"samples_ms\":";values(receipt,milliseconds);
        receipt<<",\"cpu_samples_ms\":";values(receipt,cpu_ms);
        append_waves(receipt,pipeline,workers,count);
        write_response(pipeline,request,receipt.str());
        return 0;
    }catch(const std::exception& e){std::cerr<<"NATIVE_REJECTED:"<<e.what()<<'\n';return 2;}
}
