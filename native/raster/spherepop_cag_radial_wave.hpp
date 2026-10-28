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
    std::size_t doppler_factor_evaluations=0; // Instrumentation, not event digest.
};

inline WaveReceipt render_radial_cag_spherepop(
    std::uint8_t* rgba,std::size_t rgba_bytes,
    const float* depth,std::size_t depth_cells,
    const std::uint32_t* owners,std::size_t owner_cells,
    int width,int height, int cag_x,int cag_y,
    Vec3 velocity, double wave_speed,double artistic_gain, bool enable_doppler=true,
    bool reuse_factor=false, bool allow_research_128=false,
    bool cache_directions=false) {

    // A bounded finite grid: single-threaded priority queue, no shader-side
    // recursion, state persisted only in this invocation's local receipt.
    if (width<=0 || height<=0 || width>(allow_research_128 ? 128 : 64) ||
        height>(allow_research_128 ? 128 : 64) ||
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
    // Fail closed on arithmetic overflow in edge travel or path accumulation.
    const double diagonal_time=1.4142135623730950488/wave_speed;
    if(!std::isfinite(diagonal_time) ||
       !std::isfinite(diagonal_time*double(width+height)))
        throw std::invalid_argument("SPHEREPOP_WAVE_INPUT_INVALID");
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
    // A wave emitter is always one of the eight adjacent integer cells.
    // For a fixed velocity and wave speed, Doppler depends on that direction,
    // not the absolute pixel location. Cache lazily so an unused direction
    // cannot cause a new validation failure and the default stays identical.
    std::array<double,9> direction_factors{};
    std::array<std::uint8_t,9> direction_valid{};
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
        if(enable_doppler && step.cell!=step.emitter) {
            // Doppler controls spectral post tint, not isotropic wave velocity.
            if(cache_directions) {
                // Pending events are generated only by the eight-neighbor loop
                // below. The emitter is the previous completed neighbor.
                const auto direction=std::size_t((y-py+1)*3+(x-px+1));
                if(!direction_valid[direction]) {
                    direction_factors[direction]=doppler_factor(
                        {double(px),double(py),0.},
                        {double(x),double(y),0.},velocity,wave_speed);
                    direction_valid[direction]=1;
                    ++receipt.doppler_factor_evaluations;
                }
                factor=direction_factors[direction];
            } else {
                factor=doppler_factor({double(px),double(py),0.},
                                      {double(x),double(y),0.},velocity,wave_speed);
                ++receipt.doppler_factor_evaluations;
            }
        }
        // Reuse native single-object effect including alpha/depth semantics.
        std::uint32_t tinted=0;
        if(enable_doppler && owners[step.cell]!=0 && step.cell!=step.emitter) {
            const auto offset=std::size_t(step.cell)*4;
            if(reuse_factor) {
                // Same scalar tint math, but reuse the validated factor.
                // The original function still owns the unoptimized reference.
                const double tint=std::clamp((factor-1.0)*artistic_gain,-1.0,1.0);
                const auto amount=static_cast<int>(std::floor(std::abs(tint)*64.0+0.5));
                if(amount && depth[step.cell]<1.0f) {
                    auto* color=staged.data()+offset;
                    const auto old_r=color[0],old_b=color[2];
                    if(tint>0) {
                        color[0]=static_cast<std::uint8_t>(std::max(0,int(old_r)-amount));
                        color[2]=static_cast<std::uint8_t>(std::min(255,int(old_b)+amount));
                    } else {
                        color[0]=static_cast<std::uint8_t>(std::min(255,int(old_r)+amount));
                        color[2]=static_cast<std::uint8_t>(std::max(0,int(old_b)-amount));
                    }
                    tinted=(color[0]!=old_r || color[2]!=old_b) ? 1u : 0u;
                }
            } else {
                const auto result=apply_single_object(staged.data()+offset,4,
                    depth+step.cell,1,1,1,{double(px),double(py),0.},
                    {double(x),double(y),0.},velocity,
                    wave_speed,artistic_gain,owners[step.cell]);
                ++receipt.doppler_factor_evaluations;
                tinted=static_cast<std::uint32_t>(result.tinted_pixels);
            }
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
