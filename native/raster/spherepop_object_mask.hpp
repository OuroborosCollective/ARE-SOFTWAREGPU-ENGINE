// OuroborosCollective. Repository license applies.
// Experimental, opt-in projection boundary; never alters the production raster core.
// SpherePop-inspired histories, not a claim of full upstream SpherePop semantics.
#pragma once
#include "spherepop_doppler_profile.hpp"
#include <cstddef>
#include <cstdint>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace are::raster::experimental {

// Called only after a successful draw. Before/after must be copies from the
// SAME framebuffer. A strictly nearer depth writes the owner; a tie keeps its
// previous owner, matching the renderer's first-submission depth contract.
// All source arrays must be disjoint from the writable owner buffer.
inline std::size_t label_depth_winners(const float* before, const float* after,
                                       std::size_t cells, std::uint32_t object_id,
                                       std::uint32_t* owners, std::size_t owner_cells) {
    if (!before || !after || !owners || !object_id || !cells ||
        cells > 4194304 || owner_cells != cells)
        throw std::invalid_argument("SPHEREPOP_OBJECT_MASK_BUFFER_INVALID");
    // Validate the entire transition before touching a single owner.
    for (std::size_t i=0; i<cells; ++i) {
        if (!std::isfinite(before[i]) || !std::isfinite(after[i]))
            throw std::invalid_argument("SPHEREPOP_OBJECT_MASK_DEPTH_INVALID");
        if (after[i] > before[i])
            throw std::invalid_argument("SPHEREPOP_OBJECT_MASK_DEPTH_NONMONOTONE");
    }
    std::size_t changed=0;
    for (std::size_t i=0; i<cells; ++i) {
        if (after[i] < before[i]) {
            owners[i]=object_id;
            ++changed;
        }
    }
    return changed;
}

// Only pixels owned by the target object can be recolored. No object has
// implicit authority over all pixels, even if the object was drawn last.
// Reuse the audited single-object effect, including prevalidation, history
// staging and alpha/depth invariants, via an isolated synthetic depth mask.
// This research implementation allocates O(pixels) temporary float32 memory;
// performance and activation require separate end-to-end measurement.
inline Result apply_object_masked(std::uint8_t* rgba, std::size_t rgba_bytes,
                                  const float* depth, std::size_t depth_cells,
                                  const std::uint32_t* owners, std::size_t owner_cells,
                                  int width, int height,
                                  Vec3 source, Vec3 observer, Vec3 source_velocity,
                                  double wave_speed, double artistic_gain,
                                  std::uint32_t object_id, History* history=nullptr) {
    if (width<=0 || height<=0 || width>2048 || height>2048 ||
        static_cast<std::uint64_t>(width)*height>4194304 ||
        !rgba || !depth || !owners || !object_id ||
        depth_cells!=static_cast<std::size_t>(width)*height ||
        rgba_bytes!=depth_cells*4 || owner_cells!=depth_cells)
        throw std::invalid_argument("SPHEREPOP_OBJECT_MASK_BUFFER_INVALID");
    // Validate *all* depth values: masking an invalid non-target depth must
    // never hide corrupt input from the original fail-closed admission gate.
    for (std::size_t i=0; i<depth_cells; ++i)
        if (!std::isfinite(depth[i]))
            throw std::invalid_argument("DOPPLER_DEPTH_INVALID");
    std::vector<float> isolated(depth,depth+depth_cells);
    for (std::size_t i=0; i<depth_cells; ++i)
        if (owners[i] != object_id) isolated[i]=1.0f;
    return apply_single_object(rgba,rgba_bytes,isolated.data(),isolated.size(),
                               width,height,source,observer,source_velocity,
                               wave_speed,artistic_gain,object_id,history);
}

} // namespace are::raster::experimental
