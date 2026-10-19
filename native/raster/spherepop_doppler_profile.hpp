// OuroborosCollective. Repository license applies.
// Isolated native C++17 research profile; not imported by production raster paths.
// SpherePop-inspired event history is an original adaptation, not SpherePop's runtime.
#pragma once
#include <algorithm>
#include <array>
#include <cfenv>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <limits>
#include <stdexcept>
#if defined(__SSE__)
#include <xmmintrin.h>
#endif

#ifdef __FAST_MATH__
#error Fast math is prohibited in the deterministic Doppler profile
#endif

namespace are::raster::experimental {

enum class EventKind : std::uint8_t { Bind=1, Pop=2, Refuse=3, Collapse=4 };
struct Event { EventKind kind; std::uint32_t parent; std::uint32_t subject; };
struct History {
    std::array<Event,64> events{};
    std::size_t used=0;
    std::uint32_t append(EventKind kind,std::uint32_t parent,std::uint32_t subject) {
        if (used >= events.size() || parent > used || subject == 0)
            throw std::invalid_argument("SPHEREPOP_HISTORY_INVALID");
        events[used] = {kind,parent,subject};
        return static_cast<std::uint32_t>(++used);
    }
    // Portable FNV-1a identity of ordered metadata; NOT a cryptographic receipt.
    std::uint64_t fingerprint() const {
        std::uint64_t h=14695981039346656037ull;
        const auto feed=[&](std::uint8_t b){h^=b;h*=1099511628211ull;};
        for (std::size_t i=0;i<used;++i) {
            feed(static_cast<std::uint8_t>(events[i].kind));
            for (auto word:{events[i].parent,events[i].subject})
                for (unsigned k=0;k<4;++k) feed(static_cast<std::uint8_t>(word>>(8*k)));
        }
        return h;
    }
};
struct Vec3 { double x,y,z; };
inline bool finite(Vec3 a) {
    return std::isfinite(a.x) && std::isfinite(a.y) && std::isfinite(a.z);
}
inline double doppler_factor(Vec3 source,Vec3 observer,Vec3 velocity,double wave_speed) {
    // Classical moving source, stationary observer, radial line of sight.
    // Units: consistent scene distance per second. NOT relativistic optical Doppler.
    if (!finite(source) || !finite(observer) || !finite(velocity) ||
        !std::isfinite(wave_speed) || wave_speed<=0 || std::fegetround()!=FE_TONEAREST)
        throw std::invalid_argument("DOPPLER_INPUT_INVALID");
    // Match the native raster FP environment gate: FTZ/DAZ are not permitted.
#if defined(__SSE__)
    if ((_mm_getcsr() & ((1u << 15) | (1u << 6))) != 0)
        throw std::invalid_argument("DOPPLER_INPUT_INVALID");
#endif
    const auto dx=observer.x-source.x,dy=observer.y-source.y,dz=observer.z-source.z;
    const auto length=std::hypot(dx,std::hypot(dy,dz));
    if (!std::isfinite(length) || length<=1.e-12)
        throw std::invalid_argument("DOPPLER_LINE_OF_SIGHT_INVALID");
    const double radial=(velocity.x*dx + velocity.y*dy + velocity.z*dz)/length;
    // Conservative numerical gate, not a universal physical limit.
    if (!std::isfinite(radial) || !(std::abs(radial)<0.95*wave_speed))
        throw std::invalid_argument("DOPPLER_VELOCITY_BUDGET");
    const double factor=wave_speed/(wave_speed-radial);
    if (!std::isfinite(factor)) throw std::invalid_argument("DOPPLER_RESULT_INVALID");
    return factor;
}
struct Result { double factor; std::size_t tinted_pixels; std::uint64_t history_fingerprint; };
inline Result apply_single_object(std::uint8_t* rgba,std::size_t rgba_bytes,
                                  const float* depth,std::size_t depth_cells,int width,int height,
                                  Vec3 source,Vec3 observer,Vec3 source_velocity,
                                  double wave_speed,double artistic_gain,
                                  std::uint32_t object_id,History* history=nullptr) {
    // A separate object buffer is required: never tint unrelated meshes in a composite.
    // Alpha and every depth bit remain unchanged for disjoint caller-owned buffers.
    if (width<=0 || height<=0 || width>2048 || height>2048 ||
        static_cast<std::uint64_t>(width)*height>4194304 || !rgba || !depth ||
        depth_cells!=static_cast<std::size_t>(width)*height ||
        rgba_bytes!=depth_cells*4 || object_id==0 ||
        !std::isfinite(artistic_gain) || artistic_gain<0 || artistic_gain>16)
        throw std::invalid_argument("DOPPLER_BUFFER_INVALID");
    // Prevalidate entire input and event capacity before mutating.
    const double factor=doppler_factor(source,observer,source_velocity,wave_speed);
    for (std::size_t i=0;i<depth_cells;++i)
        if (!std::isfinite(depth[i])) throw std::invalid_argument("DOPPLER_DEPTH_INVALID");
    const double tint=std::clamp((factor-1.0)*artistic_gain,-1.0,1.0);
    const auto amount=static_cast<int>(std::floor(std::abs(tint)*64.0+0.5));
    History staged;
    if (history) {
        staged=*history;
        const auto root=staged.append(EventKind::Bind,0,object_id);
        const auto effect_id=static_cast<std::uint32_t>((tint>0 ? 100u : tint<0 ? 200u : 300u)+amount);
        const auto pop=staged.append(EventKind::Pop,root,effect_id);
        staged.append(EventKind::Collapse,pop,object_id);
    }
    std::size_t changed=0;
    if (amount) for (std::size_t i=0;i<depth_cells;++i) {
        if (!(depth[i]<1.0f)) continue;
        auto* p=rgba+4*i;
        const auto old_r=p[0],old_b=p[2];
        if (tint>0) {
            p[0]=static_cast<std::uint8_t>(std::max(0,int(old_r)-amount));
            p[2]=static_cast<std::uint8_t>(std::min(255,int(old_b)+amount));
        } else {
            p[0]=static_cast<std::uint8_t>(std::min(255,int(old_r)+amount));
            p[2]=static_cast<std::uint8_t>(std::max(0,int(old_b)-amount));
        }
        changed+=(p[0]!=old_r || p[2]!=old_b);
    }
    if (history) *history=staged;
    return {factor,changed,history ? history->fingerprint() : 0ull};
}
} // namespace are::raster::experimental
