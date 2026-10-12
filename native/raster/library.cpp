#include "core.hpp"
#if defined(_WIN32)
#define ARE_EXPORT extern "C" __declspec(dllexport)
#else
#define ARE_EXPORT extern "C" __attribute__((visibility("default")))
#endif
ARE_EXPORT unsigned are_raster_abi() { return 1; }
ARE_EXPORT int are_raster_draw(const double* packed,std::size_t cells,std::size_t count,
                              int width,int height,std::uint8_t* rgba,std::size_t rgba_bytes,
                              float* depth,std::size_t depth_cells,std::uint64_t* counts,std::size_t count_cells) {
    return are::raster::draw(packed,cells,count,width,height,rgba,rgba_bytes,depth,depth_cells,counts,count_cells);
}
