// OuroborosCollective. Repository license applies.
#pragma once
#include "../symbolic/core.hpp"
#include <cstddef>

namespace are::raster {
// Packed doubles: screen[3][3], f32 inverse-W[3], f32 inverse-area,
// weighted RGB[3][3], three dtype bits (one for each f64 color term).
inline constexpr std::size_t stride = 23, max_triangles = 200000;
inline constexpr std::uint64_t max_samples = 64000000;
enum Status { ok=0, buffer=1, budget=2, environment=3, record=4, work_budget=5 };
struct Triangle {
    float s[3][3], iw[3], ia;
    double color[3][3];
    unsigned wide;
};
inline Triangle unpack(const double* p) {
    Triangle t{};
    for (int i=0;i<3;++i) {
        for (int k=0;k<3;++k) {
            t.s[i][k]=static_cast<float>(p[i*3+k]);
            t.color[i][k]=p[13+i*3+k];
        }
        t.iw[i]=static_cast<float>(p[9+i]);
    }
    t.ia=static_cast<float>(p[12]); t.wide=static_cast<unsigned>(p[22]);
    return t;
}
inline float edge(const float* a,const float* b,float x,float y) {
    return (x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0]);
}
inline bool top_left(const float* a,const float* b) {
    const float dy=b[1]-a[1],dx=b[0]-a[0];
    return dy>0.0f || (dy==0.0f && dx<0.0f);
}
struct Bounds { int x0,x1,y0,y1; };
inline Bounds bounds(const Triangle& t,int w,int h) {
    return {std::max(0,static_cast<int>(std::floor(std::min({t.s[0][0],t.s[1][0],t.s[2][0]})))),
            std::min(w-1,static_cast<int>(std::ceil(std::max({t.s[0][0],t.s[1][0],t.s[2][0]})))),
            std::max(0,static_cast<int>(std::floor(std::min({t.s[0][1],t.s[1][1],t.s[2][1]})))),
            std::min(h-1,static_cast<int>(std::ceil(std::max({t.s[0][1],t.s[1][1],t.s[2][1]}))))};
}
inline double term(float bary,double weight,bool wide) {
    return wide ? static_cast<double>(bary)*weight : static_cast<double>(bary*static_cast<float>(weight));
}
inline std::uint8_t shade(const Triangle& t,int channel,float a,float b,float c,float factor) {
    // NumPy promotes at each operation, not retroactively for the whole DAG.
    // A clipped triangle can mix f32 and f64 at its three vertices.
    const double p=term(a,t.color[0][channel],t.wide&1u);
    const double q=term(b,t.color[1][channel],t.wide&2u);
    const double r=term(c,t.color[2][channel],t.wide&4u);
    const double pq=(t.wide&3u) ? p+q : static_cast<double>(static_cast<float>(p)+static_cast<float>(q));
    const double sum=t.wide ? pq+r : static_cast<double>(static_cast<float>(pq)+static_cast<float>(r));
    const double color=t.wide ? sum*static_cast<double>(factor) : static_cast<double>(static_cast<float>(sum)*factor);
    const double scaled=t.wide ? color*255.0 : static_cast<double>(static_cast<float>(color)*255.0f);
    return static_cast<std::uint8_t>(std::clamp(scaled,0.0,255.0));
}

// Synchronous, single-worker API. All buffers are caller-owned and disjoint.
// Validate the entire bounded draw before writing any color/depth/counters.
// No allocations, Python callbacks, textures, blending, or incremental edges.
inline int draw(const double* packed,std::size_t cells,std::size_t count,
                int width,int height,std::uint8_t* rgba,std::size_t rgba_bytes,
                float* depth,std::size_t depth_cells,std::uint64_t* counts,std::size_t count_cells) {
    static_assert(sizeof(double)==8 && std::numeric_limits<double>::is_iec559,"IEEE f64 required");
    if (width<1 || height<1 || width>4096 || height>4096 ||
        std::uint64_t(width)*height>4194304 || count>max_triangles) return budget;
    const auto pixels=static_cast<std::size_t>(width)*height;
    if ((count && !packed) || !rgba || !depth || !counts || cells!=count*stride ||
        rgba_bytes!=pixels*4 || depth_cells!=pixels || count_cells!=3) return buffer;
    try { require_environment(); } catch (const std::runtime_error&) { return environment; }
    std::uint64_t candidates=0;
    for (std::size_t i=0;i<count;++i) {
        const double* p=packed+i*stride;
        for (std::size_t k=0;k<stride;++k) if (!std::isfinite(p[k])) return record;
        if (p[22]<0 || p[22]>7 || std::floor(p[22])!=p[22]) return record;
        for (int v=0;v<3;++v) {
            if (p[v*3]<-1 || p[v*3]>width+1 || p[v*3+1]<-1 || p[v*3+1]>height+1 ||
                std::abs(p[v*3+2])>2 || p[9+v]<=0 || p[9+v]>1e7) return record;
        }
        if (p[12]<=0 || p[12]>1e9) return record;
        for (int k=13;k<22;++k) if (std::abs(p[k])>1e9) return record;
        const auto t=unpack(p);
        const float area=edge(t.s[0],t.s[1],t.s[2][0],t.s[2][1]);
        if (!(area>1e-9f) || t.ia!=static_cast<float>(1.0/static_cast<double>(area))) return record;
        const auto box=bounds(t,width,height);
        if (box.x1>=box.x0 && box.y1>=box.y0)
            candidates+=std::uint64_t(box.x1-box.x0+1)*(box.y1-box.y0+1);
        if (candidates>max_samples) return work_budget;
    }
    std::uint64_t covered=0,passed=0;
    for (std::size_t i=0;i<count;++i) {
        const auto t=unpack(packed+i*stride);
        const auto box=bounds(t,width,height);
        const bool tl0=top_left(t.s[1],t.s[2]),tl1=top_left(t.s[2],t.s[0]),tl2=top_left(t.s[0],t.s[1]);
        for (int y=box.y0;y<=box.y1;++y) for (int x=box.x0;x<=box.x1;++x) {
            const float px=static_cast<float>(x)+0.5f,py=static_cast<float>(y)+0.5f;
            const float w0=edge(t.s[1],t.s[2],px,py),w1=edge(t.s[2],t.s[0],px,py),w2=edge(t.s[0],t.s[1],px,py);
            if (!(tl0 ? w0>=0 : w0>0) || !(tl1 ? w1>=0 : w1>0) || !(tl2 ? w2>=0 : w2>0)) continue;
            ++covered;
            const float a=w0*t.ia,b=w1*t.ia,c=w2*t.ia;
            const float z=(a*t.s[0][2]+b*t.s[1][2])+c*t.s[2][2];
            const auto index=static_cast<std::size_t>(y)*width+x;
            if (!(z<depth[index])) continue;
            const float iw=(a*t.iw[0]+b*t.iw[1])+c*t.iw[2];
            const float factor=iw>1e-9f ? 1.0f/iw : 1.0f;
            for (int k=0;k<3;++k) rgba[index*4+k]=shade(t,k,a,b,c,factor);
            rgba[index*4+3]=255;depth[index]=z;++passed;
        }
    }
    counts[0]=candidates;counts[1]=covered;counts[2]=passed;
    return ok;
}
} // namespace are::raster
