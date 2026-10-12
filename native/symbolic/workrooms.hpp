// OuroborosCollective. Repository license applies.
// Actual native render work rooms. Colours are operation tags, never pixels.
#pragma once
#include "core.hpp"
#include "model_material.hpp"
#include <atomic>
#include <chrono>
#include <exception>
#include <mutex>
#include <thread>

namespace are::rooms {
enum class Kind: unsigned { render, raster, msaa, aa };
enum class State: std::uint8_t { waiting, ready, running, done };
constexpr const char* names[]={"render","raster","msaa","aa"};
constexpr const char* colors[]={"green","blue","orange","purple"};
struct Config { std::uint32_t width,height,tile,frame; };
using Vertex=ClipPosition;
struct Triangle { std::array<Vertex,3> v; std::array<std::uint8_t,4> rgba; };
struct Prepared {
    std::array<Vertex,3> v{}; float area=0; std::array<std::uint8_t,4> rgba{};
    std::array<bool,3> inclusive_edges{}; bool surface=false; std::uint32_t material=0;
    std::array<float,3> reciprocal_w{};
    std::array<SurfaceV2,3> uv_over_w{};
    std::array<SurfaceV3,3> normal_over_w{},world_over_w{};
    SurfaceV3 tangent{},bitangent{};
};
struct Wave { std::uint64_t executed=0, samples=0; double milliseconds=0;
    std::vector<std::uint64_t> worker_jobs; };
enum class Admission { legacy, model_probe };
inline std::size_t validate(Config c,std::size_t triangles,unsigned workers,
                            Admission admission=Admission::legacy) {
    if(c.width<2 || c.height<2 || c.width>1024 || c.height>1024 ||
       c.tile<1 || c.tile>64 || c.frame>1000000 ||
       workers<1 || workers>8)
        throw std::runtime_error("ROOM_BUDGET");
    if(admission==Admission::legacy) {
        if(triangles<1 || triangles>64 || std::uint64_t(c.width)*c.height*triangles>67108864)
            throw std::runtime_error("ROOM_BUDGET");
    } else if(admission==Admission::model_probe) {
        const auto tiles=std::uint64_t((c.width+c.tile-1)/c.tile)*((c.height+c.tile-1)/c.tile);
        if(c.width>512 || c.height>512 || c.tile<16 || triangles>8000000 ||
           tiles*triangles>536870912)throw std::runtime_error("MODEL_RENDER_BUDGET");
    } else throw std::runtime_error("ROOM_ADMISSION");
    return std::size_t(c.width)*c.height;
}
inline float edge(const Vertex& a,const Vertex& b,float x,float y) {
    return (x-a.x)*(b.y-a.y)-(y-a.y)*(b.x-a.x);
}
inline bool covered(float e,const Vertex& a,const Vertex& b) {
    const float dy=b.y-a.y,dx=b.x-a.x;
    return (dy>0 || (dy==0 && dx<0))?e>=0:e>0;
}
inline bool inclusive_edge(const Vertex& a,const Vertex& b) {
    const float dy=b.y-a.y,dx=b.x-a.x;
    return dy>0 || (dy==0 && dx<0);
}
inline bool covered(float e,bool inclusive) {return inclusive?e>=0:e>0;}
class Pipeline {
    friend class BioPipeline; // Optional scheduler shares the exact render operations.
    Config c_; unsigned workers_; Admission admission_; std::size_t pixels_,tiles_x_,tiles_y_,tiles_;
    std::vector<Triangle> triangles_; std::vector<SurfaceTriangle> surface_triangles_;
    std::vector<Prepared> prepared_; bool surface_mode_=false;
    const std::vector<SurfaceMaterial>* materials_=nullptr;
    const std::vector<SurfaceTexture>* textures_=nullptr;
    SurfaceLighting lighting_{};
    std::vector<std::uint8_t> sample_color_,resolved_,final_;
    std::vector<float> sample_linear_;
    std::vector<float> sample_depth_,depth_;
    std::vector<State> states_;
    std::array<Wave,4> waves_;
    std::array<std::array<double,8>,4> operation_work_ms_{};
    bool delivered_=false;
    struct Rect { std::size_t x0,y0,x1,y1; };
    Rect rect(std::size_t tile)const {
        const auto x=(tile%tiles_x_)*c_.tile,y=(tile/tiles_x_)*c_.tile;
        return {x,y,std::min<std::size_t>(x+c_.tile,c_.width),std::min<std::size_t>(y+c_.tile,c_.height)};
    }
    void render_surface(std::size_t i) {
        auto& out=prepared_[i];const auto& t=surface_triangles_[i];out.surface=true;out.material=t.material;
        for(int k=0;k<3;++k){const auto& v=t.v[k];
            if(!(v.w>1e-7f)||!std::isfinite(v.w))throw std::runtime_error("MODEL_SURFACE_CLIP_W");
            const float inv=1.0f/v.w;out.reciprocal_w[k]=inv;
            out.v[k]={float((v.x*inv+1.0f)*0.5f*c_.width),float((1.0f-v.y*inv)*0.5f*c_.height),v.z*inv,1};
            for(int a=0;a<2;++a)out.uv_over_w[k][a]=t.uv[k][a]*inv;
            for(int a=0;a<3;++a){out.normal_over_w[k][a]=t.normal[k][a]*inv;out.world_over_w[k][a]=t.world[k][a]*inv;}
        }
        const auto& p0=t.world[0];const auto& p1=t.world[1];const auto& p2=t.world[2];
        const double e1[3]={double(p1[0])-p0[0],double(p1[1])-p0[1],double(p1[2])-p0[2]};
        const double e2[3]={double(p2[0])-p0[0],double(p2[1])-p0[1],double(p2[2])-p0[2]};
        const double du1=double(t.uv[1][0])-t.uv[0][0],dv1=double(t.uv[1][1])-t.uv[0][1];
        const double du2=double(t.uv[2][0])-t.uv[0][0],dv2=double(t.uv[2][1])-t.uv[0][1];
        const double det=du1*dv2-dv1*du2;out.tangent={};out.bitangent={};
        if(std::isfinite(det)&&std::abs(det)>1e-14)for(int a=0;a<3;++a){
            out.tangent[a]=float((e1[a]*dv2-e2[a]*dv1)/det);
            out.bitangent[a]=float((e2[a]*du1-e1[a]*du2)/det);
        }
        out.area=edge(out.v[0],out.v[1],out.v[2].x,out.v[2].y);
        out.inclusive_edges={inclusive_edge(out.v[1],out.v[2]),inclusive_edge(out.v[2],out.v[0]),
                             inclusive_edge(out.v[0],out.v[1])};
    }
    void render(std::size_t i) {
        if(surface_mode_){render_surface(i);return;}
        auto& out=prepared_[i];const auto& t=triangles_[i];out.rgba=t.rgba;
        out.surface=false;
        for(int k=0;k<3;++k){const auto& v=t.v[k];const double inv=1.0/double(v.w);
            out.v[k]={float((double(v.x)*inv+1.0)*0.5*c_.width),
                      float((1.0-double(v.y)*inv)*0.5*c_.height),float(double(v.z)*inv),1};}
        out.area=edge(out.v[0],out.v[1],out.v[2].x,out.v[2].y);
        out.inclusive_edges={inclusive_edge(out.v[1],out.v[2]),inclusive_edge(out.v[2],out.v[0]),
                             inclusive_edge(out.v[0],out.v[1])};
    }
    void clear_samples(const Rect& r) {
        for(auto y=r.y0;y<r.y1;++y)for(auto x=r.x0;x<r.x1;++x){const auto p=y*c_.width+x;
            for(int s=0;s<4;++s){sample_depth_[p*4+s]=1.0f;
                for(int k=0;k<4;++k){sample_color_[(p*4+s)*4+k]=k==3?255:0;
                    if(surface_mode_)sample_linear_[(p*4+s)*4+k]=k==3?1.0f:0.0f;}}}
    }
    SurfaceV3 shade_surface(const Prepared& t,float l0,float l1,float l2)const {
        if(!materials_||!textures_||t.material>=materials_->size())throw std::runtime_error("MODEL_SURFACE_MATERIAL");
        const float lambda[3]={l0,l1,l2};double q=0,uvnum[2]={0,0};SurfaceV3 normal{},world{};
        for(int i=0;i<3;++i){q+=lambda[i]*t.reciprocal_w[i];
            for(int a=0;a<2;++a)uvnum[a]+=lambda[i]*t.uv_over_w[i][a];
            for(int a=0;a<3;++a){normal[a]+=float(lambda[i]*t.normal_over_w[i][a]);world[a]+=float(lambda[i]*t.world_over_w[i][a]);}}
        if(!(q>1e-12)||!std::isfinite(q))throw std::runtime_error("MODEL_SURFACE_RECIPROCAL_W");
        const SurfaceV2 uv=surface_perspective_interpolate<2>({l0,l1,l2},t.reciprocal_w,t.uv_over_w);
        for(auto& x:normal)x=float(x/q);
        for(auto& x:world)x=float(x/q);
        const auto& a=t.v[0];const auto& b=t.v[1];const auto& c=t.v[2];const double inv_area=1.0/double(t.area);
        const double dx[3]={(c.y-b.y)*inv_area,(a.y-c.y)*inv_area,(b.y-a.y)*inv_area};
        const double dy[3]= {-(c.x-b.x)*inv_area,-(a.x-c.x)*inv_area,-(b.x-a.x)*inv_area};
        double dqx=0,dqy=0,du_num_x[2]={0,0},du_num_y[2]={0,0};
        for(int i=0;i<3;++i){dqx+=dx[i]*t.reciprocal_w[i];dqy+=dy[i]*t.reciprocal_w[i];
            for(int k=0;k<2;++k){du_num_x[k]+=dx[i]*t.uv_over_w[i][k];du_num_y[k]+=dy[i]*t.uv_over_w[i][k];}}
        SurfaceV2 duvdx{},duvdy{};
        for(int k=0;k<2;++k){duvdx[k]=float((du_num_x[k]*q-uvnum[k]*dqx)/(q*q));
            duvdy[k]=float((du_num_y[k]*q-uvnum[k]*dqy)/(q*q));}
        if(!std::isfinite(uv[0])||!std::isfinite(uv[1]))throw std::runtime_error("MODEL_SURFACE_UV");
        return surface_pbr((*materials_)[t.material],*textures_,uv,normal,t.tangent,t.bitangent,world,duvdx,duvdy,lighting_);
    }
    std::uint64_t raster_samples(const Rect& r,const Prepared& t,
            int x0,int x1,int y0,int y1,float inv) {
        (void)r;std::uint64_t samples=0;
        const auto& a=t.v[0];const auto& b=t.v[1];const auto& d=t.v[2];
            for(int y=y0;y<=y1;++y)for(int x=x0;x<=x1;++x)for(int s=0;s<4;++s) {
                const float px=x+(s%2?0.75f:0.25f),py=y+(s/2?0.75f:0.25f);
                const float e0=edge(b,d,px,py),e1=edge(d,a,px,py),e2=edge(a,b,px,py);
                if(!covered(e0,t.inclusive_edges[0])||!covered(e1,t.inclusive_edges[1])||
                   !covered(e2,t.inclusive_edges[2]))continue;
                const float z=((e0*inv)*a.z+(e1*inv)*b.z)+(e2*inv)*d.z;
                const auto index=(std::size_t(y)*c_.width+x)*4+s;
                if(z<sample_depth_[index]){sample_depth_[index]=z;++samples;
                    if(t.surface){const auto color=shade_surface(t,e0*inv,e1*inv,e2*inv);
                        for(int k=0;k<3;++k)sample_linear_[index*4+k]=color[k];
                        sample_linear_[index*4+3]=1.0f;}
                    else for(int k=0;k<4;++k)sample_color_[index*4+k]=t.rgba[k];}
            }
        return samples;
    }
    std::uint64_t raster(std::size_t tile) {
        const auto r=rect(tile);std::uint64_t samples=0;clear_samples(r);
        for(const auto& t:prepared_) {
            if(t.area<=1e-9f)continue;
            const auto& a=t.v[0];const auto& b=t.v[1];const auto& d=t.v[2];
            const auto x0=std::max<int>(int(r.x0),int(std::floor(std::min({a.x,b.x,d.x}))));
            const auto x1=std::min<int>(int(r.x1)-1,int(std::ceil(std::max({a.x,b.x,d.x}))));
            const auto y0=std::max<int>(int(r.y0),int(std::floor(std::min({a.y,b.y,d.y}))));
            const auto y1=std::min<int>(int(r.y1)-1,int(std::ceil(std::max({a.y,b.y,d.y}))));
            const float inv=float(1.0/double(t.area));
            samples+=raster_samples(r,t,x0,x1,y0,y1,inv);
        }
        return samples;
    }
    void msaa(std::size_t tile) {
        const auto r=rect(tile);
        for(auto y=r.y0;y<r.y1;++y)for(auto x=r.x0;x<r.x1;++x){const auto p=y*c_.width+x;
            if(surface_mode_){for(int k=0;k<3;++k){double sum=0;for(int s=0;s<4;++s)sum+=sample_linear_[(p*4+s)*4+k];
                    const double exposed=std::max(0.0,sum*.25*lighting_.exposure),mapped=exposed/(1.0+exposed);
                    const double encoded=surface_linear_to_srgb(mapped);
                    resolved_[p*4+k]=std::uint8_t(std::clamp(std::floor(encoded*255.0+0.5),0.0,255.0));}
                resolved_[p*4+3]=255;
            }else for(int k=0;k<4;++k){unsigned sum=0;for(int s=0;s<4;++s)sum+=sample_color_[(p*4+s)*4+k];resolved_[p*4+k]=std::uint8_t(sum/4);}
            depth_[p]=*std::min_element(sample_depth_.begin()+p*4,sample_depth_.begin()+p*4+4);
        }
    }
    std::size_t index(int x,int y)const {
        return std::size_t(std::clamp(y,0,int(c_.height)-1))*c_.width+std::clamp(x,0,int(c_.width)-1);
    }
    float channel(std::size_t p,int k)const{return float(resolved_[p*4+k])/255.0f;}
    float luma(std::size_t p)const{return (0.299f*channel(p,0)+0.587f*channel(p,1))+0.114f*channel(p,2);}
    void aa(std::size_t tile) {
        const auto r=rect(tile);
        // Reads include adjacent tile halos. The MSAA wave has joined first.
        for(int y=int(r.y0);y<int(r.y1);++y)for(int x=int(r.x0);x<int(r.x1);++x) {
            const auto p=index(x,y),n=index(x,y-1),s=index(x,y+1),w=index(x-1,y),e=index(x+1,y);
            const float lm=luma(p),ln=luma(n),ls=luma(s),lw=luma(w),le=luma(e);
            const float contrast=std::max({lm,ln,ls,lw,le})-std::min({lm,ln,ls,lw,le});
            const float corners=((luma(index(x-1,y-1))+luma(index(x+1,y-1)))+luma(index(x-1,y+1)))+luma(index(x+1,y+1));
            const float avg=(2.0f*(((ln+ls)+lw)+le)+corners)/12.0f;
            const float blend=std::clamp(std::abs(avg-lm)/std::max(contrast,1e-4f),0.0f,1.0f)*0.75f;
            const bool horizontal=std::abs((ln+ls)-2.0f*lm)>=std::abs((lw+le)-2.0f*lm);
            for(int k=0;k<3;++k){const float v=channel(p,k);
                const float neighbor=0.5f*(channel(horizontal?n:w,k)+channel(horizontal?s:e,k));
                const float out=contrast>=0.08f?((1.0f-blend)*v+blend*neighbor):v;
                final_[p*4+k]=std::uint8_t(std::clamp(out*255.0f,0.0f,255.0f));}
            final_[p*4+3]=resolved_[p*4+3];
        }
    }
    void wave(unsigned kind,std::size_t count,std::size_t offset) {
        Wave receipt;receipt.worker_jobs.resize(workers_);
        std::vector<std::uint64_t> samples(workers_);
        std::atomic<std::size_t> cursor{0};std::exception_ptr error;std::mutex error_mutex;
        for(std::size_t i=0;i<count;++i)states_[offset+i]=State::ready;
        const auto begin=std::chrono::steady_clock::now();
        auto work=[&](unsigned worker) {
            try {
                require_environment();
                // Chunk acquisition amortizes scheduling, each room still runs.
                for(;;){const auto first=cursor.fetch_add(32,std::memory_order_relaxed);if(first>=count)break;
                    for(auto i=first;i<std::min(first+32,count);++i) {
                        states_[offset+i]=State::running;
                        const auto operation_begin=std::chrono::steady_clock::now();
                        switch(static_cast<Kind>(kind)) {
                            case Kind::render:render(i);break;
                            case Kind::raster:samples[worker]+=raster(i);break;
                            case Kind::msaa:msaa(i);break;
                            case Kind::aa:aa(i);break;
                        }
                        operation_work_ms_[kind][worker]+=std::chrono::duration<double,std::milli>(
                            std::chrono::steady_clock::now()-operation_begin).count();
                        states_[offset+i]=State::done;++receipt.worker_jobs[worker];
                    }
                }
            }catch(...){std::lock_guard<std::mutex> lock(error_mutex);if(!error)error=std::current_exception();}
        };
        std::vector<std::thread> pool;
        try {for(unsigned w=1;w<workers_;++w)pool.emplace_back(work,w);}
        catch(...){for(auto& t:pool)t.join();throw;}
        work(0);for(auto& t:pool)t.join();if(error)std::rethrow_exception(error);
        receipt.milliseconds=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
        for(unsigned w=0;w<workers_;++w){receipt.executed+=receipt.worker_jobs[w];receipt.samples+=samples[w];}
        if(receipt.executed!=count)throw std::runtime_error("ROOM_INCOMPLETE_WAVE");
        waves_[kind]=std::move(receipt);
    }
    static void validate_geometry(const std::vector<Triangle>& triangles) {
        for(const auto& t:triangles)for(const auto& v:t.v)
            if(!std::isfinite(v.x)||!std::isfinite(v.y)||!std::isfinite(v.z)||!std::isfinite(v.w)||v.w<1e-7f||
               v.x < -v.w || v.x>v.w || v.y < -v.w || v.y>v.w || v.z < -v.w || v.z>v.w)
                throw std::runtime_error("ROOM_REQUIRES_FINITE_CLIPPED_GEOMETRY");
    }
    static void validate_surface_geometry(const std::vector<SurfaceTriangle>& triangles) {
        for(const auto& t:triangles)for(int k=0;k<3;++k){const auto& v=t.v[k];
            if(!std::isfinite(v.x)||!std::isfinite(v.y)||!std::isfinite(v.z)||!std::isfinite(v.w)||v.w<1e-7f||
               v.x < -v.w || v.x>v.w || v.y < -v.w || v.y>v.w || v.z < -v.w || v.z>v.w)
                throw std::runtime_error("ROOM_REQUIRES_FINITE_CLIPPED_GEOMETRY");
            for(float x:t.world[k])if(!std::isfinite(x)||std::abs(x)>1e12f)throw std::runtime_error("MODEL_SURFACE_POSITION");
            for(float x:t.normal[k])if(!std::isfinite(x)||std::abs(x)>1e6f)throw std::runtime_error("MODEL_SURFACE_NORMAL");
            for(float x:t.uv[k])if(!std::isfinite(x)||std::abs(x)>1e6f)throw std::runtime_error("MODEL_SURFACE_UV");
        }
    }
public:
    Pipeline(Config c,const std::vector<Triangle>& triangles,unsigned workers,
             Admission admission=Admission::legacy):c_(c),workers_(workers),admission_(admission),
        pixels_(validate(c,triangles.size(),workers,admission)),tiles_x_((c.width+c.tile-1)/c.tile),
        tiles_y_((c.height+c.tile-1)/c.tile),tiles_(tiles_x_*tiles_y_),triangles_(triangles),prepared_(triangles.size()),
        sample_color_(pixels_*16),resolved_(pixels_*4),final_(pixels_*4),sample_depth_(pixels_*4),depth_(pixels_),
        states_(triangles.size()+3*tiles_) {
        require_environment();
        validate_geometry(triangles_);
    }
    Pipeline(Config c,const std::vector<SurfaceTriangle>& scene,unsigned workers,
             const std::vector<SurfaceMaterial>& materials,const std::vector<SurfaceTexture>& textures,
             SurfaceLighting lighting,Admission admission=Admission::model_probe)
        :Pipeline(c,std::vector<Triangle>{},workers,admission) {
        if(admission!=Admission::model_probe||materials.empty())throw std::runtime_error("MODEL_SURFACE_ADMISSION");
        surface_mode_=true;materials_=&materials;textures_=&textures;lighting_=lighting;
        sample_linear_.resize(pixels_*16);update_scene(scene);
    }
    void update_scene(const std::vector<Triangle>& triangles) {
        delivered_=false;
        if(surface_mode_)throw std::runtime_error("MODEL_SURFACE_PROTOCOL");
        if(admission_!=Admission::model_probe)
            throw std::runtime_error("MODEL_TOPOLOGY_CHANGED");
        validate(c_,triangles.size(),workers_,admission_);
        validate_geometry(triangles);
        triangles_=triangles;
        prepared_.resize(triangles_.size());
        states_.resize(triangles_.size()+3*tiles_);
    }
    void update_scene(const std::vector<SurfaceTriangle>& triangles) {
        delivered_=false;
        if(!surface_mode_||admission_!=Admission::model_probe)throw std::runtime_error("MODEL_SURFACE_PROTOCOL");
        validate(c_,triangles.size(),workers_,admission_);validate_surface_geometry(triangles);
        for(const auto& t:triangles)if(t.material>=materials_->size())throw std::runtime_error("MODEL_SURFACE_MATERIAL");
        surface_triangles_=triangles;prepared_.resize(surface_triangles_.size());
        states_.resize(surface_triangles_.size()+3*tiles_);
    }
    std::size_t triangle_count()const{return surface_mode_?surface_triangles_.size():triangles_.size();}
    void execute() {
        delivered_=false;require_environment();std::fill(states_.begin(),states_.end(),State::waiting);operation_work_ms_={};
        const auto n=triangle_count();
        wave(0,n,0);wave(1,tiles_,n);wave(2,tiles_,n+tiles_);wave(3,tiles_,n+2*tiles_);
        for(auto s:states_)if(s!=State::done)throw std::runtime_error("ROOM_HANDOFF_INCOMPLETE");
        delivered_=true;
    }
    const auto& rgba()const {if(!delivered_)throw std::runtime_error("ROOM_NO_HANDOFF");return final_;}
    const auto& resolved()const {if(!delivered_)throw std::runtime_error("ROOM_NO_HANDOFF");return resolved_;}
    const auto& depth()const {if(!delivered_)throw std::runtime_error("ROOM_NO_HANDOFF");return depth_;}
    const auto& waves()const{return waves_;}
    std::array<double,4> stage_work_ms()const {
        std::array<double,4> total{};
        for(unsigned k=0;k<4;++k)for(unsigned w=0;w<workers_;++w)total[k]+=operation_work_ms_[k][w];
        return total;
    }
    std::size_t room_count()const{return states_.size();}
    std::size_t tiles()const{return tiles_;}
    // (slot_x, slot_y, operation, frame). Render slots index primitives;
    // the other three operation planes index disjoint rectangular tiles.
    std::array<std::size_t,4> address(std::size_t room)const {
        if(room>=states_.size())throw std::runtime_error("ROOM_ADDRESS");
        const auto n=triangle_count();
        if(room<n)return {room,0,0,c_.frame};
        const auto local=(room-n)%tiles_,kind=1+(room-n)/tiles_;
        return {local%tiles_x_,local/tiles_x_,kind,c_.frame};
    }
};
} // namespace are::rooms
