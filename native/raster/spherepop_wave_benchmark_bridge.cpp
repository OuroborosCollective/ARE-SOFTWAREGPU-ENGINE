// OuroborosCollective. Repository license applies.
// Research-only C ABI to time the *actual merged* radial C++17 wave after
// existing SoftwareRasterizer::draw_mesh. Not used by production runtime.
#include "spherepop_cag_radial_wave.hpp"
#include <cstddef>
#include <cstdint>
#include <exception>

struct WaveBenchmarkMetrics {
    std::uint64_t finalized;
    std::uint64_t refused;
    std::uint64_t tinted;
    std::uint64_t fingerprint;
};

extern "C" unsigned are_wave_benchmark_abi() noexcept { return 1u; }

extern "C" int are_wave_benchmark_apply(
    std::uint8_t* rgba, std::size_t bytes,
    const float* depth, std::size_t depth_cells,
    const std::uint32_t* owners, std::size_t owner_cells,
    int width, int height, int cag_x, int cag_y,
    double vx, double vy, double vz,
    double wave_speed, double artistic_gain,
    WaveBenchmarkMetrics* output) noexcept {
    if(!output) return 1;
    try {
        auto receipt=are::raster::experimental::render_radial_cag_spherepop(
            rgba, bytes, depth, depth_cells, owners, owner_cells, width, height,
            cag_x, cag_y, {vx,vy,vz}, wave_speed, artistic_gain);
        output->finalized=static_cast<std::uint64_t>(receipt.finalized.size());
        output->refused=receipt.refusals;
        output->tinted=static_cast<std::uint64_t>(receipt.tinted_pixels);
        output->fingerprint=receipt.event_fingerprint;
        return 0;
    } catch(const std::exception&) {
        return 2;
    } catch(...) {
        return 3;
    }
}
