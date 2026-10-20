// Real C++17 ablation: same scene/wave with and without Doppler.
#include "spherepop_cag_radial_wave.hpp"
#include <array>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <vector>
#include <algorithm>
using namespace are::raster::experimental;
int main() {
    constexpr int W=32,H=32,N=W*H;
    std::array<float,N> depth{};
    std::array<std::uint32_t,N> owners{};
    std::array<std::uint8_t,N*4> original{};
    depth.fill(0.5f); owners.fill(7);
    for(int i=0;i<N;++i) {
        original[4*i]=75; original[4*i+1]=105; original[4*i+2]=145; original[4*i+3]=255;
    }
    auto no_color=original,with_color=original;
    // This overload must be absent in baseline (RED) and supported after implementation (GREEN).
    auto no=render_radial_cag_spherepop(no_color.data(),no_color.size(),depth.data(),N,
        owners.data(),N,W,H,15,16,{30.,0.,0.},120.,1.,false);
    auto yes=render_radial_cag_spherepop(with_color.data(),with_color.size(),depth.data(),N,
        owners.data(),N,W,H,15,16,{30.,0.,0.},120.,1.,true);
    assert(no.finalized.size()==N && yes.finalized.size()==N);
    assert(no.refusals==yes.refusals && no.refusals>0);
    assert(no.tinted_pixels==0 && yes.tinted_pixels>0);
    assert(no_color==original && with_color!=original);
    assert(no.event_fingerprint==yes.event_fingerprint);
    for(size_t i=0;i<N;++i) {
        assert(no.finalized[i].area==yes.finalized[i].area);
        assert(no.finalized[i].emitter==yes.finalized[i].emitter);
        assert(no.finalized[i].arrival_seconds==yes.finalized[i].arrival_seconds);
        assert(no.finalized[i].doppler==1. && no.finalized[i].tinted==0);
        assert(yes.finalized[i].owner==no.finalized[i].owner);
    }
    // 15 alternating warm-CPU repeats, not replacement for whole-frame perf gates.
    using clock=std::chrono::steady_clock;
    std::vector<double> plain, tinted;
    for(int i=-2;i<15;++i) {
        for(int run=0;run<2;++run) {
            bool enable=((i&1)==run);
            auto rgba=original;
            auto start=clock::now();
            auto r=render_radial_cag_spherepop(rgba.data(),rgba.size(),depth.data(),N,
                owners.data(),N,W,H,15,16,{30.,0.,0.},120.,1.,enable);
            auto elapsed=std::chrono::duration<double,std::milli>(clock::now()-start).count();
            assert(r.finalized.size()==N && r.refusals==no.refusals);
            assert(r.event_fingerprint==(enable?yes:no).event_fingerprint);
            assert(rgba==(enable?with_color:no_color));
            if(i>=0) (enable?tinted:plain).push_back(elapsed);
        }
    }
    assert(plain.size()==15 && tinted.size()==15);
    const auto median=[](std::vector<double> values){
        std::sort(values.begin(),values.end());return values.at(values.size()/2);
    };
    std::vector<double> ratios;
    for(size_t i=0;i<15;++i) ratios.push_back(tinted[i]/plain[i]);
    std::cout<<"SPHEREPOP_NO_DOPPLER_RESULT median_plain_ms="<<median(plain)
             <<" median_doppler_ms="<<median(tinted)
             <<" median_doppler_over_plain="<<median(ratios)
             <<" finalized="<<N<<" refused="<<no.refusals<<" pairs=15\n";
}
