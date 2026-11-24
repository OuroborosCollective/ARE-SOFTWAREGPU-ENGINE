// Native XCB backend for a *real* ARE VkSurfaceKHR / swapchain implementation.
// Does not create a surrogate window: uses the exact client-owned connection
// and XCB window from VkXcbSurfaceCreateInfoKHR. Caller retains their lifetime.
#include <xcb/xcb.h>
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <vector>

namespace {
constexpr std::uint64_t kMaxPixels = 4194304;
bool extent(std::uint32_t w, std::uint32_t h) {
    return w && h && w <= 4096 && h <= 4096 &&
           std::uint64_t(w) * h <= kMaxPixels;
}
bool supported_visual(xcb_connection_t* conn, xcb_visualid_t vid) {
    if (!conn || xcb_connection_has_error(conn)) return false;
    const auto* setup = xcb_get_setup(conn);
    if (!setup || setup->image_byte_order != XCB_IMAGE_ORDER_LSB_FIRST) return false;
    bool fmt = false;
    for (auto it = xcb_setup_pixmap_formats_iterator(setup); it.rem;
         xcb_format_next(&it)) {
        if (it.data->depth == 24 && it.data->bits_per_pixel == 32 &&
            it.data->scanline_pad == 32) fmt = true;
    }
    if (!fmt) return false;
    for (auto screen = xcb_setup_roots_iterator(setup); screen.rem;
         xcb_screen_next(&screen)) {
        for (auto depth = xcb_screen_allowed_depths_iterator(screen.data); depth.rem;
             xcb_depth_next(&depth)) {
            if (depth.data->depth != 24) continue;
            for (auto visual = xcb_depth_visuals_iterator(depth.data); visual.rem;
                 xcb_visualtype_next(&visual)) {
                const auto& v = *visual.data;
                if (v.visual_id == vid && v._class == XCB_VISUAL_CLASS_TRUE_COLOR &&
                    v.red_mask == 0x00ff0000 && v.green_mask == 0x0000ff00 &&
                    v.blue_mask == 0x000000ff) return true;
            }
        }
    }
    return false;
}
bool checked(xcb_connection_t* conn, xcb_void_cookie_t cookie) {
    auto* error = xcb_request_check(conn, cookie);
    if (!error) return true;
    std::free(error);
    return false;
}
}

extern "C" int are_xcb_visual_supported(void* connection, std::uint32_t visual) {
    return supported_visual(static_cast<xcb_connection_t*>(connection), visual) ? 1 : 0;
}

extern "C" int are_xcb_probe_surface(
    void* connection, std::uint32_t window, std::uint32_t* w,
    std::uint32_t* h, std::uint32_t* visual_id) {
    auto* conn = static_cast<xcb_connection_t*>(connection);
    if (!conn || !window || !w || !h || !visual_id || xcb_connection_has_error(conn)) return 1;
    xcb_generic_error_t* error = nullptr;
    auto* geometry = xcb_get_geometry_reply(conn, xcb_get_geometry(conn, window), &error);
    if (error) std::free(error);
    if (!geometry) return 2;
    const auto width = geometry->width, height = geometry->height;
    const auto depth = geometry->depth;
    std::free(geometry);
    error = nullptr;
    auto* attrs = xcb_get_window_attributes_reply(conn,
        xcb_get_window_attributes(conn, window), &error);
    if (error) std::free(error);
    if (!attrs) return 2;
    const auto visual = attrs->visual;
    std::free(attrs);
    if (!extent(width, height) || depth != 24 ||
        !supported_visual(conn, visual)) return 3;
    *w = width;
    *h = height;
    *visual_id = visual;
    return 0;
}

