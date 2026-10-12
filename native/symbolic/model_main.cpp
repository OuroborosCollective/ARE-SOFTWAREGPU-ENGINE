// Standalone C++17 model/animation/scene measurement. No Python callbacks.
#include "bio_workrooms.hpp"
#include "model_scene.hpp"
#include <ctime>
#include <iomanip>
using namespace are::models;
using Clock=std::chrono::steady_clock;
inline double elapsed(Clock::time_point t){return std::chrono::duration<double,std::milli>(Clock::now()-t).count();}
struct Timing{std::vector<double> total,geometry,render,cpu;};
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
    auto run=[&](auto& renderer,Timing& timing,double time){const auto cpu=std::clock();const auto t=Clock::now();scene.frame(time);const auto g=elapsed(t);
        renderer.update_scene(scene.triangles);renderer.execute();const auto wall=elapsed(t);timing.total.push_back(wall);timing.geometry.push_back(g);timing.render.push_back(wall-g);
        timing.cpu.push_back(1000.0*double(std::clock()-cpu)/CLOCKS_PER_SEC);};
    for(unsigned i=0;i<repeats;++i){const auto time=scene.times[i%scene.times.size()];
        if(i%2==0){run(baseline,b,time);run(candidate,c,time);}else{run(candidate,c,time);run(baseline,b,time);}
        are::rooms::wire::same(baseline,candidate);frames.push_back(candidate.rgba());writes.push_back(candidate.waves()[1].samples);
    }
    std::ostringstream out;out<<std::setprecision(17)<<"{\"protocol\":\"are.model-probe.receipt.v1\",\"python_in_runtime\":false,\"hardware_gpu_submitted\":false,\"full_buffer_parity\":true,\"serial_reference_first_frame\":true,\"warmups\":3,\"workers\":"<<workers
        <<",\"triangles\":"<<scene.triangles.size()<<",\"vertices\":"<<scene.vertices<<",\"models\":"<<scene.models.size()<<",\"policy\":\""<<policy.name<<"\",\"construction_fit_and_serial_reference_ms\":"<<construction_ms<<",\"spatial_references\":"<<candidate.spatial_references();
    auto times=[&](const char*prefix,const Timing& t){for(const auto& kv:std::array<std::pair<const char*,const std::vector<double>*>,4>{{{"total_ms",&t.total},{"geometry_ms",&t.geometry},{"render_ms",&t.render},{"cpu_ms",&t.cpu}}}){
        out<<",\""<<prefix<<kv.first<<"\":";are::rooms::wire::values(out,*kv.second);}};
    times("baseline_",b);times("candidate_",c);out<<",\"sample_writes\":[";for(unsigned i=0;i<writes.size();++i){if(i)out<<',';out<<writes[i];}out<<"]}";
    const auto json=out.str();std::cout.write("AREMOUT1",8);are::rooms::wire::write32(scene.config.width);are::rooms::wire::write32(scene.config.height);are::rooms::wire::write32(unsigned(frames.size()));
    are::rooms::wire::write32(unsigned(json.size()));std::cout.write(json.data(),json.size());for(const auto& f:frames)std::cout.write(reinterpret_cast<const char*>(f.data()),f.size());
    std::cout.write(reinterpret_cast<const char*>(candidate.resolved().data()),candidate.resolved().size());for(auto z:candidate.depth())are::rooms::wire::write32(are::bits(z));
    need(bool(std::cout),"MODEL_OUTPUT");return 0;
}catch(const std::exception&e){std::cerr<<"NATIVE_REJECTED:"<<e.what()<<'\n';return 2;}}
