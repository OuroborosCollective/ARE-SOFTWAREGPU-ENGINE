// X11/XCB presenter for the REAL ARE CPU framebuffer; not a Vulkan SurfaceKHR.
// Produces observable X11 pixels on an isolated X server, with readback.
// Must not advertise VK_KHR_surface, VK_KHR_xcb_surface or VK_KHR_swapchain.
#pragma once

#include <xcb/xcb.h>
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <vector>

namespace are::vulkan::prewsi {

enum class XcbStatus : std::uint32_t {
    ok = 0, invalid_extent, unavailable, unsupported_visual, rejected_request,
    invalid_payload, out_of_date, not_open
};

class XcbFramePresenter final {
    xcb_connection_t* conn_ = nullptr;
    xcb_window_t window_ = XCB_WINDOW_NONE;
    xcb_gcontext_t gc_ = XCB_NONE;
    std::uint32_t width_ = 0, height_ = 0;
    std::uint8_t depth_ = 0;
    std::uint32_t visual_ = 0;

    static bool extent(std::uint32_t width, std::uint32_t height) {
        return width > 0 && height > 0 && width <= 4096 && height <= 4096
            && std::uint64_t(width) * height <= 4194304;
    }
    bool checked(xcb_void_cookie_t cookie) {
        auto* error = xcb_request_check(conn_, cookie);
        if (!error) return true;
        std::free(error);
        return false;
    }
    bool current_extent() const {
        auto cookie = xcb_get_geometry(conn_, window_);
        auto* response = xcb_get_geometry_reply(conn_, cookie, nullptr);
        if (!response) return false;
        const bool match = response->width == width_ && response->height == height_;
        std::free(response);
        return match;
    }
public:
    XcbFramePresenter() = default;
    XcbFramePresenter(const XcbFramePresenter&) = delete;
    XcbFramePresenter& operator=(const XcbFramePresenter&) = delete;
    ~XcbFramePresenter() { close(); }

    XcbStatus open(std::uint32_t width, std::uint32_t height) {
        if (!extent(width,height)) return XcbStatus::invalid_extent;
        if (conn_) return XcbStatus::rejected_request;
        int screen_index = 0;
        conn_ = xcb_connect(nullptr, &screen_index);
        if (!conn_ || xcb_connection_has_error(conn_)) {
            close(); return XcbStatus::unavailable;
        }
        const auto* setup = xcb_get_setup(conn_);
        if (!setup || setup->image_byte_order != XCB_IMAGE_ORDER_LSB_FIRST) {
            close(); return XcbStatus::unsupported_visual;
        }
        auto screens = xcb_setup_roots_iterator(setup);
        while (screen_index-- > 0 && screens.rem) xcb_screen_next(&screens);
        if (!screens.rem || !screens.data) {
            close(); return XcbStatus::unavailable;
        }
        const auto* screen = screens.data;
        depth_ = screen->root_depth;
        visual_ = screen->root_visual;
        bool format_found = false;
        auto formats = xcb_setup_pixmap_formats_iterator(setup);
        for (;formats.rem; xcb_format_next(&formats)) {
            if (formats.data->depth == depth_ && formats.data->bits_per_pixel == 32
                && formats.data->scanline_pad == 32) {
                format_found = true; break;
            }
        }
        if (!format_found || depth_ != 24) {
            close(); return XcbStatus::unsupported_visual;
        }
        window_ = xcb_generate_id(conn_);
        const std::uint32_t values[] = {0, XCB_EVENT_MASK_STRUCTURE_NOTIFY};
        if (!checked(xcb_create_window_checked(
                conn_,depth_,window_,screen->root,0,0,
                static_cast<std::uint16_t>(width),static_cast<std::uint16_t>(height),
                0,XCB_WINDOW_CLASS_INPUT_OUTPUT,visual_,
                XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK,values))) {
            close(); return XcbStatus::rejected_request;
        }
        gc_ = xcb_generate_id(conn_);
        const std::uint32_t gcvalues[] = {0,0};
        if (!checked(xcb_create_gc_checked(conn_,gc_,window_,
                                          XCB_GC_FOREGROUND | XCB_GC_GRAPHICS_EXPOSURES,
                                          gcvalues)) ||
            !checked(xcb_map_window_checked(conn_,window_))) {
            close(); return XcbStatus::rejected_request;
        }
        if (xcb_flush(conn_) <= 0) {
            close(); return XcbStatus::unavailable;
        }
        width_ = width;
        height_ = height;
        return XcbStatus::ok;
    }