extern "C" std::uint32_t are_xcb_open_gc(void* connection, std::uint32_t window) {
    auto* conn = static_cast<xcb_connection_t*>(connection);
    std::uint32_t w = 0, h = 0, visual = 0;
    if (are_xcb_probe_surface(conn, window, &w, &h, &visual)) return 0;
    const auto gc = xcb_generate_id(conn);
    const std::uint32_t values[] = {0};
    if (!checked(conn, xcb_create_gc_checked(conn, gc, window,
                                             XCB_GC_GRAPHICS_EXPOSURES, values)))
        return 0;
    return gc;
}

extern "C" void are_xcb_close_gc(void* connection, std::uint32_t gc) {
    auto* conn = static_cast<xcb_connection_t*>(connection);
    if (conn && gc && !xcb_connection_has_error(conn)) {
        xcb_free_gc(conn, gc);
        xcb_flush(conn);
    }
}

// 0 is success only after the real X11 window has been read back and every RGB
// byte matches the ARE VkImage. The exposed surface is depth-24/opaque only.
extern "C" int are_xcb_present_and_readback(
    void* connection, std::uint32_t window, std::uint32_t gc,
    const std::uint8_t* rgba, std::uint64_t length,
    std::uint32_t width, std::uint32_t height,
    std::uint8_t* observed, std::uint64_t observed_length) {
    auto* conn = static_cast<xcb_connection_t*>(connection);
    std::uint32_t actual_w = 0, actual_h = 0, actual_visual = 0;
    if (!gc || !rgba || !observed || !extent(width, height) ||
        length != std::uint64_t(width)*height*4 || observed_length != length) return 1;
    if (are_xcb_probe_surface(conn, window, &actual_w, &actual_h, &actual_visual))
        return 2;
    if (actual_w != width || actual_h != height) return 3;
    std::vector<std::uint8_t> bgr(static_cast<std::size_t>(length));
    for (std::size_t i=0; i<bgr.size(); i+=4) {
        bgr[i] = rgba[i+2];
        bgr[i+1] = rgba[i+1];
        bgr[i+2] = rgba[i];
        bgr[i+3] = 0;
    }
    const auto limit = xcb_get_maximum_request_length(conn);
    const auto header = sizeof(xcb_put_image_request_t)/4 +
                        (limit > UINT16_MAX);
    if (limit <= header || (limit-header)/width == 0) return 4;
    const auto rows_per_request = (limit-header)/width;
    const auto stride = width*4;
    for (std::uint32_t y=0; y<height;) {
        const auto rows = std::min<std::uint32_t>(static_cast<std::uint32_t>(rows_per_request), height-y);
        if (!checked(conn, xcb_put_image_checked(
                conn, XCB_IMAGE_FORMAT_Z_PIXMAP, window, gc,
                static_cast<std::uint16_t>(width),
                static_cast<std::uint16_t>(rows),
                0, static_cast<std::int16_t>(y), 0, 24,
                rows*stride, bgr.data()+std::size_t(y)*stride)))
            return 5;
        y+=rows;
    }
    if (xcb_flush(conn)<=0) return 6;
    xcb_generic_error_t* error=nullptr;
    auto* reply=xcb_get_image_reply(conn,
        xcb_get_image(conn,XCB_IMAGE_FORMAT_Z_PIXMAP,window,0,0,
                      static_cast<std::uint16_t>(width),
                      static_cast<std::uint16_t>(height),~0u),&error);
    if (error) std::free(error);
    if (!reply) return 7;
    const auto count=xcb_get_image_data_length(reply);
    const auto* pixels=xcb_get_image_data(reply);
    if (reply->depth!=24 || count!=static_cast<int>(length)) {
        std::free(reply);
        return 8;
    }
    for (std::size_t i=0;i<bgr.size();i+=4) {
        if (pixels[i]!=bgr[i] || pixels[i+1]!=bgr[i+1] || pixels[i+2]!=bgr[i+2]) {
            std::free(reply);
            return 9;
        }
        observed[i] = pixels[i+2];
        observed[i+1] = pixels[i+1];
        observed[i+2] = pixels[i];
        observed[i+3] = 255;
    }
    std::free(reply);
    return 0;
}
