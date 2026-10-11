// OuroborosCollective. Repository license applies.
#pragma once
#include <algorithm>
#include <array>
#include <cfenv>
#include <cfloat>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <vector>
#if defined(__SSE__)
#include <xmmintrin.h>
#endif
#if defined(__GNUC__) || defined(__clang__)
#define ARE_NOINLINE __attribute__((noinline))
#else
#define ARE_NOINLINE __declspec(noinline)
#endif
#ifdef __FAST_MATH__
#error Fast math violates ordered-f32-v1
#endif
static_assert(sizeof(float) == 4 && std::numeric_limits<float>::is_iec559,
              "IEEE binary32 is required");
static_assert(FLT_EVAL_METHOD == 0, "Excess precision violates ordered-f32-v1");

namespace are {
enum class Op { input, add, sub, mul };
struct Node { Op op; std::size_t a, b, cells; };
using Fused = bool (*)(const float* const*, float* const*);
struct Graph {
    std::vector<Node> nodes;
    std::vector<std::size_t> inputs, outputs;
    Fused fused;
    const char* sha256;
};
inline std::uint32_t bits(float value) {
    std::uint32_t result; std::memcpy(&result, &value, 4); return result;
}
inline std::uint32_t nonfinite(float value) {
    return (bits(value) & 0x7f800000u) == 0x7f800000u;
}
inline void require_environment() {
    if (std::fegetround() != FE_TONEAREST) throw std::runtime_error("ROUNDING_MODE");
#if defined(__SSE__)
    if ((_mm_getcsr() & ((1u << 15) | (1u << 6))) != 0)
        throw std::runtime_error("FLUSH_TO_ZERO");
#endif
}
struct Counts { std::size_t changed = 0, executed = 0; };

// Owns all buffers. Input memory is never retained. No allocation or Python
// callback is needed during evaluate(). Invalid frames cannot commit state.
class Engine {
    const Graph& graph_;
    std::vector<std::vector<float>> values_, staging_;
    std::vector<std::size_t> offsets_;
    std::vector<const float*> input_ptrs_;
    std::vector<float*> output_ptrs_;
    bool initialized_ = false;
    const bool incremental_;
    std::size_t input_cells_ = 0;
public:
    explicit Engine(const Graph& graph, bool incremental) : graph_(graph), incremental_(incremental) {
        if (graph.nodes.empty() || graph.nodes.size() > 128 || !graph.fused ||
            graph.outputs.empty()) throw std::runtime_error("GRAPH_SCHEMA");
        std::size_t total = 0;
        std::vector<std::size_t> expected_inputs;
        for (std::size_t i = 0; i < graph.nodes.size(); ++i) {
            const auto& n = graph.nodes[i];
            if (!n.cells || n.cells > 1048576 || total > 1048576 - n.cells)
                throw std::runtime_error("GRAPH_BUDGET");
            total += n.cells;
            if (n.op == Op::input) expected_inputs.push_back(i);
            else if ((n.op != Op::add && n.op != Op::sub && n.op != Op::mul) ||
                     n.a >= i || n.b >= i || graph.nodes[n.a].cells != n.cells ||
                     graph.nodes[n.b].cells != n.cells)
                throw std::runtime_error("GRAPH_DEPENDENCY");
            values_.emplace_back(n.cells); staging_.emplace_back(n.cells);
        }
        if (expected_inputs != graph.inputs) throw std::runtime_error("GRAPH_INPUTS");
        auto outputs = graph.outputs;
        std::sort(outputs.begin(), outputs.end());
        if (outputs.back() >= graph.nodes.size() ||
            std::adjacent_find(outputs.begin(), outputs.end()) != outputs.end())
            throw std::runtime_error("GRAPH_OUTPUTS");
        for (auto id : graph.inputs) {
            offsets_.push_back(input_cells_); input_cells_ += graph.nodes[id].cells;
            input_ptrs_.push_back(nullptr);
        }
        for (auto id : graph.outputs) output_ptrs_.push_back(staging_[id].data());
        require_environment();
    }
    std::size_t input_cells() const { return input_cells_; }
    const std::vector<float>& output(std::size_t index) const {
        if (!initialized_) throw std::runtime_error("NO_VALID_FRAME");
        return values_.at(graph_.outputs.at(index));
    }
    ARE_NOINLINE Counts evaluate(const std::vector<float>& frame) {
        require_environment();
        if (frame.size() != input_cells_) throw std::runtime_error("INPUT_SIZE");
        std::array<bool, 128> dirty{};
        Counts counts;
        for (std::size_t j = 0; j < graph_.inputs.size(); ++j) {
            auto id = graph_.inputs[j]; const float* input = frame.data() + offsets_[j];
            input_ptrs_[j] = input;
            dirty[id] = !initialized_ || std::memcmp(input, values_[id].data(),
                                                   values_[id].size() * 4) != 0;
            counts.changed += dirty[id];
            if (dirty[id]) {
                std::uint32_t invalid = 0;
                for (std::size_t k=0; k<values_[id].size(); ++k) {
                    const float value = input[k];
                    staging_[id][k] = value;
                    invalid |= nonfinite(value);
                }
                if (invalid) throw std::runtime_error("NONFINITE_INPUT");
            }
        }
        if (incremental_) {
            for (std::size_t id = 0; id < graph_.nodes.size(); ++id) {
                const auto& n = graph_.nodes[id];
                if (n.op == Op::input) continue;
                dirty[id] = !initialized_ || dirty[n.a] || dirty[n.b];
                if (!dirty[id]) continue;
                ++counts.executed;
                const auto& a = dirty[n.a] ? staging_[n.a] : values_[n.a];
                const auto& b = dirty[n.b] ? staging_[n.b] : values_[n.b];
                auto& out = staging_[id];
                // Dispatch once per array, not once per cell.
                if (n.op == Op::add) for (std::size_t k=0; k<n.cells; ++k) out[k]=a[k]+b[k];
                else if (n.op == Op::sub) for (std::size_t k=0; k<n.cells; ++k) out[k]=a[k]-b[k];
                else for (std::size_t k=0; k<n.cells; ++k) out[k]=a[k]*b[k];
                std::uint32_t invalid = 0;
                for (float value : out) invalid |= nonfinite(value);
                if (invalid) throw std::runtime_error("NONFINITE_RESULT");
            }
        } else {
            for (std::size_t j=0; j<graph_.outputs.size(); ++j)
                output_ptrs_[j] = staging_[graph_.outputs[j]].data();
            if (!graph_.fused(input_ptrs_.data(), output_ptrs_.data()))
                throw std::runtime_error("NONFINITE_RESULT");
            counts.executed = graph_.nodes.size() - graph_.inputs.size();
            for (auto id : graph_.outputs) dirty[id] = true;
        }
        for (std::size_t id=0; id<graph_.nodes.size(); ++id)
            if (dirty[id]) values_[id].swap(staging_[id]);
        initialized_ = true;
        return counts;
    }
};
} // namespace are
