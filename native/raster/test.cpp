#include "core.hpp"
#include <cassert>
#include <array>
#include <iostream>

int main() {
    std::array<double,46> p{};
    // Clockwise in screen coordinates under the renderer's edge convention.
    const double vertices[9]={0,0,0, 0,4,0, 4,0,0};
    std::copy(vertices,vertices+9,p.begin());
    p[9]=p[10]=p[11]=1; p[12]=1.0/16;
    for (int v=0;v<3;++v) p[13+3*v]=1; // red
    std::copy(p.begin(),p.begin()+23,p.begin()+23);
    std::array<std::uint8_t,64> rgba{};
    std::array<float,16> z;z.fill(1);
    std::array<std::uint64_t,3> counts{99,99,99};
    auto draw=[&](std::size_t n=1) {
        return are::raster::draw(p.data(),n*23,n,4,4,rgba.data(),rgba.size(),z.data(),z.size(),counts.data(),counts.size());
    };
    assert(draw()==0 && counts[0]==16 && counts[1]>0 && counts[2]==counts[1]);
    const auto before=rgba;const auto depth=z;
    assert(draw()==0 && counts[2]==0 && rgba==before && z==depth); // strict depth tie
    counts.fill(99);p[23+22]=8; // late invalid record must not write ANY output
    assert(draw(2)==are::raster::record && rgba==before && z==depth && counts[0]==99);
    p[23+22]=0;
    std::fesetround(FE_DOWNWARD);
    assert(draw()==are::raster::environment && rgba==before && z==depth);
    std::fesetround(FE_TONEAREST);
#if defined(__SSE__)
    const auto csr=_mm_getcsr();_mm_setcsr(csr|0x8000u);
    assert(draw()==are::raster::environment);
    _mm_setcsr(csr);
#endif
    assert(are::raster::draw(nullptr,0,0,0,4,rgba.data(),64,z.data(),16,counts.data(),3)==are::raster::budget);
    assert(are::raster::draw(nullptr,23,1,4,4,rgba.data(),64,z.data(),16,counts.data(),3)==are::raster::buffer);
    assert(are::raster::draw(nullptr,0,0,4,4,rgba.data(),64,z.data(),16,counts.data(),3)==0);
    assert(counts[0]==0 && counts[1]==0 && counts[2]==0);
    std::cout << "PASS native raster: depth ties, atomic validation, FP environment, empty draw\n";
}
