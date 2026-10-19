// Isolated projection contract, deterministic history and negative admission.
#include "spherepop_object_mask.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
using namespace are::raster::experimental;

template<typename F> static void expect_reject(F fn, const char* message) {
    bool rejected=false;
    try { fn(); }
    catch(const std::invalid_argument& e) { rejected=true; assert(std::string(e.what())==message); }
    assert(rejected);
}
int main() {
    const std::array<float,4> before{1,1,1,1}, first{0.5f,0.5f,1,1};
    std::array<std::uint32_t,4> owners{};
    assert(label_depth_winners(before.data(), first.data(),4,17,owners.data(),owners.size())==2);
    assert((owners == std::array<std::uint32_t,4>{17,17,0,0}));
    const std::array<float,4> second{0.5f,0.25f,0.7f,1};
    assert(label_depth_winners(first.data(),second.data(),4,23,owners.data(),owners.size())==2);
    assert((owners == std::array<std::uint32_t,4>{17,23,23,0}));
    const auto stable_owners=owners;
    auto increased=second; increased[0]=0.75f;
    expect_reject([&]{label_depth_winners(second.data(),increased.data(),4,19,owners.data(),owners.size());},"SPHEREPOP_OBJECT_MASK_DEPTH_NONMONOTONE");
    expect_reject([&]{label_depth_winners(first.data(),second.data(),4,0,owners.data(),owners.size());},"SPHEREPOP_OBJECT_MASK_BUFFER_INVALID");
    expect_reject([&]{label_depth_winners(first.data(),second.data(),4,19,owners.data(),3);},"SPHEREPOP_OBJECT_MASK_BUFFER_INVALID");
    auto nan=second;nan[3]=std::numeric_limits<float>::quiet_NaN();
    expect_reject([&]{label_depth_winners(first.data(),nan.data(),4,19,owners.data(),4);},"SPHEREPOP_OBJECT_MASK_DEPTH_INVALID");
    assert(owners==stable_owners);
    std::array<std::uint8_t,16> rgba{};
    for(std::size_t i=0;i<4;++i) {rgba[4*i]=100;rgba[4*i+1]=110;rgba[4*i+2]=120;rgba[4*i+3]=255;}
    const auto original=rgba;
    const Vec3 src{0,0,0},view{10,0,0};
    History hist;
    auto to=apply_object_masked(rgba.data(),rgba.size(),second.data(),second.size(),owners.data(),owners.size(),2,2,src,view,{30,0,0},120,1,23,&hist);
    assert(std::abs(to.factor-4.0/3.0)<1e-14 && to.tinted_pixels==2 && hist.used==3);
    assert(rgba[0]==original[0] && rgba[2]==original[2]);
    for(std::size_t i=1;i<3;++i){assert(rgba[4*i]<original[4*i]);assert(rgba[4*i+2]>original[4*i+2]);assert(rgba[4*i+1]==original[4*i+1]);assert(rgba[4*i+3]==255);}
    for(int k=0;k<4;++k)assert(rgba[12+k]==original[12+k]);
    assert(owners==stable_owners && second[0]==0.5f && second[1]==0.25f);
    const auto done=rgba; const auto signature=hist.fingerprint();
    auto replay=original;History hist2;
    auto again=apply_object_masked(replay.data(),replay.size(),second.data(),second.size(),owners.data(),owners.size(),2,2,src,view,{30,0,0},120,1,23,&hist2);
    assert(replay==done && again.history_fingerprint==signature);
    expect_reject([&]{apply_object_masked(rgba.data(),rgba.size(),second.data(),second.size(),owners.data(),3,2,2,src,view,{30,0,0},120,1,23,&hist);},"SPHEREPOP_OBJECT_MASK_BUFFER_INVALID");
    expect_reject([&]{apply_object_masked(rgba.data(),rgba.size(),nan.data(),nan.size(),owners.data(),owners.size(),2,2,src,view,{30,0,0},120,1,23,&hist);},"DOPPLER_DEPTH_INVALID");
    expect_reject([&]{apply_object_masked(rgba.data(),rgba.size(),second.data(),second.size(),owners.data(),owners.size(),2,2,src,view,{120,0,0},120,1,23,&hist);},"DOPPLER_VELOCITY_BUDGET");
    History full;for(unsigned i=0;i<63;++i)full.append(EventKind::Refuse,0,100+i);
    expect_reject([&]{apply_object_masked(rgba.data(),rgba.size(),second.data(),second.size(),owners.data(),owners.size(),2,2,src,view,{30,0,0},120,1,23,&full);},"SPHEREPOP_HISTORY_INVALID");
    assert(rgba==done && hist.fingerprint()==signature && full.used==63);
    std::cout << "PASS SpherePop CAG Doppler object mask ownership/replay/atomicity\n";
}
