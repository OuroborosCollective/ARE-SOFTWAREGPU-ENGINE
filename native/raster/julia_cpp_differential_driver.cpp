// OuroborosCollective. Repository license applies.
// Independent-language differential fixture; actual native C++17 effect code.
#include "doppler_only.hpp"
#include "spherepop_cag_radial_wave.hpp"
#include <array>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

using are::raster::experimental::Vec3;
using are::raster::experimental::WaveReceipt;

template <typename F>
static void expect_reject(F&& f, const char* expected) {
    try { f(); }
    catch (const std::invalid_argument& e) {
        if (std::string(e.what()) == expected) return;
        throw;
    }
    throw std::runtime_error(std::string("MISSING_REJECTION:") + expected);
}

static void emit_factor(const char* name, Vec3 observer, Vec3 velocity) {
    constexpr Vec3 source{0.,0.,0.};
    const auto direct=are::raster::doppler_only::classical_factor(
        {source.x,source.y,source.z},
        {observer.x,observer.y,observer.z},
        {velocity.x,velocity.y,velocity.z},120.);
    const auto sphere=are::raster::experimental::doppler_factor(
        source,observer,velocity,120.);
    std::cout<<"D\t"<<name<<"\t"<<direct<<"\t"<<sphere<<"\n";
}

int main() {
    try {
        std::cout<<std::setprecision(17);
        emit_factor("toward",{10.,0.,0.},{30.,0.,0.});
        emit_factor("away",{10.,0.,0.},{-30.,0.,0.});
        emit_factor("neutral",{10.,0.,0.},{0.,0.,0.});
        emit_factor("diagonal",{10.,10.,0.},{30.,0.,0.});
        emit_factor("diagonal_away",{10.,10.,0.},{-30.,0.,0.});
        expect_reject([]{are::raster::experimental::doppler_factor(
            {0,0,0},{0,0,0},{30,0,0},120);},"DOPPLER_LINE_OF_SIGHT_INVALID");
        expect_reject([]{are::raster::experimental::doppler_factor(
            {0,0,0},{1,0,0},{114,0,0},120);},"DOPPLER_VELOCITY_BUDGET");
        expect_reject([]{are::raster::doppler_only::classical_factor(
            {0,0,0},{1,0,0},{114,0,0},120);},"DOPPLER_ONLY_VELOCITY_BUDGET");
        if (are::raster::doppler_only::classical_factor(
            {0,0,0},{0,0,0},{30,0,0},120.)!=1.)
            throw std::runtime_error("COINCIDENT_DIRECT_CONTRACT");
        std::cout<<"R\tnegative_and_coincident_contracts\t1\n";

        constexpr int width=4,height=4,cells=width*height;
        std::array<std::uint8_t,cells*4> initial{};
        std::array<float,cells> depth{};
        std::array<std::uint32_t,cells> owners{};
        depth.fill(.5f);
        owners.fill(7);
        owners[0]=owners[cells-1]=0;
        depth[0]=depth[cells-1]=1.f;
        for (int i=0;i<cells;++i) {
            initial[4*i]=96;
            initial[4*i+1]=40;
            initial[4*i+2]=128;
            initial[4*i+3]=255;
        }
        std::vector<are::raster::experimental::WaveArea> reference;
        std::array<std::uint8_t,cells*4> reference_rgba{};
        std::uint64_t reference_refusals=0,reference_fingerprint=0;
        std::size_t reference_tinted=0;
        for (int mode=0;mode<3;++mode) {
            auto pixels=initial;
            const bool doppler=mode!=2;
            const bool reuse=mode==1;
            const char* label=mode==0?"baseline":mode==1?"reuse":"off";
            const WaveReceipt receipt=are::raster::experimental::render_radial_cag_spherepop(
                pixels.data(),pixels.size(),depth.data(),depth.size(),
                owners.data(),owners.size(),width,height,1,1,
                {30.,0.,0.},120.,1.,doppler,reuse);
            if (receipt.finalized.size()!=cells)
                throw std::runtime_error("UNFINISHED_WAVE");
            if (mode==0) {
                reference=receipt.finalized;
                reference_rgba=pixels;
                reference_refusals=receipt.refusals;
                reference_fingerprint=receipt.event_fingerprint;
                reference_tinted=receipt.tinted_pixels;
            } else if (mode==1) {
                if (pixels!=reference_rgba ||
                    receipt.refusals!=reference_refusals ||
                    receipt.event_fingerprint!=reference_fingerprint ||
                    receipt.tinted_pixels!=reference_tinted ||
                    receipt.finalized.size()!=reference.size())
                    throw std::runtime_error("WAVE_REUSE_DRIFT");
                for (std::size_t k=0;k<reference.size();++k) {
                    const auto a=receipt.finalized[k],b=reference[k];
                    if (a.area!=b.area||a.emitter!=b.emitter||
                        a.arrival_seconds!=b.arrival_seconds||a.doppler!=b.doppler||
                        a.owner!=b.owner||a.tinted!=b.tinted)
                        throw std::runtime_error("WAVE_REUSE_EVENT_DRIFT");
                }
            } else if (pixels!=initial || receipt.tinted_pixels!=0)
                throw std::runtime_error("WAVE_OFF_CHANGED_FRAME");

            for (const auto& area:receipt.finalized) {
                const std::size_t i=area.area;
                std::cout<<"W\t"<<label<<"\t"<<area.area<<"\t"<<area.emitter
                         <<"\t"<<area.arrival_seconds<<"\t"<<area.doppler
                         <<"\t"<<area.owner<<"\t"<<area.tinted;
                for(int c=0;c<4;++c)
                    std::cout<<"\t"<<unsigned(pixels[4*i+c]);
                std::cout<<"\n";
            }
            std::cout<<"M\t"<<label<<"\t"<<receipt.refusals<<"\t"
                     <<receipt.event_fingerprint<<"\t"<<receipt.tinted_pixels
                     <<"\t"<<receipt.doppler_factor_evaluations<<"\n";
        }
        // Admission must be transactional even with one corrupt non-owner pixel.
        auto corrupt=depth;
        corrupt[0]=std::numeric_limits<float>::quiet_NaN();
        auto unchanged=initial;
        expect_reject([&]{are::raster::experimental::render_radial_cag_spherepop(
            unchanged.data(),unchanged.size(),corrupt.data(),corrupt.size(),
            owners.data(),owners.size(),width,height,1,1,
            {30.,0.,0.},120.,1.);},"SPHEREPOP_WAVE_SCENE_INVALID");
        if (unchanged!=initial) throw std::runtime_error("REJECTION_MUTATED_FRAME");
        std::cout<<"R\ttransactional_nan_rejection\t1\n";
        return 0;
    } catch(const std::exception& e) {
        std::cerr<<"CPP_JULIA_DIFFERENTIAL_FAIL:"<<e.what()<<"\n";
        return 1;
    }
}
