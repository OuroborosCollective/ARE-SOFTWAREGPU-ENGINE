// RED: genuine C++17 renderer, independent arrival oracle and timing A/B.
// No fake frame buffers or stub timing: draw() always rasterizes two triangles.
#include "core.hpp"
#include "single_origin_impact_wave.hpp"
#include "single_origin_time_window.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <fstream>
#include <set>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
namespace wave=are::raster::single_origin;
template<typename F> void rejects(F f,const char* why) {
    bool ok=false;
    try {f();}catch(const std::invalid_argument& e){ok=std::string(e.what())==why;}
    assert(ok);
}
static std::array<double,46> geometry(int n) {
    std::array<double,46> a{};
    for(int t=0;t<2;++t) {
        double* p=a.data()+23*t;
        const std::array<double,6> xy=t==0
          ?std::array<double,6>{0.,0.,0.,double(n),double(n),0.}
          :std::array<double,6>{double(n),double(n),double(n),0.,0.,double(n)};
        for(int v=0;v<3;++v) {
            p[3*v]=xy[2*v];p[3*v+1]=xy[2*v+1];p[3*v+2]=0.5;
            p[9+v]=1.;p[13+3*v]=.5;p[14+3*v]=.4;p[15+3*v]=.35;
        }
        p[12]=1./double(n*n);
    }
    return a;
}
struct Frame{
    std::vector<std::uint8_t> rgba;
    std::vector<float> depth;
    std::vector<std::uint32_t> owners;
};
static Frame draw(int n,const std::array<double,46>& geom){
    const auto pixels=std::size_t(n)*n;
    Frame f{{},{},{}};
    f.rgba.assign(4*pixels,0);
    f.depth.assign(pixels,1.f);
    f.owners.assign(pixels,0);
    std::array<std::uint64_t,3> counters{};
    assert(are::raster::draw(geom.data(),geom.size(),2,n,n,
        f.rgba.data(),f.rgba.size(),f.depth.data(),f.depth.size(),
        counters.data(),counters.size())==are::raster::ok && counters[2]>0);
    for(std::size_t i=0;i<pixels;++i)
        if(f.depth[i]<1.f && i%17!=0) f.owners[i]=7;
    return f;
}
static wave::PulseReceipt timed(Frame& f,int n,int sx,int sy,double vx,
           double speed,double radius,double elapsed,double width,bool tint=true) {
    return wave::apply_at_time(f.rgba.data(),f.rgba.size(),f.depth.data(),
        f.depth.size(),f.owners.data(),f.owners.size(),n,n,sx,sy,
        {vx,0.,0.},speed,1.,radius,elapsed,width,7,tint);
}
static std::uint64_t checksum(const std::vector<std::uint8_t>& data){
    std::uint64_t h=14695981039346656037ull;
    for(const auto b:data){h^=b;h*=1099511628211ull;}
    return h;
}
static void check(int n,const std::array<double,46>& geom){
    const auto base=draw(n,geom);
    const int sx=n/2,sy=n/2;
    const double speed=120.,radius=double(n),t=1.+radius/speed;
    assert(wave::arrival_seconds(0,0,3,4,5.)==1.);
    for(const double v:{0.,30.,-20.})
        for(const std::pair<int,int> seed:{std::pair<int,int>{sx,sy},{0,0}})
            for(bool with_doppler:{false,true}){
                auto instant=base,animation=base,replay=base;
                const auto old=wave::apply(instant.rgba.data(),instant.rgba.size(),
                   instant.depth.data(),instant.depth.size(),
                   instant.owners.data(),instant.owners.size(),n,n,
                   seed.first,seed.second,{v,0.,0.},speed,1.,radius,7,with_doppler);
                const auto a=timed(animation,n,seed.first,seed.second,v,
                   speed,radius,t,t+1.,with_doppler);
                const auto b=timed(replay,n,seed.first,seed.second,v,
                   speed,radius,t,t+1.,with_doppler);
                assert(animation.rgba==instant.rgba && replay.rgba==instant.rgba);
                assert(animation.depth==base.depth && replay.depth==base.depth);
                assert(a.area_completions==old.area_completions);
                assert(a.tinted_pixels==old.tinted_pixels);
                assert(a.event_fingerprint==b.event_fingerprint);
                assert(a.spherepop_starts==1 && a.reemissions==0 &&
                       a.queue_pushes==0 && a.refusals==0);
            }
    // At t=0 the fixed source is the only area touched and is neutral.
    auto zero=base;
    const auto first=timed(zero,n,sx,sy,30.,speed,radius,0.,1./speed);
    assert(first.area_completions==1 && first.wave_arrivals==1);
    assert(first.tinted_pixels==0 && zero.rgba==base.rgba);
    // An advancing ring may tint only its own half-open arrival window.
    const double mid=.10,span=.012;
    auto ring=base,replay=base;
    const auto m=timed(ring,n,sx,sy,30.,speed,radius,mid,span);
    const auto m2=timed(replay,n,sx,sy,30.,speed,radius,mid,span);
    assert(ring.rgba==replay.rgba && m.event_fingerprint==m2.event_fingerprint);
    assert(m.area_completions>0 && m.area_completions<std::size_t(n)*n);
    assert(m.wave_arrivals>=m.area_completions &&
           m.spatial_candidates>=m.wave_arrivals);
    std::size_t expected=0;
    for(int y=0;y<n;++y)for(int x=0;x<n;++x){
        const double d=std::hypot(double(x-sx),double(y-sy));
        const double arrival=d/speed;
        const bool active=d<=radius && arrival<=mid && arrival>mid-span;
        expected+=active;
        const auto i=std::size_t(y)*n+x;
        if(!active || base.owners[i]!=7)
            for(int c=0;c<4;++c)assert(ring.rgba[4*i+c]==base.rgba[4*i+c]);
        assert(ring.rgba[4*i+3]==base.rgba[4*i+3]);
    }
    assert(m.area_completions==expected);
    auto past=base;
    const auto gone=timed(past,n,sx,sy,30.,speed,radius,10.,.01);
    assert(gone.area_completions==0 && past.rgba==base.rgba);
    // Single frame = no remembered event state. Nonoverlapping 1-second
    // windows on grid at c=1 cover each radius<=3 cell exactly once.
    std::size_t total=0;
    for(int tick=0;tick<=3;++tick){
        auto frame=base;
        const auto r=timed(frame,n,sx,sy,.2,1.,3.,double(tick),1.);
        total+=r.area_completions;
        for(int y=0;y<n;++y)for(int x=0;x<n;++x){
            const double dist=std::hypot(double(x-sx),double(y-sy));
            const bool active=dist<=3. && dist<=double(tick) &&
                (tick==0 || dist>double(tick-1));
            if(!active) for(int c=0;c<4;++c)
                assert(frame.rgba[4*(std::size_t(y)*n+x)+c] ==
                       base.rgba[4*(std::size_t(y)*n+x)+c]);
        }
    }
    std::size_t within=0;
    for(int y=0;y<n;++y)for(int x=0;x<n;++x)
        within+=std::hypot(double(x-sx),double(y-sy))<=3.;
    assert(within==total);
    // Reject bad config and depth outside ring before touching caller bytes.
    auto altered=base.rgba;
    auto corrupt=base.depth;
    corrupt[0]=std::numeric_limits<float>::quiet_NaN();
    rejects([&]{wave::apply_at_time(altered.data(),altered.size(),
        corrupt.data(),corrupt.size(),base.owners.data(),base.owners.size(),
        n,n,sx,sy,{30,0,0},speed,1.,radius,mid,span,7,true);},
        "SINGLE_IMPACT_SCENE_INVALID");
    rejects([&]{wave::apply_at_time(altered.data(),altered.size()-1,
        base.depth.data(),base.depth.size(),base.owners.data(),base.owners.size(),
        n,n,sx,sy,{30,0,0},speed,1.,radius,mid,span,7,true);},
        "SINGLE_IMPACT_INPUT_INVALID");
    rejects([&]{wave::apply_at_time(altered.data(),altered.size(),
        base.depth.data(),base.depth.size(),base.owners.data(),base.owners.size(),
        n,n,sx,sy,{30,0,0},speed,1.,radius,-1.,span,7,true);},
        "SINGLE_IMPACT_TIME_INVALID");
    rejects([&]{wave::apply_at_time(altered.data(),altered.size(),
        base.depth.data(),base.depth.size(),base.owners.data(),base.owners.size(),
        n,n,sx,sy,{30,0,0},speed,1.,radius,mid,0.,7,true);},
        "SINGLE_IMPACT_TIME_INVALID");
    rejects([&]{wave::apply_at_time(altered.data(),altered.size(),
        base.depth.data(),base.depth.size(),base.owners.data(),base.owners.size(),
        n,n,sx,sy,{120,0,0},speed,1.,radius,mid,span,7,true);},
        "SINGLE_IMPACT_VELOCITY_BUDGET");
    assert(altered==base.rgba);
}
static void measure(int n,const std::array<double,46>& geom){
    const int sx=n/2,sy=n/2;
    const double speed=120.,radius=double(n),elapsed=1.+radius/speed;
    const double ring_time=double(n)*.5/speed,ring_window=double(n)*.125/speed;
    std::array<std::vector<double>,3> samples{};
    std::array<std::uint64_t,3> hashes{};
    std::array<std::size_t,3> covered{};
    using clock=std::chrono::steady_clock;
    for(int rep=-2;rep<15;++rep)for(int slot=0;slot<3;++slot){
        const int selector=rep%2==0?slot:2-slot;
        const int mode=(selector+rep+300)%3;
        const auto start=clock::now();
        auto f=draw(n,geom);
        if(mode==0){
            const auto r=wave::apply(f.rgba.data(),f.rgba.size(),
               f.depth.data(),f.depth.size(),f.owners.data(),f.owners.size(),
               n,n,sx,sy,{30,0,0},speed,1.,radius,7,true);
            covered[0]=r.area_completions;
        }else{
            const auto r=timed(f,n,sx,sy,30.,speed,radius,
                mode==1?elapsed:ring_time,mode==1?elapsed+1.:ring_window);
            assert(r.reemissions==0 && r.queue_pushes==0);
            covered[mode]=r.area_completions;
        }
        const double ms=std::chrono::duration<double,std::milli>(clock::now()-start).count();
        assert(std::isfinite(ms) && ms>0);
        const auto hash=checksum(f.rgba);
        if(rep==-2)hashes[mode]=hash;
        else assert(hashes[mode]==hash);
        if(rep>=0)samples[mode].push_back(ms);
    }
    for(const auto& s:samples)assert(s.size()==15);
    assert(hashes[0]==hashes[1] && covered[0]==covered[1] && covered[2]<covered[1]);
    const auto med=[](std::vector<double> a){
        std::sort(a.begin(),a.end());return a[a.size()/2];
    };
    std::vector<double> paired;
    for(int i=0;i<15;++i)paired.push_back(samples[0][i]/samples[1][i]);
    const auto print=[](const std::vector<double>& v){
        std::cout<<"[";
        for(std::size_t i=0;i<v.size();++i){if(i)std::cout<<",";std::cout<<v[i];}
        std::cout<<"]";
    };
    std::cout<<std::fixed<<std::setprecision(9)
        <<"SINGLE_ORIGIN_TIME_RECEIPT {\"pixels\":"<<n
        <<",\"pairs\":15,\"mode\":\"native_cpp_full_draw\""
        <<",\"image_parity_static_full\":true"
        <<",\"median_static_ms\":"<<med(samples[0])
        <<",\"median_full_window_ms\":"<<med(samples[1])
        <<",\"median_ring_ms\":"<<med(samples[2])
        <<",\"paired_static_over_full_window\":"<<med(paired)
        <<",\"area_static\":"<<covered[0]
        <<",\"area_full_window\":"<<covered[1]
        <<",\"area_ring\":"<<covered[2]
        <<",\"static_rgba_fnv64\":"<<hashes[0]
        <<",\"full_rgba_fnv64\":"<<hashes[1]
        <<",\"ring_rgba_fnv64\":"<<hashes[2]
        <<",\"raw_ms\":{\"static\":";print(samples[0]);
    std::cout<<",\"full\":";print(samples[1]);
    std::cout<<",\"ring\":";print(samples[2]);std::cout<<"}}\n";
}

