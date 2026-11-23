// REAL C++17 ARE CPU raster, pre-VkDevice resources. No mock renderer.
#include "resource_queue.hpp"
#include "../raster/driver_adapter.hpp"
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <vector>

extern "C" int are_driver_draw_v1(const are::driver::DrawV1*, std::size_t);

using are::vulkan::predevice::ResourceQueue;
using are::vulkan::predevice::ResourceStatus;
using are::vulkan::predevice::ResourceHandle;
using are::vulkan::predevice::DrawRecord;
using are::vulkan::predevice::ImageSnapshot;
using are::vulkan::predevice::RasterCounters;
#define CHECK(expr) do { if (!(expr)) { std::cerr << "ARE_RESOURCE_ASSERT:" << __LINE__ \
 << ":" << #expr << "\\n"; return 1; } } while(false)

static std::array<double, 23> triangle() {
    // Strict positive-area clockwise screen triangle, 16x16 px, one red pixel range.
    return {{2,2,0.5, 2,18,0.5, 18,2,0.5, 1,1,1, 1.0/256.0,
             1,0,0, 1,0,0, 1,0,0, 0}};
}

int main(int argc, char** argv) {
    if (argc != 3) return 99;
    ResourceQueue arena(64ull * 1024 * 1024);
    ResourceHandle a=0,b=0, frame=0, replay=0, invalid=0;
    auto tri=triangle();
    CHECK(arena.create_buffer(sizeof(tri), &a)==ResourceStatus::ok);
    CHECK(arena.create_buffer(sizeof(tri), &b)==ResourceStatus::ok);
    CHECK(arena.create_image(32,24,&frame)==ResourceStatus::ok);
    CHECK(arena.create_image(32,24,&replay)==ResourceStatus::ok);
    CHECK(arena.write_buffer(a,0,tri.data(),sizeof(tri))==ResourceStatus::ok);
    CHECK(arena.write_buffer(b,0,tri.data(),sizeof(tri))==ResourceStatus::ok);
    const std::vector<DrawRecord> commands{{a,0,1},{b,0,1}};
    tri[0]=9999.0; // caller changed its original: owned resource must not change
    RasterCounters counters{};
    CHECK(arena.submit(frame,commands,&counters)==ResourceStatus::ok);
    CHECK(counters.shaded_samples>0);
    CHECK(counters.covered_samples>=counters.shaded_samples);
    CHECK(counters.candidate_samples>=counters.covered_samples);
    ImageSnapshot observed{};
    CHECK(arena.snapshot(frame,&observed)==ResourceStatus::ok);
    CHECK(observed.rgba.size()==32u*24u*4u);
    CHECK(observed.depth.size()==32u*24u);

    // Independently call the ACTUAL ARE native C ABI for the same two triangles.
    const auto ground=triangle();
    std::vector<std::uint8_t> expected_color(32u*24u*4u,0);
    std::vector<float> expected_depth(32u*24u,1.0f);
    RasterCounters expected{};
    for (int i=0;i<2;++i) {
        std::array<std::uint64_t,3> output{};
        are::driver::DrawV1 desc{};
        desc.struct_size=static_cast<std::uint32_t>(sizeof(desc));
        desc.profile=are::driver::packed_vertex_color;
        desc.packed=ground.data(); desc.cells=ground.size(); desc.count=1;
        desc.width=32; desc.height=24;
        desc.rgba=expected_color.data(); desc.rgba_bytes=expected_color.size();
        desc.depth=expected_depth.data(); desc.depth_cells=expected_depth.size();
        desc.counts=output.data(); desc.count_cells=output.size();
        CHECK(are_driver_draw_v1(&desc,sizeof(desc))==0);
        expected.candidate_samples+=output[0];
        expected.covered_samples+=output[1];
        expected.shaded_samples+=output[2];
    }
    CHECK(observed.rgba==expected_color);
    CHECK(observed.depth==expected_depth);
    CHECK(counters.candidate_samples==expected.candidate_samples);
    CHECK(counters.covered_samples==expected.covered_samples);
    CHECK(counters.shaded_samples==expected.shaded_samples);

    RasterCounters replay_counts{};
    ImageSnapshot replayed{};
    CHECK(arena.submit(replay,commands,&replay_counts)==ResourceStatus::ok);
    CHECK(arena.snapshot(replay,&replayed)==ResourceStatus::ok);
    CHECK(replayed.rgba==observed.rgba && replayed.depth==observed.depth);
    CHECK(replay_counts==counters);

    // Late failure cannot publish partial color/depth or sample counts.
    auto malformed=triangle();
    malformed[0]=std::numeric_limits<double>::quiet_NaN();
    CHECK(arena.create_buffer(sizeof(malformed),&invalid)==ResourceStatus::ok);
    CHECK(arena.write_buffer(invalid,0,malformed.data(),sizeof(malformed))==ResourceStatus::ok);
    ImageSnapshot before{}, after{};
    CHECK(arena.snapshot(replay,&before)==ResourceStatus::ok);
    RasterCounters unchanged{11,22,33};
    CHECK(arena.submit(replay,{{a,0,1},{invalid,0,1}},&unchanged)
          ==ResourceStatus::native_rejected);
    CHECK(arena.snapshot(replay,&after)==ResourceStatus::ok);
    CHECK(after.rgba==before.rgba && after.depth==before.depth);
    CHECK((unchanged==RasterCounters{11,22,33}));

    CHECK(arena.write_buffer(a,sizeof(ground)-1,ground.data(),2)
          ==ResourceStatus::out_of_bounds);
    CHECK(arena.submit(replay,{{a,1,1}},&unchanged)
          ==ResourceStatus::out_of_bounds);
    CHECK(arena.destroy_buffer(a)==ResourceStatus::ok);
    CHECK(arena.submit(replay,{{a,0,1}},&unchanged)==ResourceStatus::invalid_handle);
    CHECK(arena.destroy_buffer(a)==ResourceStatus::invalid_handle);
    ResourceHandle newer=0;
    CHECK(arena.create_buffer(sizeof(ground),&newer)==ResourceStatus::ok);
    CHECK(newer!=a);
    CHECK(arena.submit(replay,{{a,0,1}},&unchanged)==ResourceStatus::invalid_handle);

    ResourceQueue tiny(128);
    ResourceHandle none=0;
    CHECK(tiny.create_image(32,24,&none)==ResourceStatus::out_of_budget);
    CHECK(none==0);
    CHECK(tiny.create_buffer(129,&none)==ResourceStatus::out_of_budget);
    CHECK(none==0);
    CHECK(tiny.create_buffer(64,&none)==ResourceStatus::ok);
    CHECK(tiny.write_buffer(none,64,ground.data(),1)==ResourceStatus::out_of_bounds);
    CHECK(tiny.destroy_buffer(none)==ResourceStatus::ok);

    std::ofstream color(argv[1],std::ios::binary);
    std::ofstream depth(argv[2],std::ios::binary);
    CHECK(color.is_open() && depth.is_open());
    color.write(reinterpret_cast<const char*>(observed.rgba.data()),
                static_cast<std::streamsize>(observed.rgba.size()));
    depth.write(reinterpret_cast<const char*>(observed.depth.data()),
                static_cast<std::streamsize>(observed.depth.size()*sizeof(float)));
    CHECK(static_cast<bool>(color) && static_cast<bool>(depth));
    std::cout << "ARE_PREDEVICE_REAL_CPP_RASTER_PASS "
              << counters.candidate_samples << ' '
              << counters.covered_samples << ' '
              << counters.shaded_samples << '\\n';
    return 0;
}
