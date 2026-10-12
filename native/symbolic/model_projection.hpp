// Bounded perspective projection and homogeneous clipping for the model probe.
// The legacy ARERIN01 raster contract is intentionally unaffected.
#pragma once
#include "workrooms.hpp"
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>

namespace are::models::projection {
using are::rooms::Vertex;
using are::rooms::SurfaceVertex;
using V3 = std::array<double, 3>;

struct Camera {
    V3 eye{0.0, 0.0, 4.0};
    V3 target{0.0, 0.0, 0.0};
    V3 up{0.0, 1.0, 0.0};
    double fov_y_degrees = 43.0;
    double near_plane = 0.1;
    double far_plane = 80.0;
};

inline V3 subtract(const V3& a, const V3& b) {
    return {a[0]-b[0], a[1]-b[1], a[2]-b[2]};
}
inline double dot(const V3& a, const V3& b) {
    return (a[0]*b[0] + a[1]*b[1]) + a[2]*b[2];
}
inline V3 cross(const V3& a, const V3& b) {
    return {a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]};
}
inline V3 normalize(V3 v, const char* error) {
    const double n2=dot(v,v);
    if(!std::isfinite(n2) || n2<=1e-24) throw std::runtime_error(error);
    const double inv=1.0/std::sqrt(n2);
    for(double& x:v) x*=inv;
    return v;
}
inline void validate_camera(const Camera& c, double aspect) {
    auto finite=[](const V3& v){return std::isfinite(v[0])&&std::isfinite(v[1])&&std::isfinite(v[2]);};
    if(!finite(c.eye)||!finite(c.target)||!finite(c.up)||!std::isfinite(aspect)||aspect<=0.0 ||
       !std::isfinite(c.fov_y_degrees)||c.fov_y_degrees<1.0||c.fov_y_degrees>179.0 ||
       !std::isfinite(c.near_plane)||!std::isfinite(c.far_plane)||c.near_plane<=0.0||c.far_plane<=c.near_plane)
        throw std::runtime_error("MODEL_CAMERA_BOUNDS");
    const auto forward=normalize(subtract(c.target,c.eye),"MODEL_CAMERA_DIRECTION");
    const auto up=normalize(c.up,"MODEL_CAMERA_UP");
    (void)normalize(cross(forward,up),"MODEL_CAMERA_UP_PARALLEL");
}

struct Projector {
    V3 eye{},right{},up{},forward{};
    double focal=1,aspect=1,depth_a=0,depth_b=0;
};
inline Projector make_projector(const Camera& c,double aspect) {
    validate_camera(c,aspect);
    const auto f=normalize(subtract(c.target,c.eye),"MODEL_CAMERA_DIRECTION");
    const auto s=normalize(cross(f,normalize(c.up,"MODEL_CAMERA_UP")),"MODEL_CAMERA_UP_PARALLEL");
    return {c.eye,s,cross(s,f),f,
            1.0/std::tan(c.fov_y_degrees*(3.14159265358979323846/180.0)*0.5),aspect,
            (c.far_plane+c.near_plane)/(c.near_plane-c.far_plane),
            (2.0*c.far_plane*c.near_plane)/(c.near_plane-c.far_plane)};
}
// Right-handed view; camera looks along -Z. Clip depth is OpenGL [-w,+w].
inline Vertex project(const V3& point,const Projector& p) {
    const auto relative=subtract(point,p.eye);
    const double vx=dot(p.right,relative), vy=dot(p.up,relative), vz=-dot(p.forward,relative);
    const double x=(p.focal/p.aspect)*vx, y=p.focal*vy, z=p.depth_a*vz+p.depth_b, w=-vz;
    if(!std::isfinite(x)||!std::isfinite(y)||!std::isfinite(z)||!std::isfinite(w) ||
       std::abs(x)>1e30||std::abs(y)>1e30||std::abs(z)>1e30||std::abs(w)>1e30)
        throw std::runtime_error("MODEL_PROJECTION_NONFINITE");
    return {float(x),float(y),float(z),float(w)};
}
inline Vertex project(const V3& point,const Camera& c,double aspect) {
    return project(point,make_projector(c,aspect));
}

