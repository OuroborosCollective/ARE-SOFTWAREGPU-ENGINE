// OuroborosCollective. Repository license applies.
// Bounded, typed model probe. GLB decoding is offline; poses and frames are C++.
#pragma once
#include "workrooms_wire.hpp"
#include "model_projection.hpp"
#include <fstream>
#include <numeric>
#include <chrono>
namespace are::models {
using V3=std::array<double,3>;using V4=std::array<double,4>;using Mat=std::array<double,16>;
constexpr std::size_t max_vertices=6100000,max_triangles=8000000,max_nodes=256;
inline void need(bool value,const char* code){if(!value)throw std::runtime_error(code);}
inline Mat identity(){return {1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};}
inline Mat multiply(const Mat& a,const Mat& b){Mat c{};for(int i=0;i<4;++i)for(int j=0;j<4;++j)
    {for(int k=0;k<4;++k)c[i*4+j]+=a[i*4+k]*b[k*4+j];}
    return c;}
inline V3 point(const Mat& m,const V3& p){V3 o{};for(int i=0;i<3;++i)o[i]=((m[i*4]*p[0]+m[i*4+1]*p[1])+m[i*4+2]*p[2])+m[i*4+3];return o;}
inline V3 normal_vector(const Mat& m,const V3& n){
    const double a=m[0],b=m[1],c=m[2],d=m[4],e=m[5],f=m[6],g=m[8],h=m[9],i=m[10];
    const double c00=e*i-f*h,c01=f*g-d*i,c02=d*h-e*g;
    const double c10=c*h-b*i,c11=a*i-c*g,c12=b*g-a*h;
    const double c20=b*f-c*e,c21=c*d-a*f,c22=a*e-b*d;
    const double det=a*c00+b*c01+c*c02;
    need(std::isfinite(det)&&std::abs(det)>1e-18,"MODEL_NORMAL_MATRIX");
    return {(c00*n[0]+c01*n[1]+c02*n[2])/det,
            (c10*n[0]+c11*n[1]+c12*n[2])/det,
            (c20*n[0]+c21*n[1]+c22*n[2])/det};
}
inline V4 unit(V4 q){double n=0;for(double x:q)n+=x*x;need(std::isfinite(n)&&n>1e-20,"MODEL_QUATERNION");n=std::sqrt(n);for(double& x:q)x/=n;return q;}
inline V4 slerp(V4 a,V4 b,double u){a=unit(a);b=unit(b);double d=0;for(int k=0;k<4;++k)d+=a[k]*b[k];
    if(d<0){for(double& x:b)x=-x;d=-d;}d=std::clamp(d,-1.0,1.0);V4 q{};
    if(d>0.9995){for(int k=0;k<4;++k)q[k]=a[k]+u*(b[k]-a[k]);return unit(q);}
    const double angle=std::acos(d),den=std::sin(angle),wa=std::sin((1-u)*angle)/den,wb=std::sin(u*angle)/den;
    for(int k=0;k<4;++k){q[k]=wa*a[k]+wb*b[k];}
    return unit(q);
}
inline Mat trs(const V3& t,V4 q,const V3& s){q=unit(q);const auto x=q[0],y=q[1],z=q[2],w=q[3];
    Mat m={1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),t[0],
           2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),t[1],
           2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),t[2],0,0,0,1};
    for(int i=0;i<3;++i)for(int j=0;j<3;++j){m[i*4+j]*=s[j];}
    return m;
}
struct Reader {
    std::ifstream in;std::uint64_t remaining;
    explicit Reader(const char* path):in(path,std::ios::binary|std::ios::ate){need(bool(in),"MODEL_INPUT");
        const auto n=in.tellg();need(n>=32&&n<=536870912,"MODEL_INPUT_BYTES");remaining=std::uint64_t(n);in.seekg(0);
        const unsigned endian=1;need(*reinterpret_cast<const char*>(&endian)==1,"MODEL_ENDIAN");}
    void bytes(void* p,std::size_t n){need(n<=remaining,"MODEL_TRUNCATED");need(bool(in.read(static_cast<char*>(p),n)),"MODEL_TRUNCATED");remaining-=n;}
    template<class T>T scalar(){T v{};bytes(&v,sizeof(v));return v;}
    std::uint32_t count(std::uint32_t lo,std::uint32_t hi){auto n=scalar<std::uint32_t>();need(n>=lo&&n<=hi,"MODEL_COUNT");return n;}
    template<class T>std::vector<T> array(std::size_t n){need(n<=remaining/sizeof(T),"MODEL_TRUNCATED");std::vector<T> a(n);bytes(a.data(),a.size()*sizeof(T));return a;}
    double number(){auto v=scalar<double>();need(std::isfinite(v)&&std::abs(v)<=1e12,"MODEL_NUMBER");return v;}
    template<std::size_t N>std::array<double,N> numbers(){std::array<double,N>a{};for(auto&x:a)x=number();return a;}
    Mat matrix(){auto m=numbers<16>();need(m[12]==0&&m[13]==0&&m[14]==0&&m[15]==1,"MODEL_AFFINE_MATRIX");return m;}
};
struct Node {std::int32_t parent=-1;bool matrix=false;Mat local=identity();V3 t{0,0,0},s{1,1,1};V4 q{0,0,0,1};};
struct Channel {std::uint32_t node,path,interpolation;std::vector<double> times,values;};
struct Bounds {V3 lo{1e300,1e300,1e300},hi{-1e300,-1e300,-1e300};
    void add(const V3& p){for(int k=0;k<3;++k){need(std::isfinite(p[k])&&std::abs(p[k])<1e15,"MODEL_POSE_NONFINITE");lo[k]=std::min(lo[k],p[k]);hi[k]=std::max(hi[k],p[k]);}}
    V3 center()const{return {(lo[0]+hi[0])*.5,(lo[1]+hi[1])*.5,(lo[2]+hi[2])*.5};}
    double span()const{return std::max({hi[0]-lo[0],hi[1]-lo[1],hi[2]-lo[2]});}
};
struct FrameProfile {double animated_pose_ms=0,static_pose_ms=0,triangle_prepare_ms=0;
    std::uint64_t clipped_input_triangles=0,culled_input_triangles=0;std::size_t projected_triangles=0;};
