// OuroborosCollective. Repository license applies.
// Experimental CPU-only CAG-seeded SpherePop-inspired radial effect propagation.
// Does not implement or claim the upstream SpherePop formal semantics.
#pragma once
#include "spherepop_object_mask.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <queue>
#include <stdexcept>
#include <vector>

namespace are::raster::experimental {

struct WaveArea {
    std::uint32_t area;         // Row-major integer render area.
    std::uint32_t emitter;      // Previous finalized area or same area at seed.
    double arrival_seconds;     // Euclidean edge distance / constant wave speed.
    double doppler;             // Signed radial source/observer Doppler multiplier.
    std::uint32_t owner;        // Original depth-winning object's owner.
    std::uint32_t tinted;       // Exactly 0 or 1 final pixel; not a shader-call count.
};

struct WaveReceipt {
    std::vector<WaveArea> finalized;   // Immutable-on-completion render areas.
    std::uint64_t refusals=0;          // Discarded attempts to repeat finalized areas.
    std::uint64_t event_fingerprint=0; // Non-cryptographic deterministic debug digest.
    std::size_t tinted_pixels=0;
};

inline WaveReceipt render_radial_cag_spherepop(
    std::uint8_t* rgba,std::size_t rgba_bytes,
    const float* depth,std::size_t depth_cells,
    const std::uint32_t* owners,std::size_t owner_cells,
    int width,int height, int cag_x,int cag_y,
    Vec3 velocity, double wave_speed,double artistic_gain) {

    // A bounded finite grid: single-threaded priority queue, no shader-side
    // recursion, state persisted only in this invocation's local receipt.
    if (width<=0 || height<=0 || width>64 || height>64 ||
        cag_x<0 || cag_y<0 || cag_x>=width || cag_y>=height ||
        !rgba || !depth || !owners ||
        depth_cells!=static_cast<std::size_t>(width)*height ||
        owner_cells!=depth_cells || rgba_bytes!=depth_cells*4 ||
        !finite(velocity) || !std::isfinite(wave_speed) || wave_speed<=0 ||
        !std::isfinite(artistic_gain) || artistic_gain<0 || artistic_gain>16 ||
        std::fegetround()!=FE_TONEAREST)
        throw std::invalid_argument("SPHEREPOP_WAVE_INPUT_INVALID");
#if defined(__SSE__)
    if ((_mm_getcsr() & ((1u<<15)|(1u<<6)))!=0)
        throw std::invalid_argument("SPHEREPOP_WAVE_INPUT_INVALID");
#endif
    for(std::size_t i=0;i<depth_cells;++i)
        if (!std::isfinite(depth[i]) || depth[i]<0 || depth[i]>1 ||
            (owners[i]!=0 && !(depth[i]<1.0f)))
            throw std::invalid_argument("SPHEREPOP_WAVE_SCENE_INVALID");

    struct Candidate { double time; std::uint32_t cell,emitter; };
    struct Later {
        bool operator()(const Candidate& a,const Candidate& b) const {
            if(a.time!=b.time) return a.time>b.time;
            if(a.cell!=b.cell) return a.cell>b.cell;
            return a.emitter>b.emitter;
        }
    };
    std::priority_queue<Candidate,std::vector<Candidate>,Later> pending;
    const auto seed=static_cast<std::uint32_t>(cag_y*width+cag_x);
    pending.push({0.,seed,seed});
    std::vector<std::uint8_t> completed(depth_cells,0);
    // Transactional: a bad propagation never leaves half a rendered frame.
    std::vector<std::uint8_t> staged(rgba,rgba+rgba_bytes);
    WaveReceipt receipt;
    receipt.finalized.reserve(depth_cells);
    std::uint64_t fnv=14695981039346656037ull;
    const auto feed=[&](std::uint32_t v){
        for(unsigned k=0;k<4;++k) {fnv^=std::uint8_t(v>>(k*8));fnv*=1099511628211ull;}
    };
    while(!pending.empty()) {
        const auto step=pending.top();
        pending.pop();
        if(completed[step.cell]) { ++receipt.refusals; continue; } // Refuse, never Pop twice.
        const int x=int(step.cell%std::uint32_t(width));
        const int y=int(step.cell/std::uint32_t(width));
        const int px=int(step.emitter%std::uint32_t(width));
        const int py=int(step.emitter/std::uint32_t(width));
        double factor=1.;
        if(step.cell!=step.emitter) {
            // Doppler controls spectral post tint, not isotropic wave velocity.
            factor=doppler_factor({double(px),double(py),0.},
                                  {double(x),double(y),0.},velocity,wave_speed);
        }
        // Reuse native single-object effect including alpha/depth semantics.
        std::uint32_t tinted=0;
        if(owners[step.cell]!=0 && step.cell!=step.emitter) {
            const auto offset=std::size_t(step.cell)*4;
            const auto result=apply_single_object(staged.data()+offset,4,
                depth+step.cell,1,1,1,{double(px),double(py),0.},
                {double(x),double(y),0.},velocity,
                wave_speed,artistic_gain,owners[step.cell]);
            tinted=static_cast<std::uint32_t>(result.tinted_pixels);
        }
        // CAG seed has no radial direction: neutral, finalized exactly once.
        completed[step.cell]=1;     // Bind -> Pop -> Collapse, at most once.
        receipt.finalized.push_back({step.cell,step.emitter,step.time,factor,
                                     owners[step.cell],tinted});
        receipt.tinted_pixels+=tinted;
        feed(step.cell); feed(step.emitter); feed(owners[step.cell]);feed(tinted);
        // A newly completed area emits a new isotropic wave in all 8 directions
        // (four axes at d=1 and four diagonals at d=sqrt(2)).
        for(int dy=-1;dy<=1;++dy) for(int dx=-1;dx<=1;++dx) {
            if(dx==0 && dy==0)continue;
            const int xx=x+dx, yy=y+dy;
            if(xx<0||xx>=width||yy<0||yy>=height)continue;
            const auto next=static_cast<std::uint32_t>(yy*width+xx);
            if(!completed[next]) {
                const double d=(dx && dy) ? 1.4142135623730950488 : 1.;
                pending.push({step.time+d/wave_speed,next,step.cell});
            } else ++receipt.refusals;
        }
    }
    if(receipt.finalized.size()!=depth_cells)
        throw std::runtime_error("SPHEREPOP_WAVE_INCOMPLETE");
    receipt.event_fingerprint=fnv;
    std::memcpy(rgba,staged.data(),rgba_bytes);
    return receipt;
}

} // namespace are::raster::experimental
