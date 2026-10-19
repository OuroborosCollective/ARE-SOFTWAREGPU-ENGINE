// Actual native C++17 raster -> CAG point -> radial SpherePop/Doppler effect.
#include "core.hpp"
#include "spherepop_cag_radial_wave.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
using namespace are::raster::experimental;
template<typename F> void reject(F f,const char* message) {
    bool caught=false;
    try{f();}catch(const std::invalid_argument& e){caught=true; assert(std::string(e.what())==message);}
    assert(caught);
}
int main() {
    constexpr int width=7,height=9;
    std::array<std::uint8_t,width*height*4> rgba{};
    std::array<float,width*height> depth{};
    depth.fill(1.f);
    std::array<std::uint32_t,width*height> owner{};
    std::array<std::uint64_t,3> counts{};
    // One visible real native triangle; there is no stubbed renderer.
    std::array<double,23> triangle{};
    triangle[0]=0; triangle[1]=0; triangle[2]=.5;
    triangle[3]=0; triangle[4]=9; triangle[5]=.5;
    triangle[6]=7; triangle[7]=0; triangle[8]=.5;
    triangle[9]=triangle[10]=triangle[11]=1.;
    triangle[12]=1./63.;
    for(int i=13;i<22;++i) triangle[i]=.5;
    const auto before=depth;
    assert(are::raster::draw(triangle.data(),triangle.size(),1,width,height,
                            rgba.data(),rgba.size(),depth.data(),depth.size(),
                            counts.data(),counts.size())==are::raster::ok);
    assert(counts[2]>0);
    const auto visible=label_depth_winners(before.data(),depth.data(),depth.size(),7,owner.data(),owner.size());
    assert(visible>0);
    const auto input=rgba;
    const auto input_depth=depth;
    // CAG supplies (3,4) and every area emits 8-neighbour equal-speed radial waves.
    const auto wave=render_radial_cag_spherepop(rgba.data(),rgba.size(),
        depth.data(),depth.size(),owner.data(),owner.size(),width,height,
        3,4,{30.,0.,0.},120.,1.);
    assert(wave.finalized.size()==width*height);
    assert(wave.refusals>0);
    std::array<unsigned,width*height> seen{};
    double east=-1.,west=-1.,north=-1.,diag=-1.;
    for(const auto& a:wave.finalized) {
        assert(a.area<seen.size());
        assert(++seen[a.area]==1);
        assert(a.owner==owner[a.area]);
        if(a.area==31) { assert(a.arrival_seconds==0 && a.doppler==1 && a.tinted==0); }
        if(a.area==32) {east=a.doppler;assert(std::abs(a.arrival_seconds-1./120.)<1e-14);}
        if(a.area==30) west=a.doppler;
        if(a.area==24) north=a.doppler;
        if(a.area==25) {diag=a.arrival_seconds;assert(a.emitter==31);}
        if(owner[a.area]==0) assert(a.tinted==0);
    }
    for(unsigned n:seen) assert(n==1);
    assert(std::abs(east-4./3.)<1e-14);
    assert(std::abs(west-4./5.)<1e-14);
    assert(std::abs(north-1.)<1e-14);
    assert(std::abs(diag-std::sqrt(2.)/120.)<1e-14);
    assert(depth==input_depth);
    for(std::size_t k=0;k<owner.size();++k) {
        assert(rgba[4*k+3]==input[4*k+3]);
        if(owner[k]==0 || k==31)for(int c=0;c<4;++c)assert(rgba[4*k+c]==input[4*k+c]);
    }
    const auto result=rgba;
    auto replay=input;
    const auto wave2=render_radial_cag_spherepop(replay.data(),replay.size(),
        depth.data(),depth.size(),owner.data(),owner.size(),width,height,
        3,4,{30.,0.,0.},120.,1.);
    assert(replay==result && wave.event_fingerprint==wave2.event_fingerprint);
    assert(wave.refusals==wave2.refusals && wave.tinted_pixels==wave2.tinted_pixels);
    // Reject before buffer mutation.
    auto invalid=depth;invalid[62]=std::numeric_limits<float>::quiet_NaN();
    reject([&]{render_radial_cag_spherepop(rgba.data(),rgba.size(),invalid.data(),invalid.size(),
        owner.data(),owner.size(),width,height,3,4,{30,0,0},120,1);},"SPHEREPOP_WAVE_SCENE_INVALID");
    reject([&]{render_radial_cag_spherepop(rgba.data(),rgba.size(),depth.data(),depth.size(),
        owner.data(),owner.size(),width,height,7,4,{30,0,0},120,1);},"SPHEREPOP_WAVE_INPUT_INVALID");
    reject([&]{render_radial_cag_spherepop(rgba.data(),rgba.size(),depth.data(),depth.size(),
        owner.data(),owner.size(),width,height,3,4,{120,0,0},120,1);},"DOPPLER_VELOCITY_BUDGET");
    assert(rgba==result);
    std::cout<<"PASS real native CAG->SpherePop radial Doppler wavefront: complete="
             <<wave.finalized.size()<<" refusals="<<wave.refusals
             <<" tinted="<<wave.tinted_pixels<<"\n";
}
