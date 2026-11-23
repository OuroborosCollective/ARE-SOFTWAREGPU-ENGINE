// OuroborosCollective - resource admission for future Vulkan VkDevice.
// Real C++17 ARE raster in the execution path; NOT an exported Vulkan device.
// Single-threaded exclusive ownership. No wall-clock, random or fake GPU state.
#pragma once
#include "../raster/driver_adapter.hpp"
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <unordered_map>
#include <utility>
#include <vector>

extern "C" int are_driver_draw_v1(const are::driver::DrawV1*, std::size_t);

namespace are::vulkan::predevice {

using ResourceHandle = std::uint64_t;
enum class ResourceStatus : std::uint32_t {
    ok = 0, invalid_handle, out_of_bounds, out_of_budget,
    invalid_descriptor, native_rejected
};
struct DrawRecord {
    ResourceHandle packed_buffer = 0;
    std::size_t offset = 0;
    std::size_t triangle_count = 0;
};
struct RasterCounters {
    std::uint64_t candidate_samples = 0;
    std::uint64_t covered_samples = 0;
    std::uint64_t shaded_samples = 0;
    bool operator==(const RasterCounters& other) const {
        return candidate_samples == other.candidate_samples &&
               covered_samples == other.covered_samples &&
               shaded_samples == other.shaded_samples;
    }
};
struct ImageSnapshot {
    std::vector<std::uint8_t> rgba;
    std::vector<float> depth;
};

class ResourceQueue final {
    struct Buffer { std::vector<std::uint8_t> bytes; };
    struct Image {
        std::uint32_t width = 0, height = 0;
        ImageSnapshot image;
    };
    const std::size_t budget_;
    std::size_t allocated_ = 0;
    ResourceHandle next_ = 1;
    std::unordered_map<ResourceHandle, Buffer> buffers_;
    std::unordered_map<ResourceHandle, Image> images_;
    static constexpr std::size_t max_records = 256;
    static constexpr std::size_t max_draw_triangles = 200000;
    static constexpr std::size_t stride_bytes = 23 * sizeof(double);
    static constexpr std::size_t max_pixels = 4194304;

    bool room(std::size_t bytes) const {
        return bytes <= budget_ && allocated_ <= budget_ - bytes;
    }
    ResourceHandle new_handle() {
        // Never recycle IDs: destroyed buffer handles stay invalid.
        if (next_ == std::numeric_limits<ResourceHandle>::max()) return 0;
        return next_++;
    }
public:
    explicit ResourceQueue(std::size_t byte_budget) : budget_(byte_budget) {}
    ResourceQueue(const ResourceQueue&) = delete;
    ResourceQueue& operator=(const ResourceQueue&) = delete;

    ResourceStatus create_buffer(std::size_t bytes, ResourceHandle* result) {
        if (!result) return ResourceStatus::invalid_descriptor;
        *result = 0;
        if (!bytes || bytes > 64ull*1024*1024) return ResourceStatus::out_of_budget;
        if (!room(bytes)) return ResourceStatus::out_of_budget;
        try {
            auto data = std::vector<std::uint8_t>(bytes);
            const auto id = new_handle();
            if (!id) return ResourceStatus::out_of_budget;
            buffers_.emplace(id, Buffer{std::move(data)});
            allocated_ += bytes;
            *result = id;
            return ResourceStatus::ok;
        } catch (const std::bad_alloc&) {
            return ResourceStatus::out_of_budget;
        }
    }
    ResourceStatus destroy_buffer(ResourceHandle handle) {
        const auto item = buffers_.find(handle);
        if (item == buffers_.end()) return ResourceStatus::invalid_handle;
        allocated_ -= item->second.bytes.size();
        buffers_.erase(item);
        return ResourceStatus::ok;
    }
    ResourceStatus write_buffer(ResourceHandle handle, std::size_t offset,
                                const void* source, std::size_t bytes) {
        const auto item = buffers_.find(handle);
        if (item == buffers_.end()) return ResourceStatus::invalid_handle;
        if ((!source && bytes) || offset > item->second.bytes.size() ||
            bytes > item->second.bytes.size() - offset)
            return ResourceStatus::out_of_bounds;
        if (bytes) std::memcpy(item->second.bytes.data() + offset, source, bytes);
        return ResourceStatus::ok;
    }
    ResourceStatus create_image(std::uint32_t width, std::uint32_t height,
                                ResourceHandle* result) {
        if (!result) return ResourceStatus::invalid_descriptor;
        *result = 0;
        if (!width || !height || width > 4096 || height > 4096 ||
            static_cast<std::uint64_t>(width)*height > max_pixels)
            return ResourceStatus::out_of_budget;
        const auto pixels = std::size_t(width)*height;
        const auto bytes = pixels*(4u + sizeof(float));
        if (!room(bytes)) return ResourceStatus::out_of_budget;
        try {
            Image value;
            value.width = width;
            value.height = height;
            value.image.rgba.assign(pixels*4,0);
            value.image.depth.assign(pixels,1.0f);
            const auto id = new_handle();
            if (!id) return ResourceStatus::out_of_budget;
            images_.emplace(id,std::move(value));
            allocated_ += bytes;
            *result = id;
            return ResourceStatus::ok;
        } catch (const std::bad_alloc&) {
            return ResourceStatus::out_of_budget;
        }
    }
    ResourceStatus destroy_image(ResourceHandle handle) {
        auto it = images_.find(handle);
        if (it == images_.end()) return ResourceStatus::invalid_handle;
        allocated_ -= it->second.image.rgba.size() +
                      it->second.image.depth.size()*sizeof(float);
        images_.erase(it);
        return ResourceStatus::ok;
    }
    ResourceStatus snapshot(ResourceHandle handle, ImageSnapshot* target) const {
        if (!target) return ResourceStatus::invalid_descriptor;
        auto it = images_.find(handle);
        if (it == images_.end()) return ResourceStatus::invalid_handle;
        try { *target = it->second.image; } catch (const std::bad_alloc&) {
            return ResourceStatus::out_of_budget;
        }
        return ResourceStatus::ok;
    }

