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
    std::vector<Node> nodes;
    std::vector<std::uint32_t> joints,influences;
    std::vector<float> weights;
    std::vector<Mat> inverse_bind;
    std::vector<Channel> channels;
    std::vector<V3> posed;
    unsigned influence_count=0,mesh_node=0;
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
        posed.resize(positions.size());
        for(std::size_t i=0;i<positions.size();++i){V3 p{positions[i][0],positions[i][1],positions[i][2]};
            if(skin.empty())posed[i]=point(world[mesh_node],p);
            else{V3 o{};double total=0;for(unsigned k=0;k<influence_count;++k){const auto a=i*influence_count+k;const double w=weights[a];if(w==0)continue;
                    const auto v=point(skin[influences[a]],p);for(int axis=0;axis<3;++axis)o[axis]+=w*v[axis];total+=w;}
                for(auto&v:o){v/=total;}
                posed[i]=o;}
            for(double v:posed[i])need(std::isfinite(v)&&std::abs(v)<1e15,"MODEL_POSE_NONFINITE");
        }
    }
    void normalize(){raw_pose(0,false);Bounds b;for(const auto&p:posed)b.add(p);center=b.center();need(b.span()>1e-12,"MODEL_EMPTY_BOUNDS");scale=2.0/b.span();}
    void pose(double time){raw_pose(time);constexpr double yaw=.45,pitch=-.18;const double cy=std::cos(yaw),sy=std::sin(yaw),cx=std::cos(pitch),sx=std::sin(pitch);
        for(auto& p:posed){for(int k=0;k<3;++k)p[k]=(p[k]-center[k])*scale;p=point(placement,p);
            const double x=cy*p[0]+sy*p[2],z=-sy*p[0]+cy*p[2],y=cx*p[1]-sx*z;p={x,y,sx*p[1]+cx*z};}
    }
};
struct Scene {
    are::rooms::Config config{};std::vector<double> times;std::vector<Model> models;
    std::vector<are::rooms::Triangle> triangles;V3 center{};double scale=1;std::size_t vertices=0,source_triangles=0;
    bool perspective=false;projection::Camera camera{};
    explicit Scene(const char* path,unsigned workers){Reader r(path);char magic[8];r.bytes(magic,8);
        const bool v1=std::memcmp(magic,"AREMDL01",8)==0;perspective=std::memcmp(magic,"AREMDL02",8)==0;
        need(v1||perspective,"MODEL_PROTOCOL");
        const auto nm=r.count(1,12),nf=r.count(1,60);config={r.count(2,512),r.count(2,512),r.count(16,64),0};
        for(unsigned f=0;f<nf;++f){const auto t=r.number();need(t>=0&&t<=3600,"MODEL_FRAME_TIME");times.push_back(t);}
        if(perspective){camera.eye=r.numbers<3>();camera.target=r.numbers<3>();camera.up=r.numbers<3>();
            camera.fov_y_degrees=r.number();camera.near_plane=r.number();camera.far_plane=r.number();
            projection::validate_camera(camera,double(config.width)/config.height);}
        std::size_t total_faces=0,total_keys=0;
        for(unsigned mi=0;mi<nm;++mi){Model m;const auto nv=r.count(1,max_vertices),nt=r.count(1,max_triangles),nn=r.count(1,max_nodes),nj=r.count(0,max_nodes);
            m.influence_count=r.count(0,12);m.mesh_node=r.count(0,nn-1);const auto nc=r.count(0,3*nn);
            need((nj==0&&m.influence_count==0)||(nj>0&&(m.influence_count==4||m.influence_count==8||m.influence_count==12)),"MODEL_INFLUENCES");
            vertices+=nv;total_faces+=nt;need(vertices<=max_vertices&&total_faces<=max_triangles,"MODEL_SCENE_BUDGET");
            are::rooms::validate(config,total_faces,workers,are::rooms::Admission::model_probe);
            m.placement=r.matrix();r.bytes(m.color.data(),4);m.nodes.resize(nn);
            for(auto& n:m.nodes){n.parent=r.scalar<std::int32_t>();need(n.parent>=-1&&n.parent<std::int32_t(nn),"MODEL_PARENT");n.matrix=r.count(0,1)!=0;
                if(n.matrix)n.local=r.matrix();else{n.t=r.numbers<3>();n.q=unit(r.numbers<4>());n.s=r.numbers<3>();}}
            m.joints=r.array<std::uint32_t>(nj);std::vector<bool> used(nn);
            for(auto j:m.joints){need(j<nn&&!used[j],"MODEL_JOINT");used[j]=true;m.inverse_bind.push_back(r.matrix());}
            m.positions=r.array<std::array<float,3>>(nv);for(const auto&p:m.positions)for(float x:p)need(std::isfinite(x)&&std::abs(x)<1e12,"MODEL_POSITION");
            m.faces=r.array<std::array<std::uint32_t,3>>(nt);for(const auto&f:m.faces)for(auto i:f)need(i<nv,"MODEL_INDEX");
            m.influences=r.array<std::uint32_t>(std::size_t(nv)*m.influence_count);m.weights=r.array<float>(m.influences.size());
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
        if(!perspective)triangles.resize(total_faces);else triangles.reserve(total_faces);
    }
    void fit(){Bounds b;for(double t:times)for(auto& m:models){m.pose(t);for(const auto&p:m.posed)b.add(p);}center=b.center();need(b.span()>1e-12,"MODEL_EMPTY_BOUNDS");scale=1.8/b.span();}
    void frame(double time,FrameProfile* profile=nullptr){std::size_t cursor=0;
        if(perspective)triangles.clear();
        for(auto& m:models){const auto begin=std::chrono::steady_clock::now();m.pose(time);
            if(profile){const auto ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
                (m.channels.empty()?profile->static_pose_ms:profile->animated_pose_ms)+=ms;}}
        const auto prepare=std::chrono::steady_clock::now();
        const auto projector=perspective?projection::make_projector(camera,double(config.width)/config.height):projection::Projector{};
        std::uint64_t clipped_count=0,culled_count=0;
        for(auto& m:models){
        for(const auto& f:m.faces){V3 p[3];std::array<are::rooms::Vertex,3> input{};
            for(int k=0;k<3;++k){p[k]=m.posed[f[k]];
                if(perspective){V3 q{(p[k][0]-center[0])*scale,(p[k][1]-center[1])*scale,(p[k][2]-center[2])*scale};
                    input[k]=projection::project(q,projector);}
                else input[k]={float((p[k][0]-center[0])*scale),float((p[k][1]-center[1])*scale),float(-(p[k][2]-center[2])*scale),1};}
            V3 u{},v{};for(int k=0;k<3;++k){u[k]=p[1][k]-p[0][k];v[k]=p[2][k]-p[0][k];}
            const V3 n{u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]};
            const auto len=std::sqrt(n[0]*n[0]+n[1]*n[1]+n[2]*n[2]);const auto light=len>0?.25+.75*std::abs((.36*n[0]+.48*n[1]+.8*n[2])/len):.25;
            std::array<std::uint8_t,4> rgba{};for(int k=0;k<3;++k)rgba[k]=std::uint8_t(std::clamp(m.color[k]*light,0.0,255.0));rgba[3]=255;
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
            if(perspective){const auto emitted=projection::clip_triangle(input,append);
                if(emitted==0)++culled_count;else if(emitted!=1)++clipped_count;}
            else append(input);
        }}
        if(!perspective)need(cursor==source_triangles,"MODEL_FRAME_TOPOLOGY");
        if(profile){profile->clipped_input_triangles=clipped_count;profile->culled_input_triangles=culled_count;
            profile->projected_triangles=triangles.size();}
        if(profile)profile->triangle_prepare_ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-prepare).count();
    }
};
} // namespace are::models
