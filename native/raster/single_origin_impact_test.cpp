// Native C++17 real-raster comparison: chained SpherePop vs one-source impact.
// Built into standard Linux/Windows regression; no mock draw or fake times.
#include "core.hpp"
#include "single_origin_impact_wave.hpp"
#include "spherepop_cag_radial_wave.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>
namespace single=are::raster::single_origin;
namespace chained=are::raster::experimental;
template<class F> void rejects(F f,const char* expected) {
  bool hit=false;
  try {f();}catch(const std::invalid_argument& e){hit=(std::string(e.what())==expected);}
  assert(hit);
}
static std::array<double,46> square(int pixels) {
  std::array<double,46> a{};
  for(int t=0;t<2;++t){
    double* p=a.data()+23*t;
    const std::array<double,6> xy=t==0
      ? std::array<double,6>{0.,0.,0.,double(pixels),double(pixels),0.}
      : std::array<double,6>{double(pixels),double(pixels),double(pixels),0.,0.,double(pixels)};
    for(int v=0;v<3;++v) {
      p[3*v]=xy[2*v];p[3*v+1]=xy[2*v+1];p[3*v+2]=0.5;
      p[9+v]=1.; p[13+3*v]=.5; p[14+3*v]=.4; p[15+3*v]=.35;
    }
    p[12]=1.0/double(pixels*pixels);
  }
  return a;
}
struct Frame {
  std::vector<std::uint8_t> pixels;
  std::vector<float> depth;
  std::vector<std::uint32_t> owners;
};
static Frame raster(int n,const std::array<double,46>& geom) {
  Frame f;
  const auto cells=std::size_t(n)*n;
  f.pixels.assign(4*cells,0);
  f.depth.assign(cells,1.f);
  f.owners.assign(cells,0);
  std::array<std::uint64_t,3> stats{};
  assert(are::raster::draw(geom.data(),geom.size(),2,n,n,
     f.pixels.data(),f.pixels.size(),f.depth.data(),f.depth.size(),
     stats.data(),stats.size())==are::raster::ok);
  assert(stats[2]>0);
  for(std::size_t i=0;i<cells;++i)
    if(f.depth[i]<1.f&&i%17!=0) f.owners[i]=7;
  return f;
}
static void check(int n) {
  auto geom=square(n);
  auto base=raster(n,geom);
  const int sx=n/2,sy=n/2;
  // Native reference and new mode use exactly one real framebuffer.
  auto wave=base.pixels, direct=base.pixels;
  const auto old=chained::render_radial_cag_spherepop(wave.data(),wave.size(),
    base.depth.data(),base.depth.size(),base.owners.data(),base.owners.size(),
    n,n,sx,sy,{30.,0.,0.},120.,1.,true,true);
  const auto result=single::apply(direct.data(),direct.size(),
    base.depth.data(),base.depth.size(),base.owners.data(),base.owners.size(),
    n,n,sx,sy,{30.,0.,0.},120.,1.,double(n),7,true);
  assert(result.area_completions==std::size_t(n*n));
  assert(result.spherepop_starts==1 && result.reemissions==0);
  assert(result.queue_pushes==0 && result.refusals==0);
  assert(result.doppler_evaluations<=std::size_t(n*n));
  assert(old.refusals>0);
  assert(result.tinted_pixels>0 && wave!=direct); // different physical emitters
  assert(result.event_fingerprint!=0);
  for(std::size_t i=0;i<base.depth.size();++i) {
    assert(base.pixels[4*i+3]==direct[4*i+3]);
    if(base.owners[i]!=7)
      for(int c=0;c<4;++c)assert(base.pixels[4*i+c]==direct[4*i+c]);
  }
  // Exact deterministic replay and no cross-frame persistence.
  auto replay=base.pixels;
  auto again=single::apply(replay.data(),replay.size(),base.depth.data(),
    base.depth.size(),base.owners.data(),base.owners.size(),
    n,n,sx,sy,{30.,0.,0.},120.,1.,double(n),7,true);
  assert(replay==direct && again.event_fingerprint==result.event_fingerprint);
  assert(again.area_completions==result.area_completions);
  // "No Doppler" retains completion but cannot tint a pixel.
  auto neutral=base.pixels;
  auto plain=single::apply(neutral.data(),neutral.size(),base.depth.data(),
    base.depth.size(),base.owners.data(),base.owners.size(),
    n,n,sx,sy,{30.,0.,0.},120.,1.,double(n),7,false);
  assert(neutral==base.pixels && plain.tinted_pixels==0);
  assert(plain.area_completions==result.area_completions);
  // Impact radius clipped to viewport, outside untouched. Check float32 depth.
  auto cropped=base.pixels;
  const auto radius=3.;
  auto local=single::apply(cropped.data(),cropped.size(),base.depth.data(),
    base.depth.size(),base.owners.data(),base.owners.size(),
    n,n,sx,sy,{30.,0.,0.},120.,1.,radius,7,true);
  assert(local.area_completions>0 && local.area_completions<std::size_t(n*n));
  for(int y=0;y<n;++y)for(int x=0;x<n;++x) {
    double d=std::hypot(double(x-sx),double(y-sy));
    if(d>radius)
      for(int c=0;c<4;++c)assert(cropped[4*(y*n+x)+c]==base.pixels[4*(y*n+x)+c]);
  }
  // Border clipping and zero-radius seed (no Doppler line of sight).
  auto border=base.pixels;
  auto b=single::apply(border.data(),border.size(),base.depth.data(),
    base.depth.size(),base.owners.data(),base.owners.size(),
    n,n,0,0,{30,0,0},120,1,0.,7,true);
  assert(b.area_completions==1 && b.tinted_pixels==0 && border==base.pixels);
  // Invalid scene/config cannot partially mutate the source frame.
  auto broken=base.pixels;
  auto bad_depth=base.depth;
  bad_depth[0]=std::numeric_limits<float>::quiet_NaN();
  rejects([&]{single::apply(broken.data(),broken.size(),
    bad_depth.data(),bad_depth.size(),base.owners.data(),base.owners.size(),
    n,n,sx,sy,{30,0,0},120,1,double(n),7,true);},
    "SINGLE_IMPACT_SCENE_INVALID");
  rejects([&]{single::apply(broken.data(),broken.size()-1,
    base.depth.data(),base.depth.size(),base.owners.data(),base.owners.size(),
    n,n,sx,sy,{30,0,0},120,1,double(n),7,true);},
    "SINGLE_IMPACT_INPUT_INVALID");
  rejects([&]{single::apply(broken.data(),broken.size(),
    base.depth.data(),base.depth.size(),base.owners.data(),base.owners.size(),
    n,n,sx,sy,{120,0,0},120,1,double(n),7,true);},
    "SINGLE_IMPACT_VELOCITY_BUDGET");
  rejects([&]{single::apply(broken.data(),broken.size(),
    base.depth.data(),base.depth.size(),base.owners.data(),base.owners.size(),
    n,n,sx,sy,{30,0,0},120,1,-1.,7,true);},
    "SINGLE_IMPACT_INPUT_INVALID");
  assert(broken==base.pixels);
  // Fixed source, octile-geometry vs Euclidean arrival semantic regression.
  assert(std::abs(single::octile_distance(0,0,3,4)-(4.+3.*(std::sqrt(2.)-1.)))<1e-14);
  assert(std::abs(single::euclidean_distance(0,0,3,4)-5.)<1e-14);
  std::array<std::vector<double>,2> samples{};
  using clock=std::chrono::steady_clock;
  for(int rep=-2;rep<15;++rep)for(int k=0;k<2;++k) {
    bool fast=(k==(rep%2==0?0:1));
    auto f=raster(n,geom);
    const auto start=clock::now();
    if(fast) {
      auto rr=single::apply(f.pixels.data(),f.pixels.size(),f.depth.data(),
        f.depth.size(),f.owners.data(),f.owners.size(),
        n,n,sx,sy,{30,0,0},120,1,double(n),7,true);
      assert(rr.event_fingerprint==result.event_fingerprint && f.pixels==direct);
    } else {
      auto rr=chained::render_radial_cag_spherepop(f.pixels.data(),f.pixels.size(),
        f.depth.data(),f.depth.size(),f.owners.data(),f.owners.size(),
        n,n,sx,sy,{30,0,0},120,1,true,true);
      assert(rr.event_fingerprint==old.event_fingerprint && f.pixels==wave);
    }
    const double ms=std::chrono::duration<double,std::milli>(clock::now()-start).count();
    assert(std::isfinite(ms) && ms>0);
    if(rep>=0)samples[fast?1:0].push_back(ms);
  }
  auto med=[](std::vector<double> v){std::sort(v.begin(),v.end());return v[v.size()/2];};
  std::vector<double> speedup;
  for(std::size_t i=0;i<15;++i) speedup.push_back(samples[0][i]/samples[1][i]);
  auto write=[](const std::vector<double>& v){
    std::cout<<"[";for(std::size_t i=0;i<v.size();++i){if(i)std::cout<<",";std::cout<<v[i];}std::cout<<"]";
  };
  std::cout<<std::fixed<<std::setprecision(9)
    <<"SINGLE_ORIGIN_IMPACT_RECEIPT {\"pixels\":"<<n
    <<",\"repeats\":15,\"radius\":"<<n
    <<",\"source_count\":1,\"mode\":\"native_cpp_effect_only\""
    <<",\"spherepop_refusals\":"<<old.refusals
    <<",\"single_area_completions\":"<<result.area_completions
    <<",\"single_reemissions\":"<<result.reemissions
    <<",\"single_tinted\":"<<result.tinted_pixels
    <<",\"median_chain_ms\":"<<med(samples[0])
    <<",\"median_single_ms\":"<<med(samples[1])
    <<",\"paired_speedup\":"<<med(speedup)
    <<",\"raw_ms\":{\"chain\":";write(samples[0]);
  std::cout<<",\"single\":";write(samples[1]);std::cout<<"}}\n";
}
int main() {check(32);check(64);std::cout<<"SINGLE_ORIGIN_NATIVE_PASS\n";}
