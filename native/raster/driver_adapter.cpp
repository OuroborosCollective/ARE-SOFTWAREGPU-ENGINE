// OuroborosCollective. Repository license applies.
#include "driver_adapter.hpp"
#include "core.hpp"
#include <cstdint>
#include <cstring>
#include <limits>
#include <type_traits>

#if defined(_WIN32)
#define ARE_DRIVER_EXPORT extern "C" __declspec(dllexport)
#else
#define ARE_DRIVER_EXPORT extern "C" __attribute__((visibility("default")))
#endif

namespace {
using are::driver::DrawV1;
using are::driver::CapabilitiesV1;

bool range_valid(const void* ptr, std::size_t bytes) {
    if (!ptr) return false;
    const auto first = reinterpret_cast<std::uintptr_t>(ptr);
    return bytes <= std::numeric_limits<std::uintptr_t>::max() - first;
}
bool intersects(const void* left, std::size_t lb, const void* right, std::size_t rb) {
    const auto l = reinterpret_cast<std::uintptr_t>(left);
    const auto r = reinterpret_cast<std::uintptr_t>(right);
    return l < r + rb && r < l + lb;
}
} // namespace

static_assert(std::is_standard_layout<DrawV1>::value, "C ABI layout required");
static_assert(std::is_standard_layout<CapabilitiesV1>::value, "C ABI layout required");
static_assert(sizeof(std::uintptr_t) >= sizeof(void*), "Pointer range check required");

ARE_DRIVER_EXPORT std::uint32_t are_driver_abi() { return are::driver::abi_version; }

ARE_DRIVER_EXPORT int are_driver_capabilities_v1(CapabilitiesV1* destination,
                                                   std::size_t destination_bytes) {
    if (!destination || destination_bytes != sizeof(CapabilitiesV1)) return are::driver::invalid_descriptor;
    const CapabilitiesV1 caps {
        static_cast<std::uint32_t>(sizeof(CapabilitiesV1)),
        are::driver::abi_version,
        are::driver::cpu_software,
        are::driver::packed_vertex_color,
        0u, 0u, 0u, // No SPIR-V, ICD, or WSI implementation.
        4096u, 4096u, 4194304u, 200000u
    };
    std::memcpy(destination, &caps, sizeof(caps));
    return 0;
}

// This exports an ARE-specific C ABI only. It never exports Vulkan vk* symbols.
// In particular, registering this library as an ICD would be incorrect.
ARE_DRIVER_EXPORT int are_driver_draw_v1(const DrawV1* request, std::size_t request_bytes) {
    if (!request || request_bytes != sizeof(DrawV1) ||
        request->struct_size != sizeof(DrawV1))
        return are::driver::invalid_descriptor;
    if (request->profile != are::driver::packed_vertex_color ||
        request->flags || request->reserved)
        return are::driver::unsupported_capability;

    if (request->width < 1 || request->height < 1 ||
        request->width > 4096 || request->height > 4096 ||
        static_cast<std::uint64_t>(request->width) * request->height > 4194304u ||
        request->count > are::raster::max_triangles)
        return are::raster::budget;

    const std::size_t pixels = static_cast<std::size_t>(request->width) *
                               static_cast<std::size_t>(request->height);
    if (request->cells != request->count * are::raster::stride ||
        request->rgba_bytes != pixels * 4u || request->depth_cells != pixels ||
        request->count_cells != 3u ||
        (request->count && !request->packed) ||
        !request->rgba || !request->depth || !request->counts)
        return are::raster::buffer;

    const std::size_t packed_bytes = request->cells * sizeof(double);
    const std::size_t color_bytes = request->rgba_bytes;
    const std::size_t depth_bytes = request->depth_cells * sizeof(float);
    const std::size_t counts_bytes = request->count_cells * sizeof(std::uint64_t);
    if (!range_valid(request->rgba, color_bytes) ||
        !range_valid(request->depth, depth_bytes) ||
        !range_valid(request->counts, counts_bytes) ||
        (packed_bytes && !range_valid(request->packed, packed_bytes)))
        return are::raster::buffer;

    if (intersects(request->rgba, color_bytes, request->depth, depth_bytes) ||
        intersects(request->rgba, color_bytes, request->counts, counts_bytes) ||
        intersects(request->depth, depth_bytes, request->counts, counts_bytes) ||
        (packed_bytes && (intersects(request->packed, packed_bytes, request->rgba, color_bytes) ||
                          intersects(request->packed, packed_bytes, request->depth, depth_bytes) ||
                          intersects(request->packed, packed_bytes, request->counts, counts_bytes))))
        return are::driver::buffer_overlap;

    return are::raster::draw(
        request->packed, request->cells, request->count,
        request->width, request->height,
        request->rgba, request->rgba_bytes, request->depth,
        request->depth_cells, request->counts, request->count_cells);
}
