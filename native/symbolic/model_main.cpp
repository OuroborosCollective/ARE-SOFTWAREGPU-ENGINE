// Standalone C++17 model/animation/scene measurement. No Python callbacks.
#include "bio_workrooms.hpp"
#include "model_scene.hpp"
#include <ctime>
#include <iomanip>
using namespace are::models;
using Clock=std::chrono::steady_clock;
inline double elapsed(Clock::time_point t){return std::chrono::duration<double,std::milli>(Clock::now()-t).count();}
struct FrameTiming {
    double animated_pose_ms=0,static_pose_ms=0,triangle_prepare_ms=0,handoff_ms=0;
    double render_setup_ms=0,rasterization_ms=0,msaa_ms=0,aa_ms=0,scheduler_binning_ms=0,total_ms=0;
    double render_setup_work_ms=0,rasterization_work_ms=0,msaa_work_ms=0,aa_work_ms=0;
};
struct Timing{std::vector<double> total,geometry,render,cpu;std::vector<FrameTiming> frames;};
int main(int argc,char**argv){try{
    are::rooms::wire::binary_mode();are::require_environment();need(argc==6,"USAGE: model input workers repeats policy render|pose");
    const auto workers=are::rooms::wire::bounded(argv[2],1,8),repeats=are::rooms::wire::bounded(argv[3],1,30);
    const auto policy=are::rooms::bio_policy(argv[4]);const std::string mode=argv[5];need(mode=="render"||mode=="pose","MODEL_MODE");
    const auto start=Clock::now();Scene scene(argv[1],workers);
    if(mode=="pose"){
        need(scene.vertices*scene.times.size()<=16000000,"MODEL_POSE_OUTPUT_BUDGET");std::cout.write("AREPOSE1",8);
        are::rooms::wire::write32(unsigned(scene.times.size()));are::rooms::wire::write32(unsigned(scene.models.size()));
        for(double t:scene.times)for(auto&m:scene.models){m.raw_pose(t);are::rooms::wire::write32(unsigned(m.posed.size()));
            std::cout.write(reinterpret_cast<const char*>(m.posed.data()),m.posed.size()*sizeof(V3));}
        need(bool(std::cout),"MODEL_OUTPUT");return 0;
    }
    scene.fit();scene.frame(scene.times[0]);
    std::vector<std::uint8_t> ref_rgba,ref_resolved;std::vector<float> ref_depth;
    {are::rooms::Pipeline ref(scene.config,scene.triangles,1,are::rooms::Admission::model_probe);ref.execute();ref_rgba=ref.rgba();ref_resolved=ref.resolved();ref_depth=ref.depth();}
    are::rooms::Pipeline baseline(scene.config,scene.triangles,workers,are::rooms::Admission::model_probe);
    are::rooms::BioPipeline candidate(scene.config,scene.triangles,workers,policy,are::rooms::Admission::model_probe);
    const auto construction_ms=elapsed(start);
    for(int w=0;w<3;++w){baseline.execute();candidate.execute();are::rooms::wire::same(baseline,candidate);
        need(baseline.rgba()==ref_rgba&&baseline.resolved()==ref_resolved&&std::memcmp(baseline.depth().data(),ref_depth.data(),ref_depth.size()*4)==0,"MODEL_SERIAL_REFERENCE");}
    Timing b,c;std::vector<std::vector<std::uint8_t>> frames;std::vector<std::uint64_t> writes;
    auto run=[&](auto& renderer,Timing& timing,double time,bool bio_scheduler){
        const auto cpu=std::clock();const auto t=Clock::now();FrameProfile profile;FrameTiming detail;
        scene.frame(time,&profile);detail.animated_pose_ms=profile.animated_pose_ms;
        detail.static_pose_ms=profile.static_pose_ms;detail.triangle_prepare_ms=profile.triangle_prepare_ms;
        const auto g=elapsed(t);const auto handoff=Clock::now();renderer.update_scene(scene.triangles);
        detail.handoff_ms=elapsed(handoff);renderer.execute();detail.total_ms=elapsed(t);
        detail.render_setup_ms=renderer.waves()[0].milliseconds;
        detail.rasterization_ms=renderer.waves()[1].milliseconds;
        detail.msaa_ms=renderer.waves()[2].milliseconds;detail.aa_ms=renderer.waves()[3].milliseconds;
        const auto work=renderer.stage_work_ms();detail.render_setup_work_ms=work[0];detail.rasterization_work_ms=work[1];
        detail.msaa_work_ms=work[2];detail.aa_work_ms=work[3];
        detail.scheduler_binning_ms=bio_scheduler?candidate.binning_ms():0;
        timing.total.push_back(detail.total_ms);timing.geometry.push_back(g);
        timing.render.push_back(detail.total_ms-g);
        timing.cpu.push_back(1000.0*double(std::clock()-cpu)/CLOCKS_PER_SEC);timing.frames.push_back(detail);
    };
    for(unsigned i=0;i<repeats;++i){const auto time=scene.times[i%scene.times.size()];
        if(i%2==0){run(baseline,b,time,false);run(candidate,c,time,true);}
        else{run(candidate,c,time,true);run(baseline,b,time,false);}
        are::rooms::wire::same(baseline,candidate);frames.push_back(candidate.rgba());writes.push_back(candidate.waves()[1].samples);
    }
    std::ostringstream out;out<<std::setprecision(17)<<"{\"protocol\":\"are.model-probe.receipt.v1\",\"python_in_runtime\":false,\"hardware_gpu_submitted\":false,\"full_buffer_parity\":true,\"serial_reference_first_frame\":true,\"warmups\":3,\"workers\":"<<workers
        <<",\"triangles\":"<<scene.triangles.size()<<",\"vertices\":"<<scene.vertices<<",\"models\":"<<scene.models.size()<<",\"policy\":\""<<policy.name<<"\",\"construction_fit_and_serial_reference_ms\":"<<construction_ms<<",\"spatial_references\":"<<candidate.spatial_references()
        <<",\"stage_timing_clock\":\"steady_clock\",\"stage_timing_semantics\":\"per-frame wall intervals; scheduler stage durations include scheduling and synchronization; bio frontier rasterization_ms, msaa_ms, and aa_ms report the same overlapping shared frontier interval and must not be summed\"";
    auto times=[&](const char*prefix,const Timing& t){for(const auto& kv:std::array<std::pair<const char*,const std::vector<double>*>,4>{{{"total_ms",&t.total},{"geometry_ms",&t.geometry},{"render_ms",&t.render},{"cpu_ms",&t.cpu}}}){
        out<<",\""<<prefix<<kv.first<<"\":";are::rooms::wire::values(out,*kv.second);}};
    auto detailed=[&](const char*name,const Timing& t){out<<",\""<<name<<"\":[";
        for(std::size_t i=0;i<t.frames.size();++i){if(i)out<<',';const auto& f=t.frames[i];
            out<<"{\"frame\":"<<i<<",\"animated_pose_ms\":"<<f.animated_pose_ms<<",\"static_pose_ms\":"<<f.static_pose_ms
               <<",\"triangle_prepare_ms\":"<<f.triangle_prepare_ms<<",\"handoff_ms\":"<<f.handoff_ms
               <<",\"render_setup_ms\":"<<f.render_setup_ms<<",\"rasterization_ms\":"<<f.rasterization_ms
               <<",\"msaa_ms\":"<<f.msaa_ms<<",\"aa_ms\":"<<f.aa_ms
               <<",\"render_setup_worker_work_ms\":"<<f.render_setup_work_ms<<",\"rasterization_worker_work_ms\":"<<f.rasterization_work_ms
               <<",\"msaa_worker_work_ms\":"<<f.msaa_work_ms<<",\"aa_worker_work_ms\":"<<f.aa_work_ms
               <<",\"scheduler_binning_ms\":"<<f.scheduler_binning_ms<<",\"frame_total_ms\":"<<f.total_ms<<"}";
        }out<<']';};
    times("baseline_",b);times("candidate_",c);detailed("baseline_frame_timings",b);detailed("candidate_frame_timings",c);
    out<<",\"sample_writes\":[";for(unsigned i=0;i<writes.size();++i){if(i)out<<',';out<<writes[i];}out<<"]}";
    const auto json=out.str();std::cout.write("AREMOUT1",8);are::rooms::wire::write32(scene.config.width);are::rooms::wire::write32(scene.config.height);are::rooms::wire::write32(unsigned(frames.size()));
    are::rooms::wire::write32(unsigned(json.size()));std::cout.write(json.data(),json.size());for(const auto& f:frames)std::cout.write(reinterpret_cast<const char*>(f.data()),f.size());
    std::cout.write(reinterpret_cast<const char*>(candidate.resolved().data()),candidate.resolved().size());for(auto z:candidate.depth())are::rooms::wire::write32(are::bits(z));
    need(bool(std::cout),"MODEL_OUTPUT");return 0;
}catch(const std::exception&e){std::cerr<<"NATIVE_REJECTED:"<<e.what()<<'\n';return 2;}}
