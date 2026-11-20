// Offline framing probe for the UNRATIFIED GLB version 3 draft (glTF 2.1 draft).
//
// Independent C++17 counterpart of tools/gltf21_glb3_sandbox.py::_frame. It is a
// differential test oracle only: no renderer, importer or default GLB 2.0 path
// includes this file. Every field is decoded byte by byte, so the result does
// not depend on host endianness, and untrusted 64-bit lengths are compared
// against the remaining size instead of being added to an offset.
//
// Usage: glb3_container_probe <bundle>
// Bundle: "AREGLB3F" | u32le count | count x (u32le length | bytes)
// Output: one line per case, "A <canonical framing>" or "R <CODE>".
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

namespace {

constexpr std::uint64_t kMaxSourceBytes = 64ull * 1024ull * 1024ull;
constexpr std::uint64_t kMaxJsonBytes = 4ull * 1024ull * 1024ull;
constexpr std::uint64_t kMaxBundleBytes = 256ull * 1024ull * 1024ull;
constexpr std::size_t kMaxChunks = 64;
constexpr std::uint32_t kJsonChunk = 0x4E4F534Au;
constexpr std::uint64_t kFileHeader = 16;
constexpr std::uint64_t kChunkHeader = 16;

struct Chunk {
    std::uint32_t type;
    std::uint32_t encoding;
    std::uint64_t offset;
    std::uint64_t length;
};

std::uint32_t u32le(const unsigned char* p) {
    return static_cast<std::uint32_t>(p[0]) |
           (static_cast<std::uint32_t>(p[1]) << 8) |
           (static_cast<std::uint32_t>(p[2]) << 16) |
           (static_cast<std::uint32_t>(p[3]) << 24);
}

std::uint64_t u64le(const unsigned char* p) {
    return static_cast<std::uint64_t>(u32le(p)) |
           (static_cast<std::uint64_t>(u32le(p + 4)) << 32);
}

bool starts_with(const unsigned char* p, std::uint64_t n, const char* signature,
                 std::size_t length) {
    return n >= length && std::memcmp(p, signature, length) == 0;
}

// Strict RFC 3629: no overlong forms, no surrogates, nothing above U+10FFFF.
bool valid_utf8(const unsigned char* s, std::uint64_t n) {
    std::uint64_t i = 0;
    while (i < n) {
        const unsigned char c = s[i];
        if (c < 0x80) {
            ++i;
            continue;
        }
        std::uint64_t extra = 0;
        unsigned char low = 0x80, high = 0xBF;
        if (c >= 0xC2 && c <= 0xDF) {
            extra = 1;
        } else if (c == 0xE0) {
            extra = 2;
            low = 0xA0;
        } else if ((c >= 0xE1 && c <= 0xEC) || c == 0xEE || c == 0xEF) {
            extra = 2;
        } else if (c == 0xED) {
            extra = 2;
            high = 0x9F;
        } else if (c == 0xF0) {
            extra = 3;
            low = 0x90;
        } else if (c >= 0xF1 && c <= 0xF3) {
            extra = 3;
        } else if (c == 0xF4) {
            extra = 3;
            high = 0x8F;
        } else {
            return false;
        }
        if (n - i - 1 < extra) return false;
        if (s[i + 1] < low || s[i + 1] > high) return false;
        for (std::uint64_t k = 2; k <= extra; ++k) {
            if ((s[i + k] & 0xC0) != 0x80) return false;
        }
        i += extra + 1;
    }
    return true;
}

std::string hex8(std::uint32_t value) {
    static const char digits[] = "0123456789abcdef";
    std::string text(8, '0');
    for (int i = 7; i >= 0; --i) {
        text[static_cast<std::size_t>(i)] = digits[value & 0xFu];
        value >>= 4;
    }
    return text;
}

std::string inspect(const unsigned char* p, std::uint64_t size) {
    if (size > kMaxSourceBytes) return "R SOURCE_BUDGET";
    if (starts_with(p, size, "\x1f\x8b", 2) || starts_with(p, size, "\x28\xb5\x2f\xfd", 4) ||
        starts_with(p, size, "\xfd" "7zXZ\x00", 6) || starts_with(p, size, "BZh", 3) ||
        starts_with(p, size, "PK\x03\x04", 4)) {
        return "R COMPRESSED_INPUT_REFUSED";
    }
    if (size < 4) return "R HEADER_TRUNCATED";
    if (std::memcmp(p, "glTF", 4) != 0) return "R MAGIC";
    if (size < 8) return "R HEADER_TRUNCATED";
    const std::uint32_t version = u32le(p + 4);
    if (version == 2u) return "R VERSION_2_OUT_OF_SCOPE";
    if (version == 0x02000000u || version == 0x03000000u) return "R BIG_ENDIAN_REFUSED";
    if (version != 3u) return "R VERSION_UNSUPPORTED";
    if (size < kFileHeader) return "R HEADER_TRUNCATED";
    const std::uint64_t declared = u64le(p + 8);
    if ((declared >> 63) != 0) return "R LENGTH_MSB";
    if (declared != size) return "R LENGTH_MISMATCH";

    std::vector<Chunk> chunks;
    std::uint64_t nonzero_padding = 0, trailing_padding = 0;
    std::uint64_t position = kFileHeader;
    while (position < size) {
        if (size - position < kChunkHeader) return "R CHUNK_HEADER_TRUNCATED";
        const std::uint32_t type = u32le(p + position);
        const std::uint32_t encoding = u32le(p + position + 4);
        const std::uint64_t length = u64le(p + position + 8);
        if ((length >> 63) != 0) return "R CHUNK_LENGTH_MSB";
        const std::uint64_t payload = position + kChunkHeader;
        if (length > size - payload) return "R CHUNK_LENGTH_OVERFLOW";
        if (chunks.size() >= kMaxChunks) return "R CHUNK_BUDGET";
        if (encoding != 0u) return "R CHUNK_ENCODING_REFUSED";
        chunks.push_back(Chunk{type, encoding, payload, length});
        const std::uint64_t end = payload + length;  // <= size, cannot wrap.
        if (end == size) break;
        const std::uint64_t following = end + ((8u - (end & 7u)) & 7u);
        if (following > size) return "R TRAILING_BYTES";
        for (std::uint64_t i = end; i < following; ++i) {
            if (p[i] != 0) ++nonzero_padding;
        }
        if (following == size) trailing_padding = following - end;
        position = following;
    }
    if (chunks.empty()) return "R NO_CHUNKS";
    std::size_t main_json = chunks.size();
    for (std::size_t i = 0; i < chunks.size(); ++i) {
        if (chunks[i].type == kJsonChunk) {
            main_json = i;
            break;
        }
    }
    if (main_json == chunks.size()) return "R JSON_CHUNK_MISSING";
    const Chunk& json = chunks[main_json];
    if (json.length > kMaxJsonBytes) return "R JSON_BUDGET";
    const unsigned char* text = p + json.offset;
    if (json.length >= 3 && text[0] == 0xEF && text[1] == 0xBB && text[2] == 0xBF) {
        return "R JSON_BOM";
    }
    if (!valid_utf8(text, json.length)) return "R JSON_UTF8";

    std::string line = "A glb3;chunks=" + std::to_string(chunks.size()) +
                       ";main_json=" + std::to_string(main_json) +
                       ";pad_nonzero=" + std::to_string(nonzero_padding) +
                       ";trailing_pad=" + std::to_string(trailing_padding);
    for (const Chunk& chunk : chunks) {
        line += ";" + hex8(chunk.type) + ":" + std::to_string(chunk.encoding) + ":" +
                std::to_string(chunk.offset) + ":" + std::to_string(chunk.length);
    }
    return line;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fputs("usage: glb3_container_probe <bundle>\n", stderr);
        return 2;
    }
    std::ifstream input(argv[1], std::ios::binary | std::ios::ate);
    if (!input) {
        std::fputs("GLB3_PROBE_BUNDLE_UNREADABLE\n", stderr);
        return 3;
    }
    const std::streamoff measured = input.tellg();
    if (measured < 12 || static_cast<std::uint64_t>(measured) > kMaxBundleBytes) {
        std::fputs("GLB3_PROBE_BUNDLE_SIZE\n", stderr);
        return 3;
    }
    std::vector<unsigned char> bundle(static_cast<std::size_t>(measured));
    input.seekg(0);
    if (!input.read(reinterpret_cast<char*>(bundle.data()), measured)) {
        std::fputs("GLB3_PROBE_BUNDLE_UNREADABLE\n", stderr);
        return 3;
    }
    const std::uint64_t total = bundle.size();
    if (std::memcmp(bundle.data(), "AREGLB3F", 8) != 0) {
        std::fputs("GLB3_PROBE_BUNDLE_MAGIC\n", stderr);
        return 3;
    }
    const std::uint32_t count = u32le(bundle.data() + 8);
    std::uint64_t position = 12;
    std::string output = "GLB3_PROBE_BEGIN " + std::to_string(count) + "\n";
    for (std::uint32_t index = 0; index < count; ++index) {
        if (total - position < 4) {
            std::fputs("GLB3_PROBE_BUNDLE_TRUNCATED\n", stderr);
            return 3;
        }
        const std::uint64_t length = u32le(bundle.data() + position);
        position += 4;
        if (length > total - position) {
            std::fputs("GLB3_PROBE_BUNDLE_TRUNCATED\n", stderr);
            return 3;
        }
        output += inspect(bundle.data() + position, length);
        output += "\n";
        position += length;
    }
    if (position != total) {
        std::fputs("GLB3_PROBE_BUNDLE_TRAILING\n", stderr);
        return 3;
    }
    output += "GLB3_PROBE_END\n";
    std::fwrite(output.data(), 1, output.size(), stdout);
    return std::fflush(stdout) == 0 ? 0 : 4;
}