    ResourceStatus submit(ResourceHandle image_handle, const std::vector<DrawRecord>& records,
                          RasterCounters* output) {
        if (!output) return ResourceStatus::invalid_descriptor;
        auto image_it = images_.find(image_handle);
        if (image_it == images_.end()) return ResourceStatus::invalid_handle;
        if (records.empty() || records.size() > max_records)
            return ResourceStatus::invalid_descriptor;
        std::size_t triangles = 0;
        for (const auto& record : records) {
            auto it = buffers_.find(record.packed_buffer);
            if (it == buffers_.end()) return ResourceStatus::invalid_handle;
            if (record.triangle_count > max_draw_triangles ||
                triangles > max_draw_triangles - record.triangle_count)
                return ResourceStatus::out_of_budget;
            triangles += record.triangle_count;
            const std::size_t length = it->second.bytes.size();
            if (record.offset % alignof(double) != 0 ||
                record.offset > length ||
                record.triangle_count > (length-record.offset)/stride_bytes)
                return ResourceStatus::out_of_bounds;
        }

        // Candidate state is owned and private until ALL real native draws
        // complete. A late invalid geometry record cannot partially commit.
        ImageSnapshot staged;
        try { staged = image_it->second.image; } catch (const std::bad_alloc&) {
            return ResourceStatus::out_of_budget;
        }
        RasterCounters totals{};
        const auto width = image_it->second.width, height = image_it->second.height;
        for (const auto& record : records) {
            const auto& source = buffers_.find(record.packed_buffer)->second.bytes;
            std::vector<double> aligned(record.triangle_count*23);
            if (!aligned.empty()) std::memcpy(aligned.data(),source.data()+record.offset,
                                              aligned.size()*sizeof(double));
            std::array<std::uint64_t,3> counts{};
            are::driver::DrawV1 desc{};
            desc.struct_size = static_cast<std::uint32_t>(sizeof(desc));
            desc.profile = are::driver::packed_vertex_color;
            desc.packed = aligned.data();
            desc.cells = aligned.size();
            desc.count = record.triangle_count;
            desc.width = static_cast<std::int32_t>(width);
            desc.height = static_cast<std::int32_t>(height);
            desc.rgba = staged.rgba.data();
            desc.rgba_bytes = staged.rgba.size();
            desc.depth = staged.depth.data();
            desc.depth_cells = staged.depth.size();
            desc.counts = counts.data();
            desc.count_cells = counts.size();
            if (are_driver_draw_v1(&desc,sizeof(desc)) != 0)
                return ResourceStatus::native_rejected;
            totals.candidate_samples += counts[0];
            totals.covered_samples += counts[1];
            totals.shaded_samples += counts[2];
        }
        // No expected allocation: swap owned storage into the live image.
        image_it->second.image.rgba.swap(staged.rgba);
        image_it->second.image.depth.swap(staged.depth);
        *output = totals;
        return ResourceStatus::ok;
    }
};

} // namespace are::vulkan::predevice
