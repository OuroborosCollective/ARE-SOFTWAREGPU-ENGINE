// Real native raster to optional single-object Doppler post-pass.
#include "core.hpp"
#include "spherepop_doppler_profile.hpp"
#include <array>
#include <cassert>
#include <cfenv>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#if defined(__SSE__)
#include <xmmintrin.h>
#endif
using namespace are::raster::experimental;
template <typename F> static void reject(F fn,const char* expected) {
    try { fn(); } catch (const std::invalid_argument& e) {
        assert(std::string(e.what()) == expected); return;
    }
    throw std::runtime_error("EXPECTED_REJECTION");
}
int main() {
    const Vec3 source{0,0,0}, observer{10,0,0};
    assert(std::abs(doppler_factor(source,observer,{30,0,0},120)-4.0/3.0)<1e-14);
    assert(std::abs(doppler_factor(source,observer,{-30,0,0},120)-4.0/5.0)<1e-14);
    assert(doppler_factor(source,observer,{0,0,0},120)==1.0);
    reject([&]{doppler_factor(source,source,{30,0,0},120);},"DOPPLER_LINE_OF_SIGHT_INVALID");
    reject([&]{doppler_factor(source,observer,{114,0,0},120);},"DOPPLER_VELOCITY_BUDGET");
    reject([&]{doppler_factor(source,observer,{30,0,0},0);},"DOPPLER_INPUT_INVALID");
    reject([&]{doppler_factor(source,observer,{std::numeric_limits<double>::quiet_NaN(),0,0},120);},"DOPPLER_INPUT_INVALID");
    std::fesetround(FE_DOWNWARD);
    reject([&]{doppler_factor(source,observer,{30,0,0},120);},"DOPPLER_INPUT_INVALID");
    std::fesetround(FE_TONEAREST);
#if defined(__SSE__)
    const auto csr=_mm_getcsr();
    _mm_setcsr(csr|(1u<<15));
    reject([&]{doppler_factor(source,observer,{30,0,0},120);},"DOPPLER_INPUT_INVALID");
    _mm_setcsr(csr|(1u<<6));
    reject([&]{doppler_factor(source,observer,{30,0,0},120);},"DOPPLER_INPUT_INVALID");
    _mm_setcsr(csr);
#endif
    std::array<double,23> packed{};
    const double verts[]={0,0,0, 0,4,0, 4,0,0};
    std::copy(std::begin(verts),std::end(verts),packed.begin());
    packed[9]=packed[10]=packed[11]=1.0;
    packed[12]=1.0/16.0;
    for(int v=0;v<3;++v) for(int c=0;c<3;++c) packed[13+3*v+c]=.4;
    std::array<std::uint8_t,64> rgba{};
    std::array<float,16> depth; depth.fill(1.0f);
    std::array<std::uint64_t,3> counts{};
    const auto code=are::raster::draw(packed.data(),packed.size(),1,4,4,
                   rgba.data(),rgba.size(),depth.data(),depth.size(),counts.data(),counts.size());
    assert(code==are::raster::ok && counts[2]>0);
    const auto initial=rgba, initial_depth=depth;
    const auto no_effect=apply_single_object(rgba.data(),rgba.size(),depth.data(),depth.size(),4,4,source,observer,{0,0,0},120,1.0,17);
    assert(no_effect.factor==1 && no_effect.tinted_pixels==0 && rgba==initial);
    History history;
    const auto toward=apply_single_object(rgba.data(),rgba.size(),depth.data(),depth.size(),4,4,source,observer,{30,0,0},120,1.0,17,&history);
    assert(toward.tinted_pixels>0 && history.used==3 && depth==initial_depth);
    assert(history.events[1].parent==1 && history.events[2].parent==2);
    for(std::size_t i=0;i<16;++i) {
        assert(rgba[4*i+3]==initial[4*i+3]);
        if(depth[i]==1)for(int c=0;c<4;++c)assert(rgba[4*i+c]==initial[4*i+c]);
        if(depth[i]<1){assert(rgba[4*i]<=initial[4*i]); assert(rgba[4*i+2]>=initial[4*i+2]);}
    }
    const auto modified=rgba, prior=history.fingerprint();
    reject([&]{apply_single_object(rgba.data(),rgba.size(),depth.data(),depth.size(),4,4,source,observer,{120,0,0},120,1,17,&history);},"DOPPLER_VELOCITY_BUDGET");
    assert(rgba==modified && history.fingerprint()==prior);
    auto invalid_depth=depth; invalid_depth[15]=std::numeric_limits<float>::quiet_NaN();
    reject([&]{apply_single_object(rgba.data(),rgba.size(),invalid_depth.data(),invalid_depth.size(),4,4,source,observer,{30,0,0},120,1,17,&history);},"DOPPLER_DEPTH_INVALID");
    assert(rgba==modified && history.fingerprint()==prior);
    History nearly_full;
    for(unsigned i=0;i<63;++i)nearly_full.append(EventKind::Refuse,0,100+i);
    reject([&]{apply_single_object(rgba.data(),rgba.size(),depth.data(),depth.size(),4,4,source,observer,{30,0,0},120,1,17,&nearly_full);},"SPHEREPOP_HISTORY_INVALID");
    assert(nearly_full.used==63 && rgba==modified);
    auto away=initial;History away_history;
    const auto recede=apply_single_object(away.data(),away.size(),depth.data(),depth.size(),4,4,source,observer,{-30,0,0},120,1,17,&away_history);
    assert(recede.tinted_pixels>0 && std::abs(recede.factor-.8)<1e-14);
    for(std::size_t i=0;i<16;++i) if(depth[i]<1){assert(away[4*i]>=initial[4*i]);assert(away[4*i+2]<=initial[4*i+2]);}
    auto replay=initial;History replay_history;
    const auto again=apply_single_object(replay.data(),replay.size(),depth.data(),depth.size(),4,4,source,observer,{30,0,0},120,1,17,&replay_history);
    assert(replay==modified && again.history_fingerprint==toward.history_fingerprint);
    assert(away_history.fingerprint()!=history.fingerprint());
    std::cout<<"PASS native real raster + Doppler: image/depth, CAG ratios, replay, negatives; pixels="<<toward.tinted_pixels<<"\n";
}
