// ACTUAL ARE C++ raster -> real XCB PutImage -> X server GetImage.
// No fake window, framebuffer screenshot, Vulkan swapchain, or VkSurfaceKHR.
#include "xcb_frame_presenter.hpp"
#include "../raster/driver_adapter.hpp"
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

extern "C" int are_driver_draw_v1(const are::driver::DrawV1*, std::size_t);

using are::vulkan::prewsi::XcbFramePresenter;
using are::vulkan::prewsi::XcbStatus;
#define REQUIRE(condition) do { if (!(condition)) { \
  std::cerr << "ARE_XCB_FAILED:" << __LINE__ << ":" << #condition << '\n'; return 2; \
} } while (false)

static std::array<double,23> triangle(bool green) {
    const double r = green ? 0 : 1, g = green ? 1 : 0;
    return {{2,2,.5, 2,18,.5, 18,2,.5, 1,1,1,1.0/256,
             r,g,0, r,g,0, r,g,0, 0}};
}

static bool raster_frame(std::uint32_t width,std::uint32_t height,
                         bool green,std::vector<std::uint8_t>& color,
                         std::uint64_t& shaded) {
    auto tris=triangle(green);
    // Exercise the final row of the resized upload with actual shaded pixels.
    if (height == 1025) {
        for (auto index : {1, 4, 7}) tris[index] += height - 17;
    }
    color.assign(std::size_t(width)*height*4,0);
    for (std::size_t i=3; i<color.size(); i+=4) color[i]=255;
    std::vector<float> depth(std::size_t(width)*height,1.0f);
    std::array<std::uint64_t,3> counts{};
    are::driver::DrawV1 desc{};
    desc.struct_size=sizeof(desc);
    desc.profile=are::driver::packed_vertex_color;
    desc.packed=tris.data(); desc.cells=tris.size(); desc.count=1;
    desc.width=width; desc.height=height;
    desc.rgba=color.data();desc.rgba_bytes=color.size();
    desc.depth=depth.data();desc.depth_cells=depth.size();
    desc.counts=counts.data();desc.count_cells=counts.size();
    if (are_driver_draw_v1(&desc,sizeof(desc))!=0) return false;
    if (!(counts[0]>=counts[1] && counts[1]>=counts[2] && counts[2]>0))
        return false;
    shaded=counts[2];
    return true;
}

static bool save(const std::string& file,const std::vector<std::uint8_t>& bytes) {
    std::ofstream f(file,std::ios::binary);
    if (!f) return false;
    f.write(reinterpret_cast<const char*>(bytes.data()),bytes.size());
    return static_cast<bool>(f);
}

int main(int argc,char** argv) {
    if (argc==2 && std::string(argv[1])=="--negative-no-display") {
        XcbFramePresenter missing;
        REQUIRE(missing.open(32,24)==XcbStatus::unavailable);
        return 0;
    }
    if (argc==2 && std::string(argv[1])=="--negative-direct-color") {
        XcbFramePresenter window;
        REQUIRE(window.open(32,24)==XcbStatus::unsupported_visual);
        return 0;
    }
    if (argc != 2) return 64;
    const std::string root=argv[1];
    XcbFramePresenter window;
    REQUIRE(window.open(0,24)==XcbStatus::invalid_extent);
    REQUIRE(window.open(4097,24)==XcbStatus::invalid_extent);
    REQUIRE(window.open(32,24)==XcbStatus::ok);
    REQUIRE(window.depth()==24 && window.visual()!=0);
    REQUIRE(window.open(32,24)==XcbStatus::rejected_request);
    std::uint64_t shaded0=0,shaded1=0,shaded2=0;
    std::vector<std::uint8_t> first,second,large,returned;
    REQUIRE(raster_frame(32,24,false,first,shaded0));
    REQUIRE(window.present_rgba(first.data(),first.size()-1,32,24)==XcbStatus::invalid_payload);
    REQUIRE(window.present_rgba(nullptr,first.size(),32,24)==XcbStatus::invalid_payload);
    REQUIRE(window.present_rgba(first.data(),first.size(),31,24)==XcbStatus::out_of_date);
    REQUIRE(window.present_rgba(first.data(),first.size(),32,24)==XcbStatus::ok);
    REQUIRE(window.readback_rgba(&returned)==XcbStatus::ok);
    REQUIRE(returned==first);
    REQUIRE(save(root+"-first-cpu.rgba",first) && save(root+"-first-window.rgba",returned));

    REQUIRE(raster_frame(32,24,true,second,shaded1));
    REQUIRE(first!=second);
    REQUIRE(shaded0==shaded1 && shaded0>0);
    REQUIRE(window.present_rgba(second.data(),second.size(),32,24)==XcbStatus::ok);
    REQUIRE(window.readback_rgba(&returned)==XcbStatus::ok);
    REQUIRE(returned==second);
    REQUIRE(save(root+"-second-cpu.rgba",second) && save(root+"-second-window.rgba",returned));

    REQUIRE(window.resize(0,48)==XcbStatus::invalid_extent);
    REQUIRE(window.resize(1023,1025)==XcbStatus::ok);
    REQUIRE(window.present_rgba(second.data(),second.size(),32,24)==XcbStatus::out_of_date);
    REQUIRE(raster_frame(1023,1025,true,large,shaded2));
    REQUIRE(large[(1024 * 1023 + 2) * 4 + 1] == 255);
    REQUIRE(window.present_rgba(large.data(),large.size(),1023,1025)==XcbStatus::ok);
    REQUIRE(window.readback_rgba(&returned)==XcbStatus::ok);
    REQUIRE(returned==large);
    REQUIRE(save(root+"-resize-cpu.rgba",large) && save(root+"-resize-window.rgba",returned));
    REQUIRE(shaded0==shaded2);
    window.close();
    REQUIRE(window.readback_rgba(&returned)==XcbStatus::not_open);
    REQUIRE(window.present_rgba(large.data(),large.size(),1023,1025)==XcbStatus::not_open);
    std::cout << "ARE_XCB_REAL_NATIVE_FRAME_PASS first_shaded=" << shaded0
              << " second_shaded=" << shaded1 << " resized_shaded=" << shaded2
              << " visual=" << window.visual() << '\n';
    return 0;
}
