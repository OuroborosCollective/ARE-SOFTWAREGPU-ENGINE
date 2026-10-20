// OuroborosCollective. Repository license applies.
// Experimental native GLB -> raster/depth -> single-origin time-window bridge.
// Strictly one model: deriving ownership from depth for multiple models is unsafe.
// No production path is altered, no cross-frame emitter or queue is introduced.
#include "bio_workrooms.hpp"
#include "model_scene.hpp"
#include "../raster/single_origin_time_window.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <string>
#include <vector>

using namespace are::models;
namespace pulse = are::raster::single_origin;
using Clock = std::chrono::steady_clock;
constexpr std::uint32_t target_owner = 7;
constexpr int ticks = 8;

struct Rendered {
    std::vector<std::uint8_t> rgba;
    std::vector<float> depth; // immutable raw native NDC depth, may be negative
    std::vector<float> effect_depth; // separate [0,1] read-only pulse input
    std::vector<std::uint32_t> owners;
    std::uint64_t sample_writes = 0;
};
std::uint64_t fnv64(const std::vector<std::uint8_t>& bytes) {
    std::uint64_t h=14695981039346656037ull;
    for(const auto byte:bytes) {h^=byte;h*=1099511628211ull;}
    return h;
}
void export_ppm(const std::string& file,const std::vector<std::uint8_t>& rgba,int n) {
    std::ofstream out(file,std::ios::binary);
    if(!out)throw std::runtime_error("GLB_PULSE_EXPORT_OPEN");
    out<<"P6\n"<<n<<" "<<n<<"\n255\n";
    for(std::size_t i=0;i<rgba.size();i+=4)
        out.write(reinterpret_cast<const char*>(rgba.data()+i),3);
    if(!out)throw std::runtime_error("GLB_PULSE_EXPORT_WRITE");
}
double median(std::vector<double> values) {
    if(values.size()!=15)throw std::runtime_error("GLB_PULSE_BENCH_COUNT");
    std::sort(values.begin(),values.end());
    return values[7];
}
void emit_samples(const std::vector<double>& values){
    std::cout<<"[";
    for(std::size_t i=0;i<values.size();++i){
        if(i)std::cout<<",";
        std::cout<<values[i];
    }
    std::cout<<"]";
}
pulse::PulseReceipt apply(Rendered& rendered,int n,double t){
    return pulse::apply_at_time(rendered.rgba.data(),rendered.rgba.size(),
       rendered.effect_depth.data(),rendered.effect_depth.size(),
       rendered.owners.data(),rendered.owners.size(),n,n,n/2,n/2,
       {3.,0.,0.},8.,1.,48.,t,1.,target_owner,true);
}
int main(int argc,char** argv) {try{
    are::rooms::wire::binary_mode();
    are::require_environment();
    need(argc==4,"GLB_PULSE_USAGE: request.aremdl workers frames-directory");
    const unsigned workers=are::rooms::wire::bounded(argv[2],1,4);
    Scene scene(argv[1],workers);
    // Depth-derived ownership is valid only when one model is admitted;
    // do not infer per-model ownership from depth in multi-instance scenes.
    need(scene.models.size()==1,"GLB_PULSE_SINGLE_OWNER_REQUIRED");
    need(!scene.pbr&&!scene.perspective,"GLB_PULSE_DIAGNOSTIC_ONLY");
    need(scene.config.width==128&&scene.config.height==128&&
         scene.times.size()==ticks,"GLB_PULSE_FRAME_CONTRACT");
    for(int t=0;t<ticks;++t)
        need(scene.times[std::size_t(t)]==double(t),"GLB_PULSE_FRAME_CONTRACT");
    need(scene.source_triangles>0&&scene.source_triangles<=100000,
         "GLB_PULSE_TRIANGLE_BUDGET");
    scene.fit();scene.frame(scene.times.front());
    are::rooms::Pipeline renderer(scene.config,scene.triangles,workers,
                                  are::rooms::Admission::model_probe);
    const int n=int(scene.config.width);
    auto render=[&](double time)->Rendered {
        scene.frame(time);
        renderer.update_scene(scene.triangles);
        renderer.execute();
        Rendered out;
        out.rgba=renderer.rgba();
        out.depth=renderer.depth();
        out.effect_depth.resize(out.depth.size());
        out.owners.assign(out.depth.size(),0);
        out.sample_writes=renderer.waves()[1].samples;
        need(out.sample_writes>0,"GLB_PULSE_RASTER_EMPTY");
        for(std::size_t i=0;i<out.depth.size();++i){
            // Native diagnostic MSAA depth is NDC [-1,1], while the
            // pulse preflight intentionally requires [0,1]. Keep both.
            // Depth=1 is untouched background; strict-less native winners
            // remain strict-less after this monotone viewport mapping.
            const float z=out.depth[i];
            need(std::isfinite(z)&&z>=-1.0f&&z<=1.0f,
                 "GLB_PULSE_NATIVE_DEPTH_INVALID");
            if(z<1.0f){
                out.owners[i]=target_owner;
                out.effect_depth[i]=std::min((z+1.0f)*0.5f,
                                              std::nextafter(1.0f,0.0f));
            }else out.effect_depth[i]=1.0f;
        }
        return out;
    };
    const std::array<std::size_t,ticks> expected{{1,196,600,996,1416,1816,2188,0}};
    std::size_t total_areas=0, total_tinted=0;
    std::vector<unsigned> arrived(std::size_t(n)*n,0);
    for(int t=0;t<ticks;++t){
        const auto pristine=render(double(t));
        auto colored=pristine;
        auto replay=pristine;
        const auto receipt=apply(colored,n,double(t));
        const auto replay_receipt=apply(replay,n,double(t));
        need(colored.rgba==replay.rgba&&receipt.event_fingerprint==replay_receipt.event_fingerprint,
             "GLB_PULSE_NONDETERMINISTIC");
        need(receipt.area_completions==expected[std::size_t(t)]&&
             receipt.spherepop_starts==1&&receipt.queue_pushes==0&&
             receipt.reemissions==0&&receipt.refusals==0,"GLB_PULSE_ARRIVAL_CONTRACT");
        const bool depth_equal=
            std::memcmp(pristine.depth.data(),colored.depth.data(),
                        pristine.depth.size()*sizeof(float))==0 &&
            std::memcmp(pristine.effect_depth.data(),colored.effect_depth.data(),
                        pristine.effect_depth.size()*sizeof(float))==0;
        bool alpha_equal=true,background_preserved=true;
        for(std::size_t i=0;i<pristine.depth.size();++i){
            const int x=int(i%std::size_t(n)),y=int(i/std::size_t(n));
            const double distance=std::hypot(double(x-n/2),double(y-n/2));
            const double arrival=distance/8.;
            const bool active=distance<=48.&&arrival<=double(t)&&
                              (t==0||arrival>double(t)-1.);
            if(active)++arrived[i];
            if(pristine.rgba[i*4+3]!=colored.rgba[i*4+3])alpha_equal=false;
            if((!active||pristine.owners[i]!=target_owner)&&
               !std::equal(pristine.rgba.begin()+i*4,pristine.rgba.begin()+i*4+4,
                           colored.rgba.begin()+i*4))background_preserved=false;
        }
        need(alpha_equal&&depth_equal&&background_preserved,
             "GLB_PULSE_DEPTH_ALPHA_OWNER_REGRESSION");
        export_ppm(std::string(argv[3])+"/base-"+std::to_string(t)+".ppm",pristine.rgba,n);
        export_ppm(std::string(argv[3])+"/wave-"+std::to_string(t)+".ppm",colored.rgba,n);
        total_areas+=receipt.area_completions;
        total_tinted+=receipt.tinted_pixels;
        std::cout<<"GLB_PULSE_FRAME {\"tick\":"<<t
                 <<",\"triangles\":"<<scene.source_triangles
                 <<",\"raster_writes\":"<<pristine.sample_writes
                 <<",\"area_completions\":"<<receipt.area_completions
                 <<",\"tinted_pixels\":"<<receipt.tinted_pixels
                 <<",\"baseline_fnv64\":"<<fnv64(pristine.rgba)
                 <<",\"wave_fnv64\":"<<fnv64(colored.rgba)
                 <<",\"event_fingerprint\":"<<receipt.event_fingerprint
                 <<",\"alpha_equal\":true,\"depth_equal\":true"
                 <<",\"replay_equal\":true,\"background_preserved\":true"
                 <<",\"reemissions\":"<<receipt.reemissions
                 <<",\"queue_pushes\":"<<receipt.queue_pushes<<"}\n";
    }
    std::size_t circle=0;
    for(int y=0;y<n;++y)for(int x=0;x<n;++x){
        const auto i=std::size_t(y)*n+x;
        const bool within=std::hypot(double(x-n/2),double(y-n/2))<=48.;
        circle+=within;
        need(arrived[i]==unsigned(within),"GLB_PULSE_DOUBLE_ARRIVAL");
    }
    need(total_areas==7213&&circle==total_areas&&total_tinted>0,
         "GLB_PULSE_SEQUENCE_EMPTY");
    // Complete geometry+native raster+post-effect is timed. Each draw starts
    // from a pristine newly rasterized frame, never cumulative wave history.
    std::vector<double> baseline,with_wave;
    for(int rep=-2;rep<15;++rep)for(int slot=0;slot<2;++slot){
        const int mode=(rep%2==0)?slot:1-slot;
        const auto start=Clock::now();
        auto frame=render(2.);
        if(mode==1){
            const auto receipt=apply(frame,n,2.);
            need(receipt.area_completions==600&&receipt.tinted_pixels>0,
                 "GLB_PULSE_BENCH_CONTRACT");
        }
        const double milliseconds=std::chrono::duration<double,std::milli>(
                    Clock::now()-start).count();
        need(std::isfinite(milliseconds)&&milliseconds>0,"GLB_PULSE_BENCH_TIME");
        if(rep>=0)(mode==0?baseline:with_wave).push_back(milliseconds);
    }
    need(baseline.size()==15&&with_wave.size()==15,"GLB_PULSE_BENCH_COUNT");
    std::cout<<std::fixed<<std::setprecision(9)
             <<"GLB_PULSE_BENCH {\"workers\":"<<workers
             <<",\"triangles\":"<<scene.source_triangles
             <<",\"pairs\":15,\"median_baseline_ms\":"<<median(baseline)
             <<",\"median_wave_ms\":"<<median(with_wave)
             <<",\"raw_baseline_ms\":";
    emit_samples(baseline);
    std::cout<<",\"raw_wave_ms\":";
    emit_samples(with_wave);
    std::cout<<"}\nGLB_PULSE_NATIVE_PASS\n";
    return 0;
}catch(const std::exception& e){
    std::cerr<<"NATIVE_REJECTED:"<<e.what()<<'\n';
    return 2;
}}