    XcbStatus present_rgba(const std::uint8_t* rgba, std::size_t bytes,
                           std::uint32_t width, std::uint32_t height) {
        if (!conn_ || !window_) return XcbStatus::not_open;
        if (!extent(width,height) || width != width_ || height != height_)
            return XcbStatus::out_of_date;
        const auto expected = std::size_t(width)*height*4;
        if (!rgba || bytes != expected) return XcbStatus::invalid_payload;
        if (!current_extent()) return XcbStatus::out_of_date;
        // Xvfb 24-bit TrueColor ZPixmap uses 32-bit B,G,R,unused bytes.
        // Intentionally converts ONLY a frame emitted by the real CPU raster.
        std::vector<std::uint8_t> bgra(expected);
        for (std::size_t i=0; i<expected; i+=4) {
            bgra[i] = rgba[i+2];
            bgra[i+1] = rgba[i+1];
            bgra[i+2] = rgba[i];
            bgra[i+3] = 0;
        }
        if (!checked(xcb_put_image_checked(
                conn_,XCB_IMAGE_FORMAT_Z_PIXMAP,window_,gc_,
                static_cast<std::uint16_t>(width),static_cast<std::uint16_t>(height),
                0,0,0,depth_,static_cast<std::uint32_t>(expected),bgra.data())))
            return XcbStatus::rejected_request;
        if (xcb_flush(conn_) <= 0) return XcbStatus::unavailable;
        return XcbStatus::ok;
    }

    XcbStatus readback_rgba(std::vector<std::uint8_t>* result) {
        if (!conn_ || !window_) return XcbStatus::not_open;
        if (!result) return XcbStatus::invalid_payload;
        if (!current_extent()) return XcbStatus::out_of_date;
        auto cookie = xcb_get_image(conn_, XCB_IMAGE_FORMAT_Z_PIXMAP,
                                    window_,0,0,static_cast<std::uint16_t>(width_),
                                    static_cast<std::uint16_t>(height_),~0u);
        xcb_generic_error_t* error = nullptr;
        auto* reply = xcb_get_image_reply(conn_,cookie,&error);
        if (error) { std::free(error); if (reply) std::free(reply); return XcbStatus::rejected_request; }
        if (!reply) return XcbStatus::rejected_request;
        const auto len = xcb_get_image_data_length(reply);
        const auto expected = std::size_t(width_)*height_*4;
        if (len != static_cast<int>(expected) || reply->depth != depth_) {
            std::free(reply); return XcbStatus::unsupported_visual;
        }
        const auto* bgr = xcb_get_image_data(reply);
        std::vector<std::uint8_t> rgba(expected);
        for (std::size_t i=0;i<expected;i+=4) {
            rgba[i] = bgr[i+2];
            rgba[i+1] = bgr[i+1];
            rgba[i+2] = bgr[i];
            rgba[i+3] = 255; // X11 depth 24 has no stored alpha channel.
        }
        std::free(reply);
        result->swap(rgba);
        return XcbStatus::ok;
    }

    XcbStatus resize(std::uint32_t width, std::uint32_t height) {
        if (!conn_ || !window_) return XcbStatus::not_open;
        if (!extent(width,height)) return XcbStatus::invalid_extent;
        const std::uint32_t values[] = {width,height};
        if (!checked(xcb_configure_window_checked(
                conn_,window_,XCB_CONFIG_WINDOW_WIDTH | XCB_CONFIG_WINDOW_HEIGHT,values)))
            return XcbStatus::rejected_request;
        if (xcb_flush(conn_) <= 0) return XcbStatus::unavailable;
        width_=width; height_=height;
        return current_extent() ? XcbStatus::ok : XcbStatus::out_of_date;
    }

    void close() {
        if (!conn_) return;
        if (gc_) xcb_free_gc(conn_,gc_);
        if (window_) xcb_destroy_window(conn_,window_);
        xcb_flush(conn_);
        xcb_disconnect(conn_);
        conn_=nullptr; gc_=XCB_NONE; window_=XCB_WINDOW_NONE;
        width_=height_=visual_=0; depth_=0;
    }
    std::uint32_t visual() const { return visual_; }
    std::uint8_t depth() const { return depth_; }
};
} // namespace are::vulkan::prewsi
