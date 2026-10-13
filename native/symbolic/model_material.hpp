// OuroborosCollective. Repository license applies.
// Versioned native glTF metallic-roughness surface path (AREMDL03 only).
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace are::rooms {
struct ClipPosition { float x=0,y=0,z=0,w=1; };
using SurfaceV2=std::array<float,2>;
using SurfaceV3=std::array<float,3>;
struct SurfaceVertex {
    ClipPosition clip{};
    SurfaceV3 world{};
    SurfaceV3 normal{};
    SurfaceV2 uv{};
};
struct SurfaceTriangle {
    std::array<ClipPosition,3> v{};
    std::array<SurfaceV3,3> world{};
    std::array<SurfaceV3,3> normal{};
    std::array<SurfaceV2,3> uv{};
    std::uint32_t material=0;
};
struct SurfaceMip { std::uint32_t width=0,height=0; std::vector<std::uint8_t> rgba; };
struct SurfaceTexture {
    std::vector<SurfaceMip> mips;
    std::uint32_t wrap_s=10497,wrap_t=10497,min_filter=9987,mag_filter=9729;
    bool srgb=false;
    std::size_t mip_bytes()const {std::size_t n=0;for(const auto& m:mips)n+=m.rgba.size();return n;}
    void build_mips() {
        if(mips.empty() || mips[0].width<1 || mips[0].height<1 ||
           mips[0].rgba.size()!=std::size_t(mips[0].width)*mips[0].height*4)
            throw std::runtime_error("MODEL_TEXTURE_SHAPE");
        if(mips[0].width>4096 || mips[0].height>4096)throw std::runtime_error("MODEL_TEXTURE_DIMENSIONS");
        for(const auto v:{wrap_s,wrap_t})if(v!=10497&&v!=33071&&v!=33648)throw std::runtime_error("MODEL_TEXTURE_WRAP");
        if(mag_filter!=9728&&mag_filter!=9729)throw std::runtime_error("MODEL_TEXTURE_MAG_FILTER");
        if(min_filter!=9728&&min_filter!=9729&&(min_filter<9984||min_filter>9987))throw std::runtime_error("MODEL_TEXTURE_MIN_FILTER");
        while(mips.back().width>1 || mips.back().height>1) {
            const auto& src=mips.back(); SurfaceMip dst;
            dst.width=std::max(1u,src.width/2);dst.height=std::max(1u,src.height/2);
            const auto bytes=std::size_t(dst.width)*dst.height*4;
            if(bytes>768u*1024u*1024u || mip_bytes()>768u*1024u*1024u-bytes)
                throw std::runtime_error("MODEL_TEXTURE_MIP_BUDGET");
            dst.rgba.resize(bytes);
            auto srgb_decode=[](double x){return x<=0.04045?x/12.92:std::pow((x+0.055)/1.055,2.4);};
            auto srgb_encode=[](double x){x=std::clamp(x,0.0,1.0);return x<=0.0031308?12.92*x:1.055*std::pow(x,1.0/2.4)-0.055;};
            for(std::uint32_t y=0;y<dst.height;++y)for(std::uint32_t x=0;x<dst.width;++x) {
                double sum[4]={0,0,0,0};unsigned count=0;
                for(unsigned dy=0;dy<2;++dy)for(unsigned dx=0;dx<2;++dx) {
                    const auto sx=std::min(src.width-1,2*x+dx),sy=std::min(src.height-1,2*y+dy);
                    const auto at=(std::size_t(sy)*src.width+sx)*4;
                    for(unsigned c=0;c<4;++c){double q=double(src.rgba[at+c])/255.0;
                        if(srgb&&c<3)q=srgb_decode(q);
                        sum[c]+=q;}
                    ++count;
                }
                const auto to=(std::size_t(y)*dst.width+x)*4;
                for(unsigned c=0;c<4;++c){double q=sum[c]/count;if(srgb&&c<3)q=srgb_encode(q);
                    dst.rgba[to+c]=std::uint8_t(std::clamp(std::floor(q*255.0+0.5),0.0,255.0));}
            }
            mips.push_back(std::move(dst));
        }
    }
};
struct SurfaceMaterial {
    std::array<float,4> base_color{1,1,1,1};
    std::array<float,3> emissive{0,0,0};
    float metallic=1,roughness=1,normal_scale=1,occlusion_strength=1;
    std::int32_t base_texture=-1,mr_texture=-1,normal_texture=-1,emissive_texture=-1,occlusion_texture=-1;
    bool double_sided=true;
};
struct SurfaceLighting {
    SurfaceV3 light_direction{-.42f,.82f,.38f}; // direction from surface toward the directional key light
    SurfaceV3 radiance{3.2f,3.0f,2.8f};
    SurfaceV3 camera{0,0,4};
    float ambient=0.035f;
    float exposure=1.0f;
};

inline double surface_srgb_to_linear(double x) {
    return x<=0.04045?x/12.92:std::pow((x+0.055)/1.055,2.4);
}
inline double surface_linear_to_srgb(double x) {
    x=std::max(0.0,x);return x<=0.0031308?12.92*x:1.055*std::pow(x,1.0/2.4)-0.055;
}
inline SurfaceV3 surface_normalize(SurfaceV3 v,const char* code="MODEL_SURFACE_NORMAL") {
    const double n2=double(v[0])*v[0]+double(v[1])*v[1]+double(v[2])*v[2];
    if(!std::isfinite(n2)||n2<1e-20)throw std::runtime_error(code);
    const auto inv=float(1.0/std::sqrt(n2));for(auto& x:v)x*=inv;return v;
}
inline float surface_dot(const SurfaceV3& a,const SurfaceV3& b) {
    return (a[0]*b[0]+a[1]*b[1])+a[2]*b[2];
}
template<std::size_t N>
inline std::array<float,N> surface_perspective_interpolate(const std::array<float,3>& lambda,
        const std::array<float,3>& reciprocal_w,const std::array<std::array<float,N>,3>& value_over_w) {
    double denominator=0;std::array<double,N> numerator{};
    for(int i=0;i<3;++i){denominator+=double(lambda[i])*reciprocal_w[i];
        for(std::size_t k=0;k<N;++k)numerator[k]+=double(lambda[i])*value_over_w[i][k];}
    if(!(denominator>1e-12)||!std::isfinite(denominator))throw std::runtime_error("MODEL_SURFACE_RECIPROCAL_W");
    std::array<float,N> out{};for(std::size_t k=0;k<N;++k){out[k]=float(numerator[k]/denominator);
        if(!std::isfinite(out[k]))throw std::runtime_error("MODEL_SURFACE_INTERPOLATION");}
    return out;
}
inline SurfaceV3 surface_add(SurfaceV3 a,const SurfaceV3& b) {for(int i=0;i<3;++i)a[i]+=b[i];return a;}
inline SurfaceV3 surface_mul(SurfaceV3 a,float b) {for(auto& x:a)x*=b;return a;}
inline SurfaceV3 surface_hadamard(const SurfaceV3& a,const SurfaceV3& b) {
    return {a[0]*b[0],a[1]*b[1],a[2]*b[2]};
}
inline double surface_wrap_coordinate(double u,std::uint32_t mode) {
    if(!std::isfinite(u))throw std::runtime_error("MODEL_TEXTURE_UV_NONFINITE");
    if(mode==10497){u-=std::floor(u);return u;}
    if(mode==33071)return std::clamp(u,0.0,1.0);
    if(mode==33648){double q=std::fmod(u,2.0);if(q<0)q+=2.0;return q<=1.0?q:2.0-q;}
    throw std::runtime_error("MODEL_TEXTURE_WRAP");
}
inline std::array<double,4> surface_texel(const SurfaceTexture& t,unsigned level,int x,int y,bool linear) {
    const auto& m=t.mips.at(level);const auto index=[&](int i,int n,std::uint32_t mode){
        if(mode==10497){int q=i%n;return q<0?q+n:q;}
        return std::clamp(i,0,n-1);
    };
    x=index(x,int(m.width),t.wrap_s);y=index(y,int(m.height),t.wrap_t);
    const auto at=(std::size_t(y)*m.width+std::size_t(x))*4;std::array<double,4> c{};
    for(unsigned k=0;k<4;++k){c[k]=double(m.rgba[at+k])/255.0;if(linear&&t.srgb&&k<3)c[k]=surface_srgb_to_linear(c[k]);}
    return c;
}
inline std::array<double,4> surface_sample_level(const SurfaceTexture& t,unsigned level,double u,double v,bool linear) {
    const auto& m=t.mips.at(level);u=surface_wrap_coordinate(u,t.wrap_s);v=surface_wrap_coordinate(v,t.wrap_t);
    if(!linear){const int x=std::min(int(m.width)-1,int(std::floor(u*m.width)));
        const int y=std::min(int(m.height)-1,int(std::floor(v*m.height)));
        return surface_texel(t,level,x,y,true);}
    const double x=u*m.width-.5,y=v*m.height-.5;const int x0=int(std::floor(x)),y0=int(std::floor(y));
    const double fx=x-x0,fy=y-y0;const auto a=surface_texel(t,level,x0,y0,true),b=surface_texel(t,level,x0+1,y0,true);
    const auto c=surface_texel(t,level,x0,y0+1,true),d=surface_texel(t,level,x0+1,y0+1,true);std::array<double,4> out{};
    for(int k=0;k<4;++k)out[k]=(1-fy)*((1-fx)*a[k]+fx*b[k])+fy*((1-fx)*c[k]+fx*d[k]);
    return out;
}
inline std::array<double,4> surface_sample(const SurfaceTexture& t,double u,double v,double lod) {
    if(t.mips.empty())throw std::runtime_error("MODEL_TEXTURE_MIPS");
    const bool magnify=lod<=0;const auto filter=magnify?t.mag_filter:t.min_filter;
    if(filter==9728||filter==9729)return surface_sample_level(t,0,u,v,filter==9729);
    const double l=std::clamp(lod,0.0,double(t.mips.size()-1));
    if(filter==9984||filter==9985){const auto level=unsigned(std::clamp(std::floor(l+.5),0.0,double(t.mips.size()-1)));
        return surface_sample_level(t,level,u,v,filter==9985);}
    if(filter==9986||filter==9987){const unsigned lo=unsigned(std::floor(l)),hi=std::min<unsigned>(lo+1,unsigned(t.mips.size()-1));
        const auto a=surface_sample_level(t,lo,u,v,filter==9987),b=surface_sample_level(t,hi,u,v,filter==9987);std::array<double,4> out{};
        for(int k=0;k<4;++k)out[k]=a[k]+(b[k]-a[k])*(l-lo);
        return out;}
    throw std::runtime_error("MODEL_TEXTURE_MIN_FILTER");
}
inline std::array<double,4> surface_sample_grad(const SurfaceTexture& t,const SurfaceV2& uv,
                                               const SurfaceV2& dx,const SurfaceV2& dy) {
    if(t.mips.empty())throw std::runtime_error("MODEL_TEXTURE_MIPS");
    const auto& base=t.mips[0];
    const double rx=std::hypot(double(dx[0])*base.width,double(dx[1])*base.height);
    const double ry=std::hypot(double(dy[0])*base.width,double(dy[1])*base.height);
    const double rho=std::max(rx,ry);
    const double lod=rho>1e-12?std::log2(rho):-40.0;
    return surface_sample(t,uv[0],uv[1],lod);
}
inline std::array<double,4> surface_binding(const std::vector<SurfaceTexture>& textures,std::int32_t id,
        const SurfaceV2& uv,const SurfaceV2& dx,const SurfaceV2& dy,const std::array<double,4>& fallback) {
    if(id<0)return fallback;
    if(std::size_t(id)>=textures.size())throw std::runtime_error("MODEL_MATERIAL_TEXTURE_INDEX");
    return surface_sample_grad(textures[std::size_t(id)],uv,dx,dy);
}
inline SurfaceV3 surface_pbr(const SurfaceMaterial& m,const std::vector<SurfaceTexture>& textures,
        const SurfaceV2& uv,const SurfaceV3& interpolated_normal,const SurfaceV3& tangent_in,
        const SurfaceV3& bitangent_in,const SurfaceV3& world,const SurfaceV2& duvdx,
        const SurfaceV2& duvdy,const SurfaceLighting& light) {
    constexpr double pi=3.14159265358979323846;
    const auto white=std::array<double,4>{1,1,1,1};
    const auto base_tex=surface_binding(textures,m.base_texture,uv,duvdx,duvdy,white);
    const auto mr=surface_binding(textures,m.mr_texture,uv,duvdx,duvdy,white);
    auto base=SurfaceV3{float(base_tex[0]*m.base_color[0]),float(base_tex[1]*m.base_color[1]),float(base_tex[2]*m.base_color[2])};
    const float metallic=std::clamp(float(mr[2])*m.metallic,0.0f,1.0f);
    const float roughness=std::clamp(float(mr[1])*m.roughness,0.045f,1.0f);
    auto N=surface_normalize(interpolated_normal);
    const auto V=surface_normalize(SurfaceV3{light.camera[0]-world[0],light.camera[1]-world[1],light.camera[2]-world[2]});
    if(m.double_sided&&surface_dot(N,V)<0)N=surface_mul(N,-1.0f);
    const double tangent_len=double(surface_dot(tangent_in,tangent_in));
    if(m.normal_texture>=0&&tangent_len>1e-16) {
        auto T=SurfaceV3{tangent_in[0]-N[0]*surface_dot(N,tangent_in),
                         tangent_in[1]-N[1]*surface_dot(N,tangent_in),
                         tangent_in[2]-N[2]*surface_dot(N,tangent_in)};
        const double t2=surface_dot(T,T);
        const double b2=surface_dot(bitangent_in,bitangent_in);
        if(std::isfinite(t2)&&t2>1e-16&&std::isfinite(b2)&&b2>1e-16) {
            T=surface_normalize(T);
            auto B=surface_normalize(SurfaceV3{bitangent_in[0]-N[0]*surface_dot(N,bitangent_in)-T[0]*surface_dot(T,bitangent_in),
                                                bitangent_in[1]-N[1]*surface_dot(N,bitangent_in)-T[1]*surface_dot(T,bitangent_in),
                                                bitangent_in[2]-N[2]*surface_dot(N,bitangent_in)-T[2]*surface_dot(T,bitangent_in)});
            const auto map=surface_binding(textures,m.normal_texture,uv,duvdx,duvdy,{.5,.5,1,1});
            SurfaceV3 q{float((2*map[0]-1)*m.normal_scale),float((2*map[1]-1)*m.normal_scale),float(2*map[2]-1)};
            q=surface_normalize(q);
            N=surface_normalize(SurfaceV3{T[0]*q[0]+B[0]*q[1]+N[0]*q[2],
                                           T[1]*q[0]+B[1]*q[1]+N[1]*q[2],
                                           T[2]*q[0]+B[2]*q[1]+N[2]*q[2]});
        }
    }
    const auto L=surface_normalize(light.light_direction);
    const auto H=surface_normalize(SurfaceV3{V[0]+L[0],V[1]+L[1],V[2]+L[2]});
    const double nv=std::max(0.0,double(surface_dot(N,V))),nl=std::max(0.0,double(surface_dot(N,L)));
    const double nh=std::max(0.0,double(surface_dot(N,H))),vh=std::max(0.0,double(surface_dot(V,H)));
    const double alpha=double(roughness)*roughness,alpha2=alpha*alpha;
    const double term=nh*nh*(alpha2-1.0)+1.0;
    const double D=alpha2/(pi*term*term+1e-12);
    const double k=std::pow(double(roughness)+1.0,2.0)/8.0;
    const double Gv=nv/(nv*(1.0-k)+k+1e-12),Gl=nl/(nl*(1.0-k)+k+1e-12),G=Gv*Gl;
    const double fterm=std::pow(std::max(0.0,1.0-vh),5.0);
    SurfaceV3 result{},direct_light{},ambient_light{};
    for(int c=0;c<3;++c) {
        const double f0=.04*(1.0-metallic)+base[c]*metallic;
        const double F=f0+(1.0-f0)*fterm;
        const double spec=D*G*F/(4.0*nv*nl+1e-8);
        const double diffuse=(1.0-F)*(1.0-metallic)*base[c]/pi;
        direct_light[c]=float((diffuse+spec)*light.radiance[c]*nl);
        ambient_light[c]=float(base[c]*(1.0-metallic)*light.ambient);
        result[c]=direct_light[c]+ambient_light[c];
    }
    if(m.occlusion_texture>=0) {
        const auto ao=surface_binding(textures,m.occlusion_texture,uv,duvdx,duvdy,white);
        const double factor=1.0-std::clamp(double(m.occlusion_strength),0.0,1.0)*(1.0-ao[0]);
        for(int c=0;c<3;++c)result[c]=float(direct_light[c]+ambient_light[c]*factor);
    }
    const auto emissive_tex=surface_binding(textures,m.emissive_texture,uv,duvdx,duvdy,white);
    for(int c=0;c<3;++c)result[c]+=float(double(m.emissive[c])*emissive_tex[c]);
    for(float c:result)if(!std::isfinite(c)||c<0||c>1e12f)throw std::runtime_error("MODEL_PBR_NONFINITE");
    return result;
}
} // namespace are::rooms
