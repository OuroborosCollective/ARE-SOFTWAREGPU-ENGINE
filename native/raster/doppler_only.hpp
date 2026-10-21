// OuroborosCollective, repository license applies.
// C++17 classical direct Doppler; no SpherePop code, queue, history or event graph.
#pragma once
#include <algorithm>
#include <cfenv>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <vector>
#if defined(__SSE__)
#include <xmmintrin.h>
#endif
#ifdef __FAST_MATH__
#error Fast math prohibited
#endif
namespace are::raster::doppler_only {
struct Vec3 { double x,y,z; };
struct Result { std::size_t visited_pixels, tinted_pixels; };
inline bool finite(Vec3 p) {return std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z);}
inline void environment() {
    if(std::fegetround()!=FE_TONEAREST)throw std::invalid_argument("DOPPLER_ONLY_INPUT_INVALID");
#if defined(__SSE__)
    if(_mm_getcsr()&((1u<<15)|(1u<<6)))throw std::invalid_argument("DOPPLER_ONLY_INPUT_INVALID");
#endif
}
inline double classical_factor(Vec3 source,Vec3 observer,Vec3 velocity,double speed) {
    if(!finite(source)||!finite(observer)||!finite(velocity)||
       !std::isfinite(speed)||speed<=0)throw std::invalid_argument("DOPPLER_ONLY_INPUT_INVALID");
    environment();
    const double v=std::hypot(velocity.x,std::hypot(velocity.y,velocity.z));
    if(!std::isfinite(v)||!(v<.95*speed))
        throw std::invalid_argument("DOPPLER_ONLY_VELOCITY_BUDGET");
    const double dx=observer.x-source.x,dy=observer.y-source.y,dz=observer.z-source.z;
    const double d=std::hypot(dx,std::hypot(dy,dz));
    if(!std::isfinite(d))throw std::invalid_argument("DOPPLER_ONLY_INPUT_INVALID");
    if(d<=1.e-12)return 1.;
    const double radial=(velocity.x*dx+velocity.y*dy+velocity.z*dz)/d;
    const double f=speed/(speed-radial);
    if(!std::isfinite(f))throw std::invalid_argument("DOPPLER_ONLY_INPUT_INVALID");
    return f;
}
inline Result apply_direct(std::uint8_t* rgba,std::size_t bytes,
                           const float* depth,std::size_t cells,
                           const std::uint32_t* owners,std::size_t owner_cells,
                           int width,int height,int sx,int sy,
                           Vec3 velocity,double speed,double gain,
                           std::uint32_t object_id) {
    if(width<1||height<1||width>2048||height>2048||
       std::uint64_t(width)*height>4194304||sx<0||sx>=width||sy<0||sy>=height||
       !rgba||!depth||!owners||!object_id||cells!=std::size_t(width)*height||
       bytes!=cells*4||owner_cells!=cells||!finite(velocity)||
       !std::isfinite(speed)||speed<=0||!std::isfinite(gain)||gain<0||gain>16)
        throw std::invalid_argument("DOPPLER_ONLY_BUFFER_INVALID");
    environment();
    const double v=std::hypot(velocity.x,std::hypot(velocity.y,velocity.z));
    if(!std::isfinite(v)||!(v<.95*speed))
        throw std::invalid_argument("DOPPLER_ONLY_VELOCITY_BUDGET");
    for(std::size_t i=0;i<cells;++i)
        if(!std::isfinite(depth[i])||depth[i]<0||depth[i]>1||
           (owners[i] && !(depth[i]<1)))
            throw std::invalid_argument("DOPPLER_ONLY_DEPTH_INVALID");
    std::vector<std::uint8_t> staged(rgba,rgba+bytes);
    std::size_t changed=0;
    for(int y=0;y<height;++y)for(int x=0;x<width;++x) {
        const std::size_t i=std::size_t(y)*width+x;
        if(owners[i]!=object_id||!(depth[i]<1))continue;
        const double dx=double(x-sx),dy=double(y-sy),d=std::hypot(dx,dy);
        if(d<=1.e-12)continue;
        const double radial=(velocity.x*dx+velocity.y*dy)/d;
        const double factor=speed/(speed-radial);
        if(!std::isfinite(factor))throw std::invalid_argument("DOPPLER_ONLY_INPUT_INVALID");
        const double tint=std::clamp((factor-1.)*gain,-1.,1.);
        const int amount=int(std::floor(std::abs(tint)*64.+.5));
        if(!amount)continue;
        auto* p=staged.data()+4*i;auto old_r=p[0],old_b=p[2];
        if(tint>0) {
            p[0]=std::uint8_t(std::max(0,int(old_r)-amount));
            p[2]=std::uint8_t(std::min(255,int(old_b)+amount));
        } else {
            p[0]=std::uint8_t(std::min(255,int(old_r)+amount));
            p[2]=std::uint8_t(std::max(0,int(old_b)-amount));
        }
        changed+=(p[0]!=old_r||p[2]!=old_b);
    }
    std::memcpy(rgba,staged.data(),bytes);
    return {cells,changed};
}
}
