// Exact source C++17 wave, streamed for independent full-grid Julia validation.
// All user-visible timing evidence remains in the separate real CPU benchmark.
#include "spherepop_cag_radial_wave.hpp"
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

using are::raster::experimental::render_radial_cag_spherepop;

static void verify(int width) {
    const int height=width;
    const std::size_t cells=std::size_t(width)*height;
    std::vector<std::uint8_t> rgba(cells*4);
    std::vector<float> depth(cells,0.5f);
    std::vector<std::uint32_t> owners(cells,7);
    for(std::size_t i=0;i<cells;++i) {
        rgba[4*i]=96; rgba[4*i+1]=40;
        rgba[4*i+2]=128; rgba[4*i+3]=255;
    }
    owners[0]=owners[cells-1]=0;
    depth[0]=depth[cells-1]=1.f;
    const auto original=rgba;
    const auto first=render_radial_cag_spherepop(
        rgba.data(),rgba.size(),depth.data(),depth.size(),
        owners.data(),owners.size(),width,height,width/2,height/2,
        {30.,0.,0.},120.,1.,true,false,true);
    if(first.finalized.size()!=cells || first.refusals==0 ||
       first.tinted_pixels==0)
        throw std::runtime_error("GRID_ORACLE_INCOMPLETE");
    auto repeat=original;
    const auto replay=render_radial_cag_spherepop(
        repeat.data(),repeat.size(),depth.data(),depth.size(),
        owners.data(),owners.size(),width,height,width/2,height/2,
        {30.,0.,0.},120.,1.,true,true,true);
    if(repeat!=rgba || replay.event_fingerprint!=first.event_fingerprint ||
       replay.refusals!=first.refusals ||
       replay.tinted_pixels!=first.tinted_pixels ||
       replay.finalized.size()!=first.finalized.size() ||
       replay.doppler_factor_evaluations>first.doppler_factor_evaluations)
        throw std::runtime_error("GRID_ORACLE_REUSE_DRIFT");
    for(std::size_t i=0;i<cells;++i) {
        const auto& event=first.finalized[i];
        if(event.area>=cells) throw std::runtime_error("GRID_BAD_AREA");
        const auto pixel=std::size_t(event.area)*4;
        std::cout<<"W\t"<<width<<"\t"<<event.area<<"\t"
                 <<event.emitter<<"\t"<<event.arrival_seconds<<"\t"
                 <<event.doppler<<"\t"<<event.owner<<"\t"<<event.tinted;
        for(unsigned c=0;c<4;++c)
            std::cout<<"\t"<<unsigned(rgba[pixel+c]);
        std::cout<<"\n";
    }
    std::cout<<"M\t"<<width<<"\t"<<first.refusals<<"\t"
             <<first.event_fingerprint<<"\t"<<first.tinted_pixels<<"\t"
             <<first.doppler_factor_evaluations<<"\t"
             <<replay.doppler_factor_evaluations<<"\n";
}

int main() {
    try {
        std::cout<<std::setprecision(17);
        verify(64);
        verify(128);
        return 0;
    } catch(const std::exception& e) {
        std::cerr<<"CPP_GRID_ORACLE_FAIL:"<<e.what()<<"\n";
        return 1;
    }
}
