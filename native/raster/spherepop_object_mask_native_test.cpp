// Real native raster with independent per-object depth ownership and effect.
#include "core.hpp"
#include "spherepop_object_mask.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
using namespace are::raster::experimental;

static std::array<double,23> triangle(double ax,double ay,double bx,double by,
                                       double cx,double cy,double z,double color) {
    std::array<double,23> p{};
    p[0]=ax;p[1]=ay;p[2]=z;
    p[3]=bx;p[4]=by;p[5]=z;
    p[6]=cx;p[7]=cy;p[8]=z;
    p[9]=p[10]=p[11]=1;
    const auto area=static_cast<float>((cx-ax)*(by-ay)-(cy-ay)*(bx-ax));
    assert(area>0.0f);
    p[12]=static_cast<float>(1.0/static_cast<double>(area));
    for (int v=0;v<3;++v) for (int k=0;k<3;++k) p[13+v*3+k]=color;
    return p;
}
template<typename F> static void reject(F fn,const char* text) {
    bool seen=false;
    try{fn();}catch(const std::invalid_argument& e){seen=true;assert(std::string(e.what())==text);}
    assert(seen);
}
int main() {
    constexpr int width=8,height=8;
    std::array<std::uint8_t,width*height*4> rgba{};
    std::array<float,width*height> depth;depth.fill(1);
    std::array<std::uint32_t,width*height> owners{};
    std::array<std::uint64_t,3> counts{};
    const auto draw=[&](const std::array<double,23>& p) {
        return are::raster::draw(p.data(),p.size(),1,width,height,
                                 rgba.data(),rgba.size(),depth.data(),depth.size(),
                                 counts.data(),counts.size());
    };
    const auto first=triangle(0,0,0,8,8,0,.5,.4);
    const auto second=triangle(2,2,2,7,7,2,.25,.7);
    const auto initial_depth=depth;
    assert(draw(first)==are::raster::ok && counts[2]>0);
    const auto first_depth=depth;
    const auto n1=label_depth_winners(initial_depth.data(),depth.data(),depth.size(),17,owners.data(),owners.size());
    assert(n1>0);
    assert(draw(second)==are::raster::ok && counts[2]>0);
    const auto n2=label_depth_winners(first_depth.data(),depth.data(),depth.size(),23,owners.data(),owners.size());
    assert(n2>0);
    const auto winners=owners;
    const auto original=rgba;
    const auto frozen_depth=depth;
    // Strict depth ties may draw again, but cannot rewrite owner identity.
    assert(draw(second)==are::raster::ok && counts[2]==0);
    assert(label_depth_winners(frozen_depth.data(),depth.data(),depth.size(),31,owners.data(),owners.size())==0);
    assert(winners==owners && original==rgba && frozen_depth==depth);
    std::size_t ids17=0,ids23=0,background=0;
    for (auto id:owners) {ids17+=(id==17);ids23+=(id==23);background+=(id==0);}
    assert(ids17>0 && ids23>0 && background>0);
    const Vec3 src{0,0,0}, eye{10,0,0};
    History history;
    const auto effect=apply_object_masked(rgba.data(),rgba.size(),depth.data(),depth.size(),
                                           owners.data(),owners.size(),width,height,src,eye,
                                           {30,0,0},120,1,23,&history);
    assert(std::abs(effect.factor-4.0/3.0)<1e-14 && effect.tinted_pixels==ids23);
    assert(history.used==3 && frozen_depth==depth && winners==owners);
    for (std::size_t i=0;i<owners.size();++i) {
        assert(rgba[4*i+3]==original[4*i+3]);
        if (owners[i]==23) {
            assert(rgba[4*i]<original[4*i] && rgba[4*i+2]>original[4*i+2]);
            assert(rgba[4*i+1]==original[4*i+1]);
        } else for(int k=0;k<4;++k) assert(rgba[4*i+k]==original[4*i+k]);
    }
    const auto colored=rgba;
    const auto stamp=history.fingerprint();
    auto repeat=original;History replay;
    const auto again=apply_object_masked(repeat.data(),repeat.size(),depth.data(),depth.size(),
                                          owners.data(),owners.size(),width,height,src,eye,
                                          {30,0,0},120,1,23,&replay);
    assert(repeat==colored && again.history_fingerprint==stamp);
    auto invalid_depth=depth;invalid_depth[0]=std::numeric_limits<float>::quiet_NaN();
    reject([&]{apply_object_masked(rgba.data(),rgba.size(),invalid_depth.data(),invalid_depth.size(),
                                    owners.data(),owners.size(),width,height,src,eye,
                                    {30,0,0},120,1,23,&history);},"DOPPLER_DEPTH_INVALID");
    reject([&]{apply_object_masked(rgba.data(),rgba.size(),depth.data(),depth.size(),
                                    owners.data(),owners.size()-1,width,height,src,eye,
                                    {30,0,0},120,1,23,&history);},"SPHEREPOP_OBJECT_MASK_BUFFER_INVALID");
    assert(rgba==colored && history.fingerprint()==stamp);
    std::cout<<"PASS native raster SpherePop object mask/Doppler: ownership, depth tie, replay, negatives; first="
             <<ids17<<" second="<<ids23<<" background="<<background<<"\n";
}
