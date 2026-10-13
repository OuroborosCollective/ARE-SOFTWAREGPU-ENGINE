// OuroborosCollective. Experimental bounded native RGBA frame source for CPU streaming.
// Compiled only with -DARE_STREAM_PROBE=1. This is NOT a GLB/PBR or WebRTC test.
#ifndef ARE_STREAM_PROBE
#error Compile with ARE_STREAM_PROBE=1; production renderer is unchanged.
#endif
#include "workrooms_wire.hpp"
#include <chrono>
#include <cstdio>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

using Clock=std::chrono::steady_clock;
using namespace are::rooms;
namespace {
double ms(Clock::time_point start) {
    return std::chrono::duration<double,std::milli>(Clock::now()-start).count();
}
Triangle tri(float x0,float y0,float x1,float y1,float x2,float y2,
             std::array<std::uint8_t,4> rgba,float z=0.3f) {
    // Flip the second point to preserve CCW screen-space raster winding.
    Triangle t{};
    t.v={{{x0,y0,z,1.0f},{x1,y1,z,1.0f},{x2,y2,z,1.0f}}};
    t.rgba=rgba;
    return t;
}
std::vector<Triangle> scene(unsigned frame,unsigned frames) {
    // Deterministic finite clip-space geometry. Genuine native rasterization,
    // deliberately not represented as imported GLB or cinematic content.
    const float shift=0.17f*std::sin(6.2831853071795864769f*float(frame)/float(frames));
    const float opposite=0.11f*std::cos(6.2831853071795864769f*float(frame)/float(frames));
    std::vector<Triangle> out;
    out.reserve(12);
    const std::array<std::array<std::uint8_t,4>,6> colors{{{{215,75,85,255}},
      {{70,190,240,255}},{{230,185,66,255}},{{110,225,135,255}},
      {{175,105,225,255}},{{200,160,115,255}}}};
    for(unsigned row=0;row<2;++row)for(unsigned col=0;col<3;++col) {
        const float x=-0.80f+0.53f*float(col)+(row?opposite:shift);
        const float y=-0.55f+0.62f*float(row);
        // Screen-space CCW winding after the glTF clip-to-screen Y flip.
        out.push_back(tri(x,y,x+0.17f,y+0.37f,x+0.35f,y,colors[row*3+col]));
        out.push_back(tri(x,y-0.10f,x+0.15f,y+0.15f,x+0.30f,y-0.10f,
                          colors[row*3+col],0.38f));
    }
    return out;
}
std::string u64hex(std::uint64_t x) {
    std::ostringstream out;out<<std::hex<<std::setw(16)<<std::setfill('0')<<x;
    return out.str();
}
std::uint64_t fnv(std::uint64_t h,const std::vector<std::uint8_t>& frame) {
    for(std::uint8_t b:frame){h^=b;h*=1099511628211ull;}return h;
}
}

int main(int argc,char** argv) {
    try {
        are::require_environment();
        if(argc!=5)throw std::runtime_error("STREAM_USAGE: width height frames workers");
        const auto width=are::rooms::wire::bounded(argv[1],640,1280);
        const auto height=are::rooms::wire::bounded(argv[2],360,720);
        const auto frames=are::rooms::wire::bounded(argv[3],2,30);
        const auto workers=are::rooms::wire::bounded(argv[4],1,8);
        if(!((width==640&&height==360)||(width==1280&&height==720)))
            throw std::runtime_error("STREAM_SIZE_PRESET");
        const Config config{width,height,32,0};
        auto triangles=scene(0,frames);
        Pipeline pipeline(config,triangles,workers,Admission::stream_probe);
        Pipeline reference(config,triangles,1,Admission::stream_probe);
        const auto construct=Clock::now();
        for(int w=0;w<3;++w)pipeline.execute();
        const double warmup_ms=ms(construct);
        std::vector<double> render_ms,write_ms;
        render_ms.reserve(frames);write_ms.reserve(frames);
        std::uint64_t hash=14695981039346656037ull;
        std::uint64_t samples=0;
        unsigned parity_frames=0;
        for(unsigned i=0;i<frames;++i){
            triangles=scene(i,frames);
            pipeline.update_scene(triangles);
            const auto started=Clock::now();
            pipeline.execute();
            render_ms.push_back(ms(started));
            const auto& bytes=pipeline.rgba();
            if(bytes.size()!=std::size_t(width)*height*4)throw std::runtime_error("STREAM_FRAME_SIZE");
            if(i==0 || i+1==frames){
                reference.update_scene(triangles);
                reference.execute();
                if(reference.rgba()!=pipeline.rgba()||
                   reference.resolved()!=pipeline.resolved()||
                   std::memcmp(reference.depth().data(),pipeline.depth().data(),
                               pipeline.depth().size()*sizeof(float))!=0)
                    throw std::runtime_error("STREAM_NATIVE_PARITY");
                ++parity_frames;
            }
            hash=fnv(hash,bytes);
            samples+=pipeline.waves()[1].samples;
            const auto writer=Clock::now();
            if(std::fwrite(bytes.data(),1,bytes.size(),stdout)!=bytes.size())
                throw std::runtime_error("STREAM_PIPE_CLOSED");
            write_ms.push_back(ms(writer));
        }
        if(std::fflush(stdout)!=0)throw std::runtime_error("STREAM_PIPE_FLUSH");
        const auto counts=[](const auto& values) {
            std::ostringstream s;
            s<<std::setprecision(12)<<'[';
            for(std::size_t i=0;i<values.size();++i){if(i)s<<',';s<<values[i];}
            return s.str()+']';
        };
        std::ostringstream report;
        report<<std::setprecision(12)
            <<"{\"protocol\":\"are.native-stream-probe.v1\",\"status\":\"PASS\","
            <<"\"source_kind\":\"native-deterministic-geometry-fixture\","
            <<"\"renderer\":\"are-cxx17-pipeline\",\"pbr\":false,\"glb\":false,"
            <<"\"video_encoded_in_native\":false,\"hardware_gpu_submitted\":false,"
            <<"\"width\":"<<width<<",\"height\":"<<height<<",\"workers\":"<<workers
            <<",\"frames\":"<<frames<<",\"warmups\":3,\"warmup_ms\":"<<warmup_ms
            <<",\"parity_reference_frames\":"<<parity_frames
            <<",\"input_triangles\":"<<triangles.size()
            <<",\"pixel_samples_written\":"<<samples
            <<",\"raw_bytes\":"<<std::uint64_t(width)*height*frames*4ull
            <<",\"frame_fnv64\":\""<<u64hex(hash)<<"\""
            <<",\"render_ms\":"<<counts(render_ms)
            <<",\"pipe_write_ms\":"<<counts(write_ms)
            <<"}";
        std::cerr<<"ARE_STREAM_NATIVE_RECEIPT "<<report.str()<<'\n';
        return 0;
    } catch(const std::exception& e) {
        std::cerr<<"NATIVE_STREAM_REJECTED:"<<e.what()<<'\n';return 2;
    }
}
