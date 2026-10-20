// OuroborosCollective. Repository license applies.
// Experimental time-windowed SINGLE-source impact projection; not production dispatched.
// One CAG impact -> one direct distance calculation per affected area.
// Deliberately no SpherePop queue, no recurrent re-emissions, no persistent history.
#pragma once
#include "single_origin_impact_wave.hpp"
#include <algorithm>
#include <cfenv>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <vector>

namespace are::raster::single_origin {
using experimental::Vec3;
struct PulseReceipt {
    std::size_t area_completions=0;   // exactly once per active window
    std::size_t spatial_candidates=0; // inside clipped impact bound
    std::size_t wave_arrivals=0; // inside radius and below current front
    std::size_t tinted_pixels=0;
    std::size_t doppler_evaluations=0;
    std::size_t spherepop_starts=1;
    std::size_t reemissions=0;
    std::size_t queue_pushes=0;
    std::size_t refusals=0;
    std::uint64_t event_fingerprint=0; // diagnostic FNV1a, not cryptographic
};
inline PulseReceipt apply_at_time(
    std::uint8_t* rgba,std::size_t rgba_bytes,
    const float* depth,std::size_t depth_cells,
    const std::uint32_t* owners,std::size_t owner_cells,
    int width,int height,int source_x,int source_y,
    Vec3 velocity,double wave_speed,double gain,double radius,
    double elapsed_seconds,double window_seconds,
    std::uint32_t target_owner,bool enable_doppler=true) {
    // One deterministic stateless snapshot per timestamp; no event persistence.
    // Bounding prevents overflow and pathological CPU/memory reservations.
    if(width<1||height<1||width>2048||height>2048||
       std::uint64_t(width)*height>4194304ull||
       source_x<0||source_y<0||source_x>=width||source_y>=height||
       !rgba||!depth||!owners||!target_owner||
       depth_cells!=std::size_t(width)*height||
       owner_cells!=depth_cells||rgba_bytes!=depth_cells*4||
       !experimental::finite(velocity)||
       !std::isfinite(wave_speed)||wave_speed<=0||
       !std::isfinite(gain)||gain<0||gain>16||
       !std::isfinite(radius)||radius<0||
       std::fegetround()!=FE_TONEAREST)
        throw std::invalid_argument("SINGLE_IMPACT_INPUT_INVALID");
#if defined(__SSE__)
    if((_mm_getcsr() & ((1u<<15)|(1u<<6)))!=0)
        throw std::invalid_argument("SINGLE_IMPACT_INPUT_INVALID");
#endif
    if(!std::isfinite(elapsed_seconds)||elapsed_seconds<0 ||
       !std::isfinite(window_seconds)||window_seconds<=0)
        throw std::invalid_argument("SINGLE_IMPACT_TIME_INVALID");
    const double speed=std::hypot(velocity.x,std::hypot(velocity.y,velocity.z));
    if(!std::isfinite(speed)||!(speed<0.95*wave_speed))
        throw std::invalid_argument("SINGLE_IMPACT_VELOCITY_BUDGET");
    // Complete input preflight before touching RGBA; scene retains native
    // owner/depth invariant, even for cells outside the proposed impact.
    for(std::size_t i=0;i<depth_cells;++i)
        if(!std::isfinite(depth[i])||depth[i]<0||depth[i]>1||
           (owners[i]!=0 && !(depth[i]<1.f)))
            throw std::invalid_argument("SINGLE_IMPACT_SCENE_INVALID");
    // Preflight travel distance to avoid non-finite arrival times. Never
    // impose unrelated frame-to-frame progress/authority semantics.
    const double maximum=std::hypot(double(width),double(height))/wave_speed;
    if(!std::isfinite(maximum))
        throw std::invalid_argument("SINGLE_IMPACT_INPUT_INVALID");

    // Work only within clipped impact AABB. A completed area is *not* enqueued
    // elsewhere; row-major linear execution inherently visits it exactly once.
    // Never scan pixels the traveling front cannot have reached yet.
    const double reached=std::min(radius,elapsed_seconds*wave_speed);
    const int reach=reached>=double(std::max(width,height))
       ? std::max(width,height)
       : int(std::ceil(reached));
    const int left=std::max(0,source_x-reach);
    const int top=std::max(0,source_y-reach);
    const int right=std::min(width-1,source_x+reach);
    const int bottom=std::min(height-1,source_y+reach);
    std::vector<std::uint8_t> staged(rgba,rgba+rgba_bytes);
    PulseReceipt receipt;
    std::uint64_t fingerprint=14695981039346656037ull;
    const auto feed=[&](std::uint32_t v) {
        for(unsigned k=0;k<4;++k) {
            fingerprint^=std::uint8_t(v>>(k*8));
            fingerprint*=1099511628211ull;
        }
    };
    for(int y=top;y<=bottom;++y)for(int x=left;x<=right;++x) {
        const double dx=double(x-source_x),dy=double(y-source_y);
        const double distance=std::hypot(dx,dy);
        if(distance>radius)continue;
        ++receipt.spatial_candidates;
        const double arrival=distance/wave_speed;
        if(arrival>elapsed_seconds)continue;
        ++receipt.wave_arrivals;
        // Half-open trailing edge avoids double-hit on consecutive time ticks.
        // At t=0 the source is the unique first arrival.
        if(elapsed_seconds>0 && arrival<=elapsed_seconds-window_seconds)continue;
        const auto index=std::size_t(y)*width+x;
        ++receipt.area_completions;
        std::uint32_t tinted=0;
        if(enable_doppler && distance>1.e-12 && owners[index]==target_owner) {
            // Exact single-source line-of-sight Doppler. One evaluation per
            // visible owned target; no new emitter at the destination.
            const double radial=(velocity.x*dx+velocity.y*dy)/distance;
            const double factor=wave_speed/(wave_speed-radial);
            if(!std::isfinite(factor))
                throw std::invalid_argument("SINGLE_IMPACT_INPUT_INVALID");
            ++receipt.doppler_evaluations;
            const double tint=std::clamp((factor-1.)*gain,-1.,1.);
            const auto amount=int(std::floor(std::abs(tint)*64.+.5));
            if(amount>0) {
                auto* color=staged.data()+4*index;
                const auto old_r=color[0],old_b=color[2];
                if(tint>0) {
                    color[0]=std::uint8_t(std::max(0,int(old_r)-amount));
                    color[2]=std::uint8_t(std::min(255,int(old_b)+amount));
                } else {
                    color[0]=std::uint8_t(std::min(255,int(old_r)+amount));
                    color[2]=std::uint8_t(std::max(0,int(old_b)-amount));
                }
                tinted=(color[0]!=old_r || color[2]!=old_b)?1u:0u;
            }
        }
        receipt.tinted_pixels+=tinted;
        feed(std::uint32_t(index));feed(owners[index]);feed(tinted);
    }
    receipt.event_fingerprint=fingerprint;
    std::memcpy(rgba,staged.data(),rgba_bytes);
    return receipt;
}
inline double arrival_seconds(int sx,int sy,int x,int y,double speed) {
    if(!std::isfinite(speed)||speed<=0)
        throw std::invalid_argument("SINGLE_IMPACT_INPUT_INVALID");
    return std::hypot(double(x-sx),double(y-sy))/speed;
}
} // namespace are::raster::single_origin