inline double distance(const Vertex& v, unsigned plane) {
    switch(plane) {
        case 0:return double(v.x)+v.w; // left
        case 1:return double(v.w)-v.x; // right
        case 2:return double(v.y)+v.w; // bottom
        case 3:return double(v.w)-v.y; // top
        case 4:return double(v.z)+v.w; // near
        default:return double(v.w)-v.z; // far
    }
}
inline Vertex intersection(const Vertex& a,const Vertex& b,double da,double db,unsigned plane) {
    const double den=da-db;
    if(!std::isfinite(den)||den==0.0) throw std::runtime_error("MODEL_CLIP_PARALLEL_EDGE");
    const double t=std::clamp(da/den,0.0,1.0);
    Vertex v{float(double(a.x)+(double(b.x)-a.x)*t),
             float(double(a.y)+(double(b.y)-a.y)*t),
             float(double(a.z)+(double(b.z)-a.z)*t),
             float(double(a.w)+(double(b.w)-a.w)*t)};
    // Snap the generated point onto its active plane so float rounding cannot
    // make the following strict native admission reject a valid intersection.
    switch(plane) {
        case 0:v.x=-v.w;break; case 1:v.x=v.w;break;
        case 2:v.y=-v.w;break; case 3:v.y=v.w;break;
        case 4:v.z=-v.w;break; default:v.z=v.w;break;
    }
    if(!std::isfinite(v.x)||!std::isfinite(v.y)||!std::isfinite(v.z)||!std::isfinite(v.w))
        throw std::runtime_error("MODEL_CLIP_NONFINITE");
    return v;
}

// A clipped triangle can have at most nine polygon vertices (three initial
// vertices plus one per clip plane). Fan triangulation therefore emits <=7.
// The caller controls output storage and can enforce its scene/budget contract.
template<class Emit>
std::size_t clip_triangle(const std::array<Vertex,3>& triangle, Emit&& emit) {
    constexpr std::size_t capacity=16;
    std::array<Vertex,capacity> a{},b{};
    std::size_t count=3;
    for(std::size_t i=0;i<3;++i) {
        const auto& v=triangle[i];
        if(!std::isfinite(v.x)||!std::isfinite(v.y)||!std::isfinite(v.z)||!std::isfinite(v.w))
            throw std::runtime_error("MODEL_CLIP_NONFINITE");
        a[i]=v;
    }
    for(unsigned plane=0;plane<6&&count;++plane) {
        std::size_t out=0;
        auto push=[&](const Vertex& v){
            if(out>=capacity)throw std::runtime_error("MODEL_CLIP_VERTEX_BUDGET");
            b[out++]=v;
        };
        Vertex previous=a[count-1];double dp=distance(previous,plane);bool prev_inside=dp>=0.0;
        for(std::size_t i=0;i<count;++i) {
            const Vertex current=a[i];const double dc=distance(current,plane);const bool curr_inside=dc>=0.0;
            if(prev_inside&&curr_inside) push(current);
            else if(prev_inside&&!curr_inside) push(intersection(previous,current,dp,dc,plane));
            else if(!prev_inside&&curr_inside) {push(intersection(previous,current,dp,dc,plane));push(current);}
            previous=current;dp=dc;prev_inside=curr_inside;
        }
        count=out;a=b;
    }
    if(count<3)return 0;
    // Float intersections on a later plane may move by one ULP relative to an
    // earlier plane. Clamp only the final homogeneous coordinates to the clip cube.
    for(std::size_t i=0;i<count;++i) {
        auto& v=a[i];
        if(!(v.w>0.0f)||!std::isfinite(v.w))throw std::runtime_error("MODEL_CLIP_W");
        v.x=std::clamp(v.x,-v.w,v.w);v.y=std::clamp(v.y,-v.w,v.w);v.z=std::clamp(v.z,-v.w,v.w);
    }
    std::size_t emitted=0;
    for(std::size_t i=1;i+1<count;++i) {
        emit(std::array<Vertex,3>{a[0],a[i],a[i+1]});
        ++emitted;
    }
    if(emitted>7)throw std::runtime_error("MODEL_CLIP_TRIANGLE_BUDGET");
    return emitted;
}

