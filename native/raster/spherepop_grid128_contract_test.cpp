// Research-only regression for an explicitly bounded 128x128 native CAG wave.
// No mocks, no GPU; this is the real C++17 wave implementation.
#include "spherepop_cag_radial_wave.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <exception>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

using are::raster::experimental::render_radial_cag_spherepop;
using are::raster::experimental::WaveReceipt;

static void demand(bool ok, const char* what) {
    if(!ok) throw std::runtime_error(what);
}

template <typename Fn>
static void rejects(Fn&& f, const char* message) {
    bool caught=false;
    try {f();} catch(const std::invalid_argument& e) {
        caught=true; demand(std::string(e.what())==message,"WRONG_REJECTION");
    }
    demand(caught,"MISSING_REJECTION");
}

static WaveReceipt run(std::vector<std::uint8_t>& rgba,
                       const std::vector<float>& depth,
                       const std::vector<std::uint32_t>& owners,
                       int width,int height,bool reuse=false) {
    return render_radial_cag_spherepop(
        rgba.data(),rgba.size(),depth.data(),depth.size(),
        owners.data(),owners.size(),width,height,width/2,height/2,
        {30.,0.,0.},120.,1.,true,reuse);
}

static void test_grid(int width,int height) {
    const std::size_t cells=std::size_t(width)*std::size_t(height);
    std::vector<std::uint8_t> original(cells*4);
    std::vector<float> depth(cells,.5f);
    std::vector<std::uint32_t> owners(cells,7);
    for(std::size_t i=0;i<cells;++i) {
        original[4*i]=96; original[4*i+1]=40;
        original[4*i+2]=128; original[4*i+3]=255;
    }
    for(std::size_t i: {std::size_t(0),cells-1}) {
        owners[i]=0; depth[i]=1.f;
    }
    auto frame=original;
    const auto reference=run(frame,depth,owners,width,height);
    demand(reference.finalized.size()==cells,"GRID_AREA_INCOMPLETE");
    demand(reference.refusals>0,"GRID_DUPLICATES_NOT_REFUSED");
    demand(reference.tinted_pixels>0,"GRID_DOPPLER_NOT_TINTED");
    std::vector<std::uint8_t> visited(cells,0);
    for(const auto& event:reference.finalized) {
        demand(event.area<cells && visited[event.area]++==0,"GRID_DOUBLE_FINALIZATION");
        demand(event.owner==owners[event.area],"GRID_OWNER_MISMATCH");
        if(event.owner==0) demand(event.tinted==0,"GRID_BACKGROUND_TINTED");
        demand(std::isfinite(event.arrival_seconds) && event.arrival_seconds>=0,
               "GRID_ARRIVAL_INVALID");
        demand(std::isfinite(event.doppler) && event.doppler>0,"GRID_DOPPLER_INVALID");
    }
    demand(std::all_of(visited.begin(),visited.end(),[](auto x){return x==1;}),
           "GRID_NOT_ALL_FINALIZED");
    for(std::size_t i=0;i<cells;++i) {
        demand(frame[4*i+3]==original[4*i+3],"GRID_ALPHA_CHANGED");
        if(owners[i]==0)
            for(std::size_t c=0;c<4;++c)
                demand(frame[4*i+c]==original[4*i+c],"GRID_BACKGROUND_CHANGED");
    }
    auto replay=original;
    const auto repeat=run(replay,depth,owners,width,height);
    demand(replay==frame &&
           repeat.event_fingerprint==reference.event_fingerprint &&
           repeat.refusals==reference.refusals &&
           repeat.tinted_pixels==reference.tinted_pixels,
           "GRID_REPLAY_DRIFT");
    auto reuse=original;
    const auto reused=run(reuse,depth,owners,width,height,true);
    demand(reuse==frame && reused.event_fingerprint==reference.event_fingerprint &&
           reused.refusals==reference.refusals &&
           reused.tinted_pixels==reference.tinted_pixels &&
           reused.doppler_factor_evaluations<=reference.doppler_factor_evaluations,
           "GRID_FACTOR_REUSE_DRIFT");

    auto invalid=depth;
    invalid[cells/2]=std::numeric_limits<float>::quiet_NaN();
    auto untouched=original;
    rejects([&]{render_radial_cag_spherepop(untouched.data(),untouched.size(),
        invalid.data(),invalid.size(),owners.data(),owners.size(),
        width,height,width/2,height/2,{30,0,0},120,1);},
        "SPHEREPOP_WAVE_SCENE_INVALID");
    demand(untouched==original,"GRID_BAD_DEPTH_MUTATED_FRAME");
    std::cout<<"GRID_CONTRACT_PASS width="<<width<<" height="<<height
             <<" finalized="<<reference.finalized.size()
             <<" fingerprint="<<reference.event_fingerprint
             <<" refusals="<<reference.refusals
             <<" tinted="<<reference.tinted_pixels<<"\n";
}
int main() {
    try {
        // An existing 64-grid remains deterministic; new 128-grid is opt-in.
        test_grid(64,64);
        test_grid(128,128);
        // Anything outside the new finite resource budget must reject
        // transactionally, including empty or overflow-sized dimensions.
        constexpr int width=129,height=128;
        const auto cells=std::size_t(width)*height;
        std::vector<std::uint8_t> rgba(cells*4,7);
        std::vector<float> depth(cells,.5f);
        std::vector<std::uint32_t> owner(cells,7);
        const auto original=rgba;
        rejects([&]{run(rgba,depth,owner,width,height);},
                "SPHEREPOP_WAVE_INPUT_INVALID");
        demand(rgba==original,"GRID_OVERSIZE_MUTATED_FRAME");
        std::cout<<"GRID_129_REJECTION_PASS\n";
        return 0;
    } catch(const std::exception& e) {
        std::cerr<<"GRID_CONTRACT_FAIL:"<<e.what()<<"\n";
        return 1;
    }
}