// Eight independent native raster frames, from a pristine framebuffer on every
// tick. Exported P6 frames are visual evidence, not a performance comparison.
static void visual_sequence(int n,const std::array<double,46>& geom,
                            const char* export_directory) {
    assert(n==128);
    const auto base=draw(n,geom);
    const int sx=n/2, sy=n/2;
    const double speed=8., radius=48., window=1.;
    const std::array<std::size_t,8> oracle{{1,196,600,996,1416,1816,2188,0}};
    std::vector<unsigned> arrivals(std::size_t(n)*n,0);
    std::array<std::uint64_t,8> frame_hashes{};
    std::size_t total=0;
    for(int tick=0;tick<8;++tick){
        auto frame=base, replay=base;
        const double elapsed=double(tick);
        const auto receipt=timed(frame,n,sx,sy,3.,speed,radius,elapsed,window);
        const auto twice=timed(replay,n,sx,sy,3.,speed,radius,elapsed,window);
        assert(frame.rgba==replay.rgba && frame.depth==base.depth &&
               replay.depth==base.depth && frame.owners==base.owners);
        assert(receipt.area_completions==twice.area_completions &&
               receipt.event_fingerprint==twice.event_fingerprint &&
               receipt.area_completions==oracle[std::size_t(tick)]);
        assert(receipt.spherepop_starts==1 && receipt.reemissions==0 &&
               receipt.queue_pushes==0 && receipt.refusals==0);
        std::size_t independently_active=0;
        for(int y=0;y<n;++y)for(int x=0;x<n;++x){
            const auto cell=std::size_t(y)*n+x;
            const double distance=std::hypot(double(x-sx),double(y-sy));
            const double arrival=distance/speed;
            const bool active=distance<=radius && arrival<=elapsed &&
                (tick==0 || arrival>elapsed-window);
            if(active){++arrivals[cell];++independently_active;}
            if(!active || base.owners[cell]!=7)
                for(int c=0;c<4;++c)
                    assert(frame.rgba[4*cell+c]==base.rgba[4*cell+c]);
            assert(frame.rgba[4*cell+3]==base.rgba[4*cell+3]);
        }
        assert(independently_active==receipt.area_completions);
        frame_hashes[std::size_t(tick)]=checksum(frame.rgba);
        if(export_directory){
            const std::string path=std::string(export_directory)+
                "/wave-"+std::to_string(tick)+".ppm";
            std::ofstream ppm(path,std::ios::binary);
            if(!ppm) throw std::runtime_error("SINGLE_ORIGIN_SEQUENCE_EXPORT_OPEN");
            ppm<<"P6\n"<<n<<" "<<n<<"\n255\n";
            for(std::size_t i=0;i<frame.rgba.size();i+=4)
                ppm.write(reinterpret_cast<const char*>(frame.rgba.data()+i),3);
            if(!ppm) throw std::runtime_error("SINGLE_ORIGIN_SEQUENCE_EXPORT_WRITE");
        }
        total+=receipt.area_completions;
        std::cout<<"SINGLE_ORIGIN_SEQUENCE_FRAME {\"tick\":"<<tick
                 <<",\"areas\":"<<receipt.area_completions
                 <<",\"tinted\":"<<receipt.tinted_pixels
                 <<",\"rgba_fnv64\":"<<frame_hashes[std::size_t(tick)]<<"}\n";
    }
    std::size_t circle=0;
    for(int y=0;y<n;++y)for(int x=0;x<n;++x){
        const auto cell=std::size_t(y)*n+x;
        const bool in_circle=std::hypot(double(x-sx),double(y-sy))<=radius;
        circle+=in_circle;
        assert(arrivals[cell]==unsigned(in_circle));
    }
    assert(total==7213 && total==circle);
    assert(frame_hashes[0]==frame_hashes[7] &&
           std::set<std::uint64_t>(frame_hashes.begin(),frame_hashes.end()).size()>=6);
    std::cout<<"SINGLE_ORIGIN_SEQUENCE_PASS frames=8 unique_areas="
             <<total<<" repeated_areas=0\n";
}

int main(int argc,char** argv){
    if(argc!=1 && !(argc==3 && std::string(argv[1])=="--frames-dir"))
        return 2;
    assert(wave::arrival_seconds(0,0,3,4,5.)==1.);
    for(int n:{32,64,128,256}){
        const auto geom=geometry(n);
        check(n,geom);
        if(n==128) visual_sequence(n,geom,argc==3?argv[2]:nullptr);
        measure(n,geom);
    }
    std::cout<<"SINGLE_ORIGIN_TIME_NATIVE_PASS\n";
}