struct Model {
    std::vector<std::array<float,3>> positions;
    std::vector<std::array<std::uint32_t,3>> faces;
    std::vector<std::array<float,3>> normals;
    std::vector<std::array<float,2>> uvs;
    std::vector<Node> nodes;
    std::vector<std::uint32_t> joints,influences;
    std::vector<float> weights;
    std::vector<Mat> inverse_bind;
    std::vector<Channel> channels;
    std::vector<V3> posed,posed_normals;
    unsigned influence_count=0,mesh_node=0,material_index=0;
    Mat placement=identity();std::array<std::uint8_t,4> color{};V3 center{};double scale=1;
    void raw_pose(double time,bool animated=true){
        auto pose=nodes;
        if(animated)for(const auto& c:channels){const auto dim=c.path==1?4u:3u;
            const auto upper=std::upper_bound(c.times.begin(),c.times.end(),time);
            std::size_t a=upper==c.times.begin()?0:std::size_t(upper-c.times.begin()-1),b=std::min(a+1,c.times.size()-1);
            double u=b==a?0:std::clamp((time-c.times[a])/(c.times[b]-c.times[a]),0.0,1.0);if(c.interpolation==0)u=0;
            auto& n=pose[c.node];
            if(c.path==1){V4 qa{},qb{};for(unsigned k=0;k<4;++k){qa[k]=c.values[a*4+k];qb[k]=c.values[b*4+k];}n.q=slerp(qa,qb,u);}
            else for(unsigned k=0;k<dim;++k)(c.path==0?n.t:n.s)[k]=c.values[a*dim+k]+u*(c.values[b*dim+k]-c.values[a*dim+k]);
        }
        std::vector<Mat> world(nodes.size());std::vector<unsigned char> marks(nodes.size());
        auto visit=[&](auto&& self,std::size_t i)->void{if(marks[i]==2)return;need(marks[i]==0,"MODEL_NODE_CYCLE");marks[i]=1;
            const auto& n=pose[i];const auto local=n.matrix?n.local:trs(n.t,n.q,n.s);
            if(n.parent>=0){self(self,std::size_t(n.parent));world[i]=multiply(world[std::size_t(n.parent)],local);}else world[i]=local;
            marks[i]=2;};
        for(std::size_t i=0;i<nodes.size();++i)visit(visit,i);
        std::vector<Mat> skin(joints.size());for(std::size_t j=0;j<joints.size();++j)skin[j]=multiply(world[joints[j]],inverse_bind[j]);
        posed.resize(positions.size());if(!normals.empty())posed_normals.resize(positions.size());
        for(std::size_t i=0;i<positions.size();++i){V3 p{positions[i][0],positions[i][1],positions[i][2]};
            if(skin.empty()){posed[i]=point(world[mesh_node],p);
                if(!normals.empty())posed_normals[i]=normal_vector(world[mesh_node],V3{normals[i][0],normals[i][1],normals[i][2]});}
            else{Mat blended{};double total=0;
                for(unsigned k=0;k<influence_count;++k){const auto a=i*influence_count+k;const double w=weights[a];if(w==0)continue;
                    const auto& joint=skin[influences[a]];for(int cell=0;cell<16;++cell)blended[cell]+=w*joint[cell];total+=w;}
                need(total>0&&std::isfinite(total),"MODEL_SKIN_WEIGHT_SUM");for(auto& cell:blended)cell/=total;
                posed[i]=point(blended,p);
                if(!normals.empty())posed_normals[i]=normal_vector(blended,V3{normals[i][0],normals[i][1],normals[i][2]});}
            for(double v:posed[i])need(std::isfinite(v)&&std::abs(v)<1e15,"MODEL_POSE_NONFINITE");
            if(!normals.empty())posed_normals[i]=projection::normalize(posed_normals[i],"MODEL_NORMAL_DEGENERATE");
        }
    }
    void normalize(){raw_pose(0,false);Bounds b;for(const auto&p:posed)b.add(p);center=b.center();need(b.span()>1e-12,"MODEL_EMPTY_BOUNDS");scale=2.0/b.span();}
    void pose(double time){raw_pose(time);constexpr double yaw=.45,pitch=-.18;const double cy=std::cos(yaw),sy=std::sin(yaw),cx=std::cos(pitch),sx=std::sin(pitch);
        for(std::size_t i=0;i<posed.size();++i){auto& p=posed[i];for(int k=0;k<3;++k)p[k]=(p[k]-center[k])*scale;p=point(placement,p);
            const double x=cy*p[0]+sy*p[2],z=-sy*p[0]+cy*p[2],y=cx*p[1]-sx*z;p={x,y,sx*p[1]+cx*z};
            if(!posed_normals.empty()){auto n=normal_vector(placement,posed_normals[i]);
                const double nx=cy*n[0]+sy*n[2],nz=-sy*n[0]+cy*n[2],ny=cx*n[1]-sx*nz;
                posed_normals[i]=projection::normalize(V3{nx,ny,sx*n[1]+cx*nz},"MODEL_NORMAL_DEGENERATE");}}
    }
};
struct Scene {
    are::rooms::Config config{};std::vector<double> times;std::vector<Model> models;
    std::vector<are::rooms::Triangle> triangles;std::vector<are::rooms::SurfaceTriangle> surface_triangles;
    std::vector<are::rooms::SurfaceMaterial> materials;std::vector<are::rooms::SurfaceTexture> textures;
    V3 center{};double scale=1;std::size_t vertices=0,source_triangles=0;
    bool perspective=false,pbr=false;projection::Camera camera{};are::rooms::SurfaceLighting lighting{};
    explicit Scene(const char* path,unsigned workers){Reader r(path);char magic[8];r.bytes(magic,8);
        const bool v1=std::memcmp(magic,"AREMDL01",8)==0;perspective=std::memcmp(magic,"AREMDL02",8)==0;
        pbr=std::memcmp(magic,"AREMDL03",8)==0;if(pbr)perspective=true;
        need(v1||perspective,"MODEL_PROTOCOL");
        const auto nm=r.count(1,12),nf=r.count(1,60);config={r.count(2,512),r.count(2,512),r.count(16,64),0};
        for(unsigned f=0;f<nf;++f){const auto t=r.number();need(t>=0&&t<=3600,"MODEL_FRAME_TIME");times.push_back(t);}
        if(perspective){camera.eye=r.numbers<3>();camera.target=r.numbers<3>();camera.up=r.numbers<3>();
            camera.fov_y_degrees=r.number();camera.near_plane=r.number();camera.far_plane=r.number();
            projection::validate_camera(camera,double(config.width)/config.height);}
        if(pbr){
            const auto texture_count=r.count(0,64),material_count=r.count(1,12);need(material_count==nm,"MODEL_MATERIAL_COUNT");
            struct TextureMeta{std::uint32_t w,h,ws,wt,min,mag,srgb;};std::vector<TextureMeta> metas;metas.reserve(texture_count);
            std::uint64_t base_bytes=0,mip_bytes=0;
            for(unsigned i=0;i<texture_count;++i){TextureMeta m{r.count(1,4096),r.count(1,4096),r.scalar<std::uint32_t>(),
                    r.scalar<std::uint32_t>(),r.scalar<std::uint32_t>(),r.scalar<std::uint32_t>(),r.count(0,1)};
                need((m.ws==10497||m.ws==33071||m.ws==33648)&&(m.wt==10497||m.wt==33071||m.wt==33648),"MODEL_TEXTURE_WRAP");
                need((m.mag==9728||m.mag==9729)&&(m.min==9728||m.min==9729||(m.min>=9984&&m.min<=9987)),"MODEL_TEXTURE_FILTER");
                base_bytes+=std::uint64_t(m.w)*m.h*4;for(std::uint32_t w=m.w,h=m.h;;){mip_bytes+=std::uint64_t(w)*h*4;if(w==1&&h==1)break;w=std::max(1u,w/2);h=std::max(1u,h/2);}
                need(base_bytes<=512ull*1024*1024&&mip_bytes<=768ull*1024*1024,"MODEL_TEXTURE_SCENE_BUDGET");metas.push_back(m);}
            for(unsigned i=0;i<material_count;++i){are::rooms::SurfaceMaterial m;const auto f=r.array<float>(11);const auto ids=r.array<std::int32_t>(5);
                std::copy_n(f.begin(),4,m.base_color.begin());std::copy_n(f.begin()+4,3,m.emissive.begin());
                m.metallic=f[7];m.roughness=f[8];m.normal_scale=f[9];m.occlusion_strength=f[10];
                m.base_texture=ids[0];m.mr_texture=ids[1];m.normal_texture=ids[2];m.emissive_texture=ids[3];m.occlusion_texture=ids[4];
                m.double_sided=r.count(0,1)!=0;
                for(float x:f)need(std::isfinite(x)&&std::abs(x)<=1e4f,"MODEL_MATERIAL_NUMBER");
                for(float x:m.base_color)need(x>=0&&x<=1,"MODEL_BASE_COLOR");
                need(m.metallic>=0&&m.metallic<=1&&m.roughness>=0&&m.roughness<=1&&std::abs(m.normal_scale)<=100&&
                     m.occlusion_strength>=0&&m.occlusion_strength<=1&&m.double_sided,"MODEL_MATERIAL_RANGE");
                for(auto id:ids)need(id>=-1&&(id<0||std::uint32_t(id)<texture_count),"MODEL_MATERIAL_TEXTURE_INDEX");
                materials.push_back(m);}
            std::uint64_t built_bytes=0;
            for(const auto& meta:metas){are::rooms::SurfaceTexture t;t.wrap_s=meta.ws;t.wrap_t=meta.wt;t.min_filter=meta.min;t.mag_filter=meta.mag;t.srgb=meta.srgb!=0;
                are::rooms::SurfaceMip base;base.width=meta.w;base.height=meta.h;base.rgba=r.array<std::uint8_t>(std::size_t(meta.w)*meta.h*4);
                t.mips.push_back(std::move(base));t.build_mips();built_bytes+=t.mip_bytes();need(built_bytes<=768ull*1024*1024,"MODEL_TEXTURE_SCENE_BUDGET");textures.push_back(std::move(t));}
            lighting.camera={float(camera.eye[0]),float(camera.eye[1]),float(camera.eye[2])};
        }
        std::size_t total_faces=0,total_keys=0;
        for(unsigned mi=0;mi<nm;++mi){Model m;const auto nv=r.count(1,max_vertices),nt=r.count(1,max_triangles),nn=r.count(1,max_nodes),nj=r.count(0,max_nodes);
            m.influence_count=r.count(0,12);m.mesh_node=r.count(0,nn-1);const auto nc=r.count(0,3*nn);
            if(pbr){m.material_index=r.count(0,unsigned(materials.size()-1));need(nt<=1000000,"MODEL_SURFACE_TRIANGLE_BUDGET");}
            need((nj==0&&m.influence_count==0)||(nj>0&&(m.influence_count==4||m.influence_count==8||m.influence_count==12)),"MODEL_INFLUENCES");
            vertices+=nv;total_faces+=nt;need(vertices<=max_vertices&&total_faces<=max_triangles&&(!pbr||total_faces<=1000000),"MODEL_SCENE_BUDGET");
            are::rooms::validate(config,total_faces,workers,are::rooms::Admission::model_probe);
            m.placement=r.matrix();r.bytes(m.color.data(),4);m.nodes.resize(nn);
            for(auto& n:m.nodes){n.parent=r.scalar<std::int32_t>();need(n.parent>=-1&&n.parent<std::int32_t(nn),"MODEL_PARENT");n.matrix=r.count(0,1)!=0;
                if(n.matrix)n.local=r.matrix();else{n.t=r.numbers<3>();n.q=unit(r.numbers<4>());n.s=r.numbers<3>();}}
            m.joints=r.array<std::uint32_t>(nj);std::vector<bool> used(nn);
            for(auto j:m.joints){need(j<nn&&!used[j],"MODEL_JOINT");used[j]=true;m.inverse_bind.push_back(r.matrix());}
            m.positions=r.array<std::array<float,3>>(nv);for(const auto&p:m.positions)for(float x:p)need(std::isfinite(x)&&std::abs(x)<1e12,"MODEL_POSITION");
            m.faces=r.array<std::array<std::uint32_t,3>>(nt);for(const auto&f:m.faces)for(auto i:f)need(i<nv,"MODEL_INDEX");
            m.influences=r.array<std::uint32_t>(std::size_t(nv)*m.influence_count);m.weights=r.array<float>(m.influences.size());
            if(pbr){m.normals=r.array<std::array<float,3>>(nv);m.uvs=r.array<std::array<float,2>>(nv);
                for(const auto& n:m.normals){double n2=0;for(float x:n){need(std::isfinite(x)&&std::abs(x)<=1.001,"MODEL_NORMAL");n2+=double(x)*x;}
                    need(n2>1e-20,"MODEL_NORMAL_DEGENERATE");}
                for(const auto& uv:m.uvs)for(float x:uv)need(std::isfinite(x)&&std::abs(x)<=1e6f,"MODEL_UV");}
            for(std::size_t i=0;i<nv&&nj;++i){double sum=0;for(unsigned k=0;k<m.influence_count;++k){const auto a=i*m.influence_count+k;
                need(m.influences[a]<nj&&std::isfinite(m.weights[a])&&m.weights[a]>=0&&m.weights[a]<=1,"MODEL_WEIGHT");sum+=m.weights[a];}
                need(std::abs(sum-1)<.001,"MODEL_WEIGHT_SUM");}
            std::vector<bool> targets(std::size_t(nn)*3);
            for(unsigned ci=0;ci<nc;++ci){Channel c;c.node=r.count(0,nn-1);c.path=r.count(0,2);c.interpolation=r.count(0,1);const auto nk=r.count(1,10000);
                need(!targets[c.node*3+c.path]&&!m.nodes[c.node].matrix,"MODEL_ANIMATION_TARGET");targets[c.node*3+c.path]=true;
                total_keys+=nk;need(total_keys<=2000000,"MODEL_KEYS_BUDGET");c.times=r.array<double>(nk);const unsigned dim=c.path==1?4:3;c.values=r.array<double>(std::size_t(nk)*dim);
                for(std::size_t k=0;k<nk;++k){need(std::isfinite(c.times[k])&&c.times[k]>=0&&c.times[k]<=3600&&(k==0||c.times[k]>c.times[k-1]),"MODEL_KEY_TIME");
                    for(unsigned j=0;j<dim;++j)need(std::isfinite(c.values[k*dim+j])&&std::abs(c.values[k*dim+j])<1e12,"MODEL_KEY_VALUE");
                    if(c.path==1)unit({c.values[k*4],c.values[k*4+1],c.values[k*4+2],c.values[k*4+3]});}
                m.channels.push_back(std::move(c));}
            m.normalize();models.push_back(std::move(m));
        }
        need(r.remaining==0,"MODEL_TRAILING");source_triangles=total_faces;
        if(pbr)surface_triangles.reserve(total_faces);
        else if(!perspective)triangles.resize(total_faces);else triangles.reserve(total_faces);
    }
    void fit(){Bounds b;for(double t:times)for(auto& m:models){m.pose(t);for(const auto&p:m.posed)b.add(p);}center=b.center();need(b.span()>1e-12,"MODEL_EMPTY_BOUNDS");scale=1.8/b.span();}
    void frame(double time,FrameProfile* profile=nullptr){std::size_t cursor=0;
        if(perspective)triangles.clear();
        if(pbr)surface_triangles.clear();
        for(auto& m:models){const auto begin=std::chrono::steady_clock::now();m.pose(time);
            if(profile){const auto ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
                (m.channels.empty()?profile->static_pose_ms:profile->animated_pose_ms)+=ms;}}
        const auto prepare=std::chrono::steady_clock::now();
        const auto projector=perspective?projection::make_projector(camera,double(config.width)/config.height):projection::Projector{};
        std::uint64_t clipped_count=0,culled_count=0;
        for(auto& m:models){
        for(const auto& f:m.faces){V3 p[3];std::array<are::rooms::Vertex,3> input{};std::array<are::rooms::SurfaceVertex,3> surface_input{};
            for(int k=0;k<3;++k){p[k]=m.posed[f[k]];
                if(perspective){V3 q{(p[k][0]-center[0])*scale,(p[k][1]-center[1])*scale,(p[k][2]-center[2])*scale};
                    input[k]=projection::project(q,projector);
                    if(pbr){surface_input[k].clip=input[k];
                        for(int a=0;a<3;++a){surface_input[k].world[a]=float(q[a]);surface_input[k].normal[a]=float(m.posed_normals[f[k]][a]);}
                        surface_input[k].uv=m.uvs[f[k]];}}
                else input[k]={float((p[k][0]-center[0])*scale),float((p[k][1]-center[1])*scale),float(-(p[k][2]-center[2])*scale),1};}
            V3 u{},v{};for(int k=0;k<3;++k){u[k]=p[1][k]-p[0][k];v[k]=p[2][k]-p[0][k];}
            const V3 n{u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]};
            const auto len=std::sqrt(n[0]*n[0]+n[1]*n[1]+n[2]*n[2]);const auto light=len>0?.25+.75*std::abs((.36*n[0]+.48*n[1]+.8*n[2])/len):.25;
            std::array<std::uint8_t,4> rgba{};for(int k=0;k<3;++k)rgba[k]=std::uint8_t(std::clamp(m.color[k]*light,0.0,255.0));rgba[3]=255;
            auto append_surface=[&](std::array<are::rooms::SurfaceVertex,3> vertices){
                auto screen=[&](const are::rooms::SurfaceVertex& a){const double inv=1.0/double(a.clip.w);
                    return are::rooms::Vertex{float((double(a.clip.x)*inv+1)*.5*config.width),
                        float((1-double(a.clip.y)*inv)*.5*config.height),float(double(a.clip.z)*inv),1};};
                const auto a=screen(vertices[0]),b=screen(vertices[1]),c=screen(vertices[2]);
                if(are::rooms::edge(a,b,c.x,c.y)<0)std::swap(vertices[1],vertices[2]);
                if(surface_triangles.size()>=1000000)throw std::runtime_error("MODEL_SURFACE_TRIANGLE_BUDGET");
                are::rooms::SurfaceTriangle tri;tri.material=m.material_index;
                for(int k=0;k<3;++k){tri.v[k]=vertices[k].clip;tri.world[k]=vertices[k].world;
                    tri.normal[k]=vertices[k].normal;tri.uv[k]=vertices[k].uv;}
                surface_triangles.push_back(std::move(tri));
            };
            auto append=[&](const std::array<are::rooms::Vertex,3>& vertices){
                are::rooms::Triangle tri;tri.v=vertices;tri.rgba=rgba;
                // Preserve the renderer's positive-area convention and stable fan order.
                auto screen=[&](are::rooms::Vertex a){const double inv=1.0/double(a.w);
                    return are::rooms::Vertex{float((double(a.x)*inv+1)*.5*config.width),
                        float((1-double(a.y)*inv)*.5*config.height),float(double(a.z)*inv),1};};
                const auto a=screen(tri.v[0]),b=screen(tri.v[1]),c=screen(tri.v[2]);
                if(are::rooms::edge(a,b,c.x,c.y)<0)std::swap(tri.v[1],tri.v[2]);
                if(perspective){if(triangles.size()>=max_triangles)throw std::runtime_error("MODEL_RENDER_BUDGET");
                    triangles.push_back(std::move(tri));}
                else triangles[cursor++]=std::move(tri);
            };
            bool input_clipped=false;
            if(pbr){for(const auto& vertex:surface_input)for(unsigned plane=0;plane<6;++plane)
                    input_clipped=input_clipped||projection::distance(vertex.clip,plane)<0.0;
                const auto emitted=projection::clip_surface_triangle(surface_input,append_surface);
                if(emitted==0)++culled_count;else if(input_clipped)++clipped_count;}
            else if(perspective){for(const auto& vertex:input)for(unsigned plane=0;plane<6;++plane)
                    input_clipped=input_clipped||projection::distance(vertex,plane)<0.0;
                const auto emitted=projection::clip_triangle(input,append);
                if(emitted==0)++culled_count;else if(input_clipped)++clipped_count;}
            else append(input);
        }}
        if(!perspective)need(cursor==source_triangles,"MODEL_FRAME_TOPOLOGY");
        if(profile){profile->clipped_input_triangles=clipped_count;profile->culled_input_triangles=culled_count;
            profile->projected_triangles=pbr?surface_triangles.size():triangles.size();}
        if(profile)profile->triangle_prepare_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-prepare).count();
    }
};
} // namespace are::models
