// Real C++17 CPU raster -> single-source Doppler without SpherePop, and
// 15 paired full-frame comparisons to bare raster and SpherePop+Doppler.
// This *test* imports both algorithms; doppler_only.hpp imports no SpherePop.
#include "core.hpp"
#include "doppler_only.hpp"
#include "spherepop_cag_radial_wave.hpp"
#include <algorithm>
#include <array>
#include <cassert>
#include <cfenv>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>
#if defined(__SSE__)
#include <xmmintrin.h>
#endif

namespace direct=are::raster::doppler_only;
namespace wave=are::raster::experimental;

template<typename F> static void expect_reject(F fn,const char* expected) {
    bool rejected=false;
    try { fn(); }
    catch(const std::invalid_argument& e) {
        rejected=true;
        assert(std::string(e.what())==expected);
    }
    assert(rejected);
}
static void check_wolfram() {
    const direct::Vec3 zero{0,0,0},velocity{30,0,0};
    constexpr double c=120.0;
    assert(std::abs(direct::classical_factor(zero,{1,0,0},velocity,c)-4.0/3.0)<1.e-14);
    assert(std::abs(direct::classical_factor(zero,{-1,0,0},velocity,c)-4.0/5.0)<1.e-14);
    assert(direct::classical_factor(zero,{0,0,0},velocity,c)==1.0);
    assert(direct::classical_factor(zero,{0,1,0},velocity,c)==1.0);
    assert(std::abs(direct::classical_factor(zero,{1,1,0},velocity,c)-
        c/(c-30.0/std::sqrt(2.0)))<1.e-14);
    assert(std::abs(direct::classical_factor(zero,{-1,1,0},velocity,c)-
        c/(c+30.0/std::sqrt(2.0)))<1.e-14);
    expect_reject([&]{direct::classical_factor(zero,{1,0,0},velocity,0);},
                  "DOPPLER_ONLY_INPUT_INVALID");
    expect_reject([&]{direct::classical_factor(zero,{1,0,0},{114,0,0},c);},
                  "DOPPLER_ONLY_VELOCITY_BUDGET");
    const auto nan=std::numeric_limits<double>::quiet_NaN();
    expect_reject([&]{direct::classical_factor(zero,{1,0,0},{nan,0,0},c);},
                  "DOPPLER_ONLY_INPUT_INVALID");
    std::fesetround(FE_DOWNWARD);
    expect_reject([&]{direct::classical_factor(zero,{1,0,0},velocity,c);},
                  "DOPPLER_ONLY_INPUT_INVALID");
    std::fesetround(FE_TONEAREST);
#if defined(__SSE__)
    const auto fp=_mm_getcsr();
    _mm_setcsr(fp|(1u<<15));
    expect_reject([&]{direct::classical_factor(zero,{1,0,0},velocity,c);},
                  "DOPPLER_ONLY_INPUT_INVALID");
    _mm_setcsr(fp|(1u<<6));
    expect_reject([&]{direct::classical_factor(zero,{1,0,0},velocity,c);},
                  "DOPPLER_ONLY_INPUT_INVALID");
    _mm_setcsr(fp);
#endif
}
static std::array<double,46> square(int pixels) {
    std::array<double,46> packed{};
    auto triangle=[&](int index,std::array<double,6> xy) {
        double* p=packed.data()+index*23;
        for(int v=0;v<3;++v) {
            p[3*v]=xy[2*v];
            p[3*v+1]=xy[2*v+1];
            p[3*v+2]=0.5;
            p[9+v]=1.0;
            p[13+3*v]=0.50;
            p[14+3*v]=0.40;
            p[15+3*v]=0.35;
        }
        p[12]=1.0/double(pixels*pixels);
    };
    triangle(0,{0.,0.,0.,double(pixels),double(pixels),0.});
    triangle(1,{double(pixels),double(pixels),double(pixels),0.,0.,double(pixels)});
    return packed;
}
static std::uint64_t checksum(const std::uint8_t* p,std::size_t n) {
    std::uint64_t v=14695981039346656037ull;
    for(std::size_t i=0;i<n;++i) {v^=p[i];v*=1099511628211ull;}
    return v;
}
template<typename T> static std::uint64_t hash_vector(const std::vector<T>& data) {
    return checksum(reinterpret_cast<const std::uint8_t*>(data.data()),data.size()*sizeof(T));
}
struct Observed {
    std::vector<std::uint8_t> rgba;
    std::vector<float> depth;
    std::size_t tinted=0;
    std::size_t wave_refusals=0;
    std::size_t finished=0;
};
static Observed render_once(int pixels,const std::array<double,46>& packed,int mode) {
    const auto cells=std::size_t(pixels)*pixels;
    Observed result{};
    result.rgba.assign(cells*4,0);
    result.depth.assign(cells,1.0f);
    std::array<std::uint64_t,3> counts{};
    const int status=are::raster::draw(packed.data(),packed.size(),2,pixels,pixels,
        result.rgba.data(),result.rgba.size(),
        result.depth.data(),result.depth.size(),counts.data(),counts.size());
    assert(status==are::raster::ok && counts[2]>0);
    if(mode==0)return result;
    std::vector<std::uint32_t> owners(cells,0);
    for(std::size_t i=0;i<cells;++i)
        if(result.depth[i]<1.0f) owners[i]=7;
    if(mode==1) {
        auto r=direct::apply_direct(result.rgba.data(),result.rgba.size(),
            result.depth.data(),result.depth.size(),owners.data(),owners.size(),
            pixels,pixels,pixels/2,pixels/2,{30,0,0},120,1,7);
        assert(r.visited_pixels==cells);
        result.tinted=r.tinted_pixels;
        result.finished=r.visited_pixels;
    } else {
        const auto r=wave::render_radial_cag_spherepop(
            result.rgba.data(),result.rgba.size(),
            result.depth.data(),result.depth.size(),
            owners.data(),owners.size(),pixels,pixels,pixels/2,pixels/2,
            {30,0,0},120,1,true);
        assert(r.finalized.size()==cells && r.refusals>0);
        result.finished=r.finalized.size();
        result.wave_refusals=std::size_t(r.refusals);
        result.tinted=r.tinted_pixels;
    }
    assert(result.tinted>0);
    return result;
}
static double median(std::vector<double> values) {
    assert(!values.empty());
    std::sort(values.begin(),values.end());
    return values.at(values.size()/2);
}
static void print_samples(const std::vector<double>& a) {
    std::cout<<"[";
    for(std::size_t i=0;i<a.size();++i) {
        if(i)std::cout<<",";
        std::cout<<a[i];
    }
    std::cout<<"]";
}
static void measure(int pixels) {
    const auto packed=square(pixels);
    const auto bare=render_once(pixels,packed,0);
    const auto single=render_once(pixels,packed,1);
    const auto pop=render_once(pixels,packed,2);
    const auto cells=std::size_t(pixels)*pixels;
    assert(single.depth==bare.depth && pop.depth==bare.depth);
    assert(single.rgba!=bare.rgba && pop.rgba!=bare.rgba);
    assert(single.finished==cells && pop.finished==cells && pop.wave_refusals>0);
    for(std::size_t i=0;i<cells;++i) {
        // The real native framebuffer alpha and every depth bit are preserved.
        assert(single.rgba[4*i+3]==bare.rgba[4*i+3]);
        assert(pop.rgba[4*i+3]==bare.rgba[4*i+3]);
        if(bare.depth[i]==1.0f)for(int c=0;c<4;++c) {
            assert(single.rgba[4*i+c]==bare.rgba[4*i+c]);
            assert(pop.rgba[4*i+c]==bare.rgba[4*i+c]);
        }
    }
    auto broken=bare.rgba;
    auto broken_depth=bare.depth;
    broken_depth[cells-1]=std::numeric_limits<float>::quiet_NaN();
    std::vector<std::uint32_t> owners(cells,7);
    const auto stable=broken;
    expect_reject([&]{direct::apply_direct(broken.data(),broken.size(),
        broken_depth.data(),broken_depth.size(),owners.data(),owners.size(),
        pixels,pixels,pixels/2,pixels/2,{30,0,0},120,1,7);},
        "DOPPLER_ONLY_DEPTH_INVALID");
    expect_reject([&]{direct::apply_direct(broken.data(),broken.size(),
        bare.depth.data(),bare.depth.size(),owners.data(),owners.size()-1,
        pixels,pixels,pixels/2,pixels/2,{30,0,0},120,1,7);},
        "DOPPLER_ONLY_BUFFER_INVALID");
    expect_reject([&]{direct::apply_direct(broken.data(),broken.size(),
        bare.depth.data(),bare.depth.size(),owners.data(),owners.size(),
        pixels,pixels,pixels/2,pixels/2,{114,0,0},120,1,7);},
        "DOPPLER_ONLY_VELOCITY_BUDGET");
    assert(broken==stable);
    // Independent direct mode must obey object ownership, including depth-ties.
    auto owners_other=owners;
    owners_other[0]=11;
    auto owned=bare.rgba;
    auto re=direct::apply_direct(owned.data(),owned.size(),bare.depth.data(),bare.depth.size(),
        owners_other.data(),owners_other.size(),pixels,pixels,pixels/2,pixels/2,
        {30,0,0},120,1,7);
    assert(re.tinted>0);
    for(int c=0;c<4;++c)assert(owned[c]==bare.rgba[c]);

    constexpr int repeats=15;
    using clock=std::chrono::steady_clock;
    std::array<std::vector<double>,3> samples{};
    // Same renderer work for all three modes; order rotates and reverses.
    for(int rep=-2;rep<repeats;++rep) {
        for(int slot=0;slot<3;++slot) {
            const int mode=(rep%2==0) ? (slot+rep+300)%3 : (2-slot+rep+300)%3;
            const auto start=clock::now();
            auto frame=render_once(pixels,packed,mode);
            const auto milliseconds=std::chrono::duration<double,std::milli>(clock::now()-start).count();
            assert(std::isfinite(milliseconds)&&milliseconds>0);
            const auto& expected=(mode==0?bare:mode==1?single:pop);
            assert(frame.depth==expected.depth && frame.rgba==expected.rgba &&
                   frame.finished==expected.finished && frame.tinted==expected.tinted &&
                   frame.wave_refusals==expected.wave_refusals);
            if(rep>=0)samples[mode].push_back(milliseconds);
        }
    }
    for(const auto& one:samples)assert(one.size()==repeats);
    std::vector<double> speedup,bare_to_direct,bare_to_pop;
    for(int i=0;i<repeats;++i) {
        speedup.push_back(samples[2][i]/samples[1][i]);
        bare_to_direct.push_back(samples[0][i]/samples[1][i]);
        bare_to_pop.push_back(samples[0][i]/samples[2][i]);
    }
    std::cout<<std::fixed<<std::setprecision(9);
    std::cout<<"DOPPLER_ONLY_FRAME_RECEIPT {\"pixels\":"<<pixels
             <<",\"pairs\":15,\"triangles\":2,\"backend\":\"native-cpp\""
             <<",\"median_bare_ms\":"<<median(samples[0])
             <<",\"median_doppler_only_ms\":"<<median(samples[1])
             <<",\"median_spherepop_doppler_ms\":"<<median(samples[2])
             <<",\"paired_sp_over_direct\":"<<median(speedup)
             <<",\"paired_bare_over_direct\":"<<median(bare_to_direct)
             <<",\"paired_bare_over_sp\":"<<median(bare_to_pop)
             <<",\"direct_tinted\":"<<single.tinted
             <<",\"spherepop_tinted\":"<<pop.tinted
             <<",\"spherepop_refusals\":"<<pop.wave_refusals
             <<",\"direct_rgba_fnv64\":"<<hash_vector(single.rgba)
             <<",\"spherepop_rgba_fnv64\":"<<hash_vector(pop.rgba)
             <<",\"depth_fnv64\":"<<hash_vector(bare.depth)
             <<",\"raw_ms\":{\"bare\":";
    print_samples(samples[0]);
    std::cout<<",\"direct\":";
    print_samples(samples[1]);
    std::cout<<",\"spherepop\":";
    print_samples(samples[2]);
    std::cout<<"}}\n";
}
int main() {
    check_wolfram();
    measure(32);
    measure(64);
    std::cout<<"DOPPLER_ONLY_REAL_RASTER_TEST_PASS\n";
}