inline SurfaceVertex surface_intersection(const SurfaceVertex& a,const SurfaceVertex& b,
                                           double da,double db,unsigned plane) {
    const double den=da-db;if(!std::isfinite(den)||den==0)throw std::runtime_error("MODEL_CLIP_PARALLEL_EDGE");
    const double t=std::clamp(da/den,0.0,1.0);SurfaceVertex v;
    auto mix=[&](float x,float y){return float(double(x)+(double(y)-x)*t);};
    v.clip={mix(a.clip.x,b.clip.x),mix(a.clip.y,b.clip.y),mix(a.clip.z,b.clip.z),mix(a.clip.w,b.clip.w)};
    for(int k=0;k<3;++k){v.world[k]=mix(a.world[k],b.world[k]);v.normal[k]=mix(a.normal[k],b.normal[k]);}
    for(int k=0;k<2;++k)v.uv[k]=mix(a.uv[k],b.uv[k]);
    switch(plane){case 0:v.clip.x=-v.clip.w;break;case 1:v.clip.x=v.clip.w;break;
        case 2:v.clip.y=-v.clip.w;break;case 3:v.clip.y=v.clip.w;break;
        case 4:v.clip.z=-v.clip.w;break;default:v.clip.z=v.clip.w;break;}
    for(float x:{v.clip.x,v.clip.y,v.clip.z,v.clip.w})if(!std::isfinite(x))throw std::runtime_error("MODEL_CLIP_NONFINITE");
    return v;
}
template<class Emit>
std::size_t clip_surface_triangle(const std::array<SurfaceVertex,3>& triangle,Emit&& emit) {
    constexpr std::size_t capacity=16;std::array<SurfaceVertex,capacity> a{},b{};std::size_t count=3;
    for(std::size_t i=0;i<3;++i){const auto& v=triangle[i];
        for(float x:{v.clip.x,v.clip.y,v.clip.z,v.clip.w})if(!std::isfinite(x))throw std::runtime_error("MODEL_CLIP_NONFINITE");
        for(float x:v.world)if(!std::isfinite(x))throw std::runtime_error("MODEL_SURFACE_POSITION");
        for(float x:v.normal)if(!std::isfinite(x))throw std::runtime_error("MODEL_SURFACE_NORMAL");
        for(float x:v.uv)if(!std::isfinite(x))throw std::runtime_error("MODEL_SURFACE_UV");
        a[i]=v;}
    for(unsigned plane=0;plane<6&&count;++plane){std::size_t out=0;
        auto push=[&](const SurfaceVertex& v){if(out>=capacity)throw std::runtime_error("MODEL_CLIP_VERTEX_BUDGET");b[out++]=v;};
        auto previous=a[count-1];double dp=distance(previous.clip,plane);bool prev=dp>=0;
        for(std::size_t i=0;i<count;++i){const auto current=a[i];const double dc=distance(current.clip,plane);const bool inside=dc>=0;
            if(prev&&inside)push(current);
            else if(prev&&!inside)push(surface_intersection(previous,current,dp,dc,plane));
            else if(!prev&&inside){push(surface_intersection(previous,current,dp,dc,plane));push(current);}
            previous=current;dp=dc;prev=inside;}
        count=out;a=b;
    }
    if(count<3)return 0;
    for(std::size_t i=0;i<count;++i){auto& v=a[i].clip;if(!(v.w>0)||!std::isfinite(v.w))throw std::runtime_error("MODEL_CLIP_W");
        v.x=std::clamp(v.x,-v.w,v.w);v.y=std::clamp(v.y,-v.w,v.w);v.z=std::clamp(v.z,-v.w,v.w);}
    std::size_t emitted=0;for(std::size_t i=1;i+1<count;++i){emit(std::array<SurfaceVertex,3>{a[0],a[i],a[i+1]});++emitted;}
    if(emitted>7)throw std::runtime_error("MODEL_CLIP_TRIANGLE_BUDGET");
    return emitted;
}
} // namespace are::models::projection
