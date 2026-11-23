// Real ARE native C++ pixel transport to an actual X11/XCB window.
// Admits actual X server readback, not a Vulkan VkSurfaceKHR or Swapchain.
#include "xcb_present.hpp"
#include "../raster/driver_adapter.hpp"
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <vector>
extern "C" int are_driver_draw_v1(const are::driver::DrawV1*, std::size_t);

#define REQUIRE(test) do { if (!(test)) { std::cerr << "ARE_XCB_TEST_FAIL:" << __LINE__ << ":" << #test << std::endl; return 2; } } while (false)

std::array<double,23> triangle(bool red) {
    std::array<double,23> t{};
    t[0]=2;t[1]=2;t[2]=0.5;
    t[3]=2;t[4]=18;t[5]=0.5;
    t[6]=18;t[7]=2;t[8]=0.5;
    t[9]=1;t[10]=1;t[11]=1;
    t[12]=1.0/256.0;
    for (int i=0;i<3;++i) t[13+3*i+(red?0:1)]=1;
    return t;
}
struct Frame {
    std::vector<std::uint8_t> rgba = std::vector<std::uint8_t>(32u*24u*4u,0);
    std::vector<float> depth = std::vector<float>(32u*24u,1.0f);
    std::array<std::uint64_t,3> counts{};
};
Frame draw_frame(bool red) {
    auto data=triangle(red);
    Frame out;
    are::driver::DrawV1 d{};
    d.struct_size=sizeof(d);
    d.profile=are::driver::packed_vertex_color;
    d.packed=data.data();
    d.cells=data.size();d.count=1;
    d.width=32;d.height=24;
    d.rgba=out.rgba.data();d.rgba_bytes=out.rgba.size();
    d.depth=out.depth.data();d.depth_cells=out.depth.size();
    d.counts=out.counts.data();d.count_cells=out.counts.size();
    if (are_driver_draw_v1(&d,sizeof(d)) != 0) out.counts={};
    return out;
}
bool write_bytes(const char* path,const std::vector<std::uint8_t>& bytes) {
    std::ofstream f(path,std::ios::binary);
    if (!f) return false;
    f.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
    return static_cast<bool>(f);
}
int main(int argc,char** argv) {
    REQUIRE(argc==5);
    const Frame red=draw_frame(true), green=draw_frame(false);
    REQUIRE(red.counts[2]>0 && green.counts[2]>0);
    REQUIRE(red.counts==green.counts);
    REQUIRE(red.rgba!=green.rgba);
    REQUIRE(red.depth==green.depth);
    are::vulkan::xcb::WindowPresenter presenter(32,24);
    REQUIRE(presenter.ready());
    std::vector<std::uint8_t> capture_red,capture_green;
    REQUIRE(presenter.present_and_readback(red.rgba,&capture_red) ==
            are::vulkan::xcb::PresentStatus::ok);
    REQUIRE(presenter.present_and_readback(green.rgba,&capture_green) ==
            are::vulkan::xcb::PresentStatus::ok);
    REQUIRE(capture_red!=capture_green);
    REQUIRE(capture_red.size()==32u*24u*4u && capture_green.size()==capture_red.size());
    REQUIRE(write_bytes(argv[1],red.rgba));
    REQUIRE(write_bytes(argv[2],green.rgba));
    REQUIRE(write_bytes(argv[3],capture_red));
    REQUIRE(write_bytes(argv[4],capture_green));
    std::cout << "ARE_REAL_XCB_WINDOW_READBACK_PASS "
              << red.counts[0] << " " << red.counts[1] << " "
              << red.counts[2] << std::endl;
    return 0;
}
