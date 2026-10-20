// RED->GREEN: real native C++17 raster and strictly equivalent Doppler-factor reuse.
// No synthetic timings or mock draw. Compares prior implementation with opt-in
// fused pixel tint while preserving WaveArea, ownership, depth and event order.
#include "core.hpp"
#include "spherepop_cag_radial_wave.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace wave=are::raster::experimental;

struct Frame {
    std::vector<std::uint8_t> rgba;
    std::vector<float> depth;
    wave::WaveReceipt receipt;
};
static std::array<double,46> square(int pixels) {
    std::array<double,46> packed{};
    auto triangle=[&](int index,const std::array<double,6>& xy) {
        double* p=packed.data()+index*23;
        for(int v=0;v<3;++v) {
            p[v*3]=xy[2*v];
            p[v*3+1]=xy[2*v+1];
            p[v*3+2]=0.5;
            p[9+v]=1.;
            p[13+v*3]=.5;
            p[14+v*3]=.4;
            p[15+v*3]=.35;
        }
        p[12]=1.0/double(pixels*pixels);
    };
    triangle(0,{0.,0.,0.,double(pixels),double(pixels),0.});
    triangle(1,{double(pixels),double(pixels),double(pixels),0.,0.,double(pixels)});
    return packed;
}
static Frame draw_and_wave(int pixels,const std::array<double,46>& mesh,
                           wave::Vec3 velocity,int cx,int cy,
                           bool with_doppler,bool reuse_factor) {
    const auto cells=std::size_t(pixels)*pixels;
    Frame result{};
    result.rgba.assign(cells*4,0);
    result.depth.assign(cells,1.0f);
    std::array<std::uint64_t,3> counts{};
    assert(are::raster::draw(mesh.data(),mesh.size(),2,pixels,pixels,
           result.rgba.data(),result.rgba.size(),result.depth.data(),
           result.depth.size(),counts.data(),counts.size())==are::raster::ok);
    assert(counts[2]>0);
    std::vector<std::uint32_t> owners(cells,0);
    for(std::size_t i=0;i<cells;++i) {
        if(result.depth[i]<1.0f && i%17!=0)owners[i]=7;
    }
    if(reuse_factor) std::cerr<<"FACTOR_REUSE_REQUEST_AT_CALL "<<reuse_factor<<"\n";
    result.receipt=wave::render_radial_cag_spherepop(
        result.rgba.data(),result.rgba.size(),result.depth.data(),result.depth.size(),
        owners.data(),owners.size(),pixels,pixels,cx,cy,velocity,120.,1.,
        with_doppler,reuse_factor);
    if(reuse_factor) std::cerr<<"FACTOR_REUSE_RETURN_RECORDED "<<result.receipt.reuse_requested<<" CELLS "<<result.receipt.reused_visible_cells<<"\n";
    return result;
}
static void verify_equal(const Frame& reference,const Frame& candidate,int pixels,
                         bool with_doppler,int cx,int cy) {
    const auto cells=std::size_t(pixels)*pixels;
    assert(reference.rgba==candidate.rgba && reference.depth==candidate.depth);
    const auto& a=reference.receipt;
    const auto& b=candidate.receipt;
    assert(a.finalized.size()==cells && b.finalized.size()==cells);
    assert(a.refusals==b.refusals && a.refusals>0);
    assert(a.tinted_pixels==b.tinted_pixels);
    assert(a.event_fingerprint==b.event_fingerprint);
    std::vector<std::uint8_t> visited(cells,0);
    std::size_t eligible=0;
    const auto seed=std::size_t(cy)*pixels+cx;
    for(std::size_t k=0;k<cells;++k) {
        const auto& x=a.finalized[k];
        const auto& y=b.finalized[k];
        assert(x.area==y.area && x.emitter==y.emitter);
        assert(x.owner==y.owner && x.tinted==y.tinted);
        assert(std::memcmp(&x.doppler,&y.doppler,sizeof(double))==0);
        assert(std::memcmp(&x.arrival_seconds,&y.arrival_seconds,sizeof(double))==0);
        assert(x.area<cells && visited[x.area]++==0);
        eligible+=(x.area!=seed && x.owner!=0);
    }
    for(auto v:visited)assert(v==1);
    if(with_doppler) {
        std::size_t wave_edges=0;
        for(const auto& event:a.finalized) wave_edges+=(event.area!=event.emitter);
        if(b.doppler_factor_evaluations!=wave_edges ||
           a.doppler_factor_evaluations!=wave_edges+eligible) {
            std::cerr<<"SPHEREPOP_FACTOR_COUNT_DIAGNOSTIC expected="
                <<wave_edges<<" extra="<<eligible
                <<" legacy="<<a.doppler_factor_evaluations
                <<" reused="<<b.doppler_factor_evaluations
                <<" request="<<b.reuse_requested
                <<" reused_branch="<<b.reused_visible_cells
                <<" legacy_branch="<<a.reused_visible_cells
                <<" pixels="<<pixels<<"\n";
        }
        assert(wave_edges==cells-1);
        assert(b.doppler_factor_evaluations==wave_edges);
        assert(a.doppler_factor_evaluations==wave_edges+eligible);
    } else {
        assert(a.doppler_factor_evaluations==0);
        assert(b.doppler_factor_evaluations==0);
        assert(a.tinted_pixels==0);
    }
}
static double median(std::vector<double> values) {
    assert(!values.empty());
    std::sort(values.begin(),values.end());
    return values[values.size()/2];
}
static void print_values(const std::vector<double>& v) {
    std::cout<<"[";
    for(std::size_t i=0;i<v.size();++i) {
        if(i)std::cout<<",";
        std::cout<<v[i];
    }
    std::cout<<"]";
}
static void measure(int pixels) {
    const auto mesh=square(pixels);
    const int cx=pixels/2,cy=pixels/2;
    // Prove exact equivalence on different velocities, seeds and no-Doppler.
    for(const auto vel: {wave::Vec3{30.,0.,0.},wave::Vec3{0.,30.,0.},
                         wave::Vec3{-20.,15.,0.},wave::Vec3{0.,0.,0.}}) {
        for(const std::pair<int,int> seed: {std::pair<int,int>{cx,cy},{3,4}}) {
            for(bool with_doppler: {true,false}) {
                const auto a=draw_and_wave(pixels,mesh,vel,seed.first,seed.second,
                                           with_doppler,false);
                const auto b=draw_and_wave(pixels,mesh,vel,seed.first,seed.second,
                                           with_doppler,true);
                verify_equal(a,b,pixels,with_doppler,seed.first,seed.second);
            }
        }
    }
    const auto legacy=draw_and_wave(pixels,mesh,{30.,0.,0.},cx,cy,true,false);
    const auto optimized=draw_and_wave(pixels,mesh,{30.,0.,0.},cx,cy,true,true);
    verify_equal(legacy,optimized,pixels,true,cx,cy);
    const auto draw_no_effect=[&](){
        std::vector<std::uint8_t> rgba(std::size_t(pixels)*pixels*4,0);
        std::vector<float> depth(std::size_t(pixels)*pixels,1.f);
        std::array<std::uint64_t,3> counts{};
        assert(are::raster::draw(mesh.data(),mesh.size(),2,pixels,pixels,
               rgba.data(),rgba.size(),depth.data(),depth.size(),
               counts.data(),counts.size())==are::raster::ok);
        return std::pair<std::vector<std::uint8_t>,std::vector<float>>{
            std::move(rgba),std::move(depth)};
    };
    const auto bare=draw_no_effect();
    assert(bare.second==legacy.depth);
    for(std::size_t i=0;i<legacy.depth.size();++i) {
        assert(legacy.rgba[i*4+3]==bare.first[i*4+3]);
    }
    // Invalid inputs must fail closed in both implementations.
    for(bool reuse: {false,true}) {
        std::vector<std::uint8_t> rgba=bare.first;
        std::vector<float> invalid=bare.second;
        invalid[0]=std::numeric_limits<float>::quiet_NaN();
        std::vector<std::uint32_t> owners(invalid.size(),7);
        bool rejected=false;
        try {
            (void)wave::render_radial_cag_spherepop(
                rgba.data(),rgba.size(),invalid.data(),invalid.size(),
                owners.data(),owners.size(),pixels,pixels,cx,cy,
                {30.,0.,0.},120.,1.,true,reuse);
        } catch(const std::invalid_argument& e) {
            rejected=(std::string(e.what())=="SPHEREPOP_WAVE_SCENE_INVALID");
        }
        assert(rejected && rgba==bare.first);
    }
    // 15 alternating full native draws. Framebuffer clear and scene setup
    // are identical; measured work includes the actual raster and effect.
    std::array<std::vector<double>,2> samples{};
    using clock=std::chrono::steady_clock;
    for(int repeat=-2;repeat<15;++repeat) {
        for(int pass=0;pass<2;++pass) {
            const bool reuse=(pass==(repeat%2==0?0:1));
            const auto begin=clock::now();
            auto frame=draw_and_wave(pixels,mesh,{30.,0.,0.},cx,cy,true,reuse);
            const auto elapsed=std::chrono::duration<double,std::milli>(
                clock::now()-begin).count();
            assert(std::isfinite(elapsed) && elapsed>0);
            verify_equal(legacy,frame,pixels,true,cx,cy);
            if(repeat>=0)samples[reuse?1:0].push_back(elapsed);
        }
    }
    assert(samples[0].size()==15 && samples[1].size()==15);
    std::vector<double> ratios;
    for(std::size_t i=0;i<15;++i) ratios.push_back(samples[0][i]/samples[1][i]);
    std::cout<<std::fixed<<std::setprecision(9);
    std::cout<<"SPHEREPOP_FACTOR_REUSE_RECEIPT {\"pixels\":"<<pixels
        <<",\"pairs\":15,\"triangles\":2,\"head_only\":\"CI_SHA_BOUND\""
        <<",\"same_rgba_depth_history\":true"
        <<",\"old_factor_evaluations\":"<<legacy.receipt.doppler_factor_evaluations
        <<",\"new_factor_evaluations\":"<<optimized.receipt.doppler_factor_evaluations
        <<",\"refusals\":"<<optimized.receipt.refusals
        <<",\"tinted\":"<<optimized.receipt.tinted_pixels
        <<",\"event_fingerprint\":"<<optimized.receipt.event_fingerprint
        <<",\"median_legacy_ms\":"<<median(samples[0])
        <<",\"median_reuse_ms\":"<<median(samples[1])
        <<",\"median_paired_speedup\":"<<median(ratios)
        <<",\"raw_ms\":{\"legacy\":";
    print_values(samples[0]);
    std::cout<<",\"reuse\":";
    print_values(samples[1]);
    std::cout<<"}}\n";
}
int main() {
    measure(32);
    measure(64);
    std::cout<<"SPHEREPOP_FACTOR_REUSE_NATIVE_PASS\n";
}
