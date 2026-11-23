// OuroborosCollective. Repository license applies.
// ARE driver adaptation ABI v1: CPU-only, synchronous, headless, not a Vulkan ICD.
#pragma once
#include <cstddef>
#include <cstdint>

namespace are::driver {
inline constexpr std::uint32_t abi_version = 1u;
inline constexpr std::uint32_t cpu_software = 1u;
inline constexpr std::uint32_t packed_vertex_color = 1u;
inline constexpr int unsupported_capability = 7;
inline constexpr int buffer_overlap = 8;
inline constexpr int invalid_descriptor = 6;

struct CapabilitiesV1 {
    std::uint32_t struct_size;
    std::uint32_t abi_version;
    std::uint32_t device_kind;
    std::uint32_t profile_bits;
    std::uint32_t supports_spirv;
    std::uint32_t supports_vulkan_icd;
    std::uint32_t supports_wsi;
    std::uint32_t max_width;
    std::uint32_t max_height;
    std::uint32_t max_pixels;
    std::uint32_t max_triangles;
};

// No ownership transfer. Buffers must remain alive, disjoint, aligned and
// exclusively held by the calling process until return. The boundary does not
// validate arbitrary untrusted pointers or launch a background GPU thread.
struct DrawV1 {
    std::uint32_t struct_size;
    std::uint32_t profile;
    std::uint32_t flags;
    std::uint32_t reserved;
    const double* packed;
    std::size_t cells;
    std::size_t count;
    std::int32_t width;
    std::int32_t height;
    std::uint8_t* rgba;
    std::size_t rgba_bytes;
    float* depth;
    std::size_t depth_cells;
    std::uint64_t* counts;
    std::size_t count_cells;
};
} // namespace are::driver
