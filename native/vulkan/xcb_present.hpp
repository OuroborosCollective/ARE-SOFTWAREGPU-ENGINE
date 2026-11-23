// No Vulkan ICD or swapchain is exported from this file.
// Actual X11/XCB transport for native ARE RGBA8; verified via X server GetImage.
// Fail closed on any unsupported visual, byte order, depth or stale connection.
// Single-threaded, owner-exclusive. Caller and X server are real, not mocked.
#pragma once
#include <xcb/xcb.h>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace are::vulkan::xcb {
enum class PresentStatus : int {
    ok = 0, disconnected, invalid_frame, unsupported_visual,
    window_error, capture_error, pixel_mismatch
};

class WindowPresenter final {
    xcb_connection_t* conn_ = nullptr;
    xcb_window_t window_ = XCB_WINDOW_NONE;
    xcb_gcontext_t gc_ = XCB_NONE;
    std::uint16_t width_ = 0,height_ = 0;
    PresentStatus status_ = PresentStatus::disconnected;
    bool checked(xcb_void_cookie_t cookie) {
        xcb_generic_error_t* error = xcb_request_check(conn_,cookie);
        if (!error) return true;
        std::free(error);
        return false;
    }
public:
    WindowPresenter(std::uint16_t width, std::uint16_t height)
        : width_(width),height_(height) {
        if (!width || !height || width > 4096 || height > 4096 ||
            std::size_t(width)*height > 4194304) {
            status_=PresentStatus::invalid_frame;
            return;
        }
        int screen_index=0;
        conn_=xcb_connect(nullptr,&screen_index);
        if (!conn_ || xcb_connection_has_error(conn_)) return;
        const xcb_setup_t* setup=xcb_get_setup(conn_);
        if (!setup || setup->image_byte_order!=XCB_IMAGE_ORDER_LSB_FIRST ||
            *reinterpret_cast<const std::uint8_t*>(
                &little_endian_check_) != 1u) {
            status_=PresentStatus::unsupported_visual;return;
        }
        xcb_screen_iterator_t screen_it=xcb_setup_roots_iterator(setup);
        for (int i=0;i<screen_index && screen_it.rem;++i)
            xcb_screen_next(&screen_it);
        if (!screen_it.rem) return;
        const xcb_screen_t* screen=screen_it.data;
        if (screen->root_depth!=24) {
            status_=PresentStatus::unsupported_visual;return;
        }
        bool format_ok=false,visual_ok=false;
        for (auto it=xcb_setup_pixmap_formats_iterator(setup);it.rem;
             xcb_format_next(&it)) {
            if (it.data->depth==24 && it.data->bits_per_pixel==32 &&
                it.data->scanline_pad==32) format_ok=true;
        }
        for (auto depth_it=xcb_screen_allowed_depths_iterator(screen);
             depth_it.rem; xcb_depth_next(&depth_it)) {
            for (auto it=xcb_depth_visuals_iterator(depth_it.data);it.rem;
                 xcb_visualtype_next(&it)) {
                const auto& visual=*it.data;
                if (visual.visual_id==screen->root_visual &&
                    visual._class==XCB_VISUAL_CLASS_TRUE_COLOR &&
                    visual.red_mask==0x00ff0000u &&
                    visual.green_mask==0x0000ff00u &&
                    visual.blue_mask==0x000000ffu) visual_ok=true;
            }
        }
        if (!format_ok || !visual_ok) {
            status_=PresentStatus::unsupported_visual;return;
        }
        window_=xcb_generate_id(conn_);
        const std::uint32_t values[]={
            screen->black_pixel, XCB_EVENT_MASK_EXPOSURE
        };
        if (!checked(xcb_create_window_checked(
                conn_,screen->root_depth,window_,screen->root,
                0,0,width,height,0,XCB_WINDOW_CLASS_INPUT_OUTPUT,
                screen->root_visual,
                XCB_CW_BACK_PIXEL|XCB_CW_EVENT_MASK,values))) {
            status_=PresentStatus::window_error;return;
        }
        gc_=xcb_generate_id(conn_);
        const std::uint32_t gc_values[]={0};
        if (!checked(xcb_create_gc_checked(
                conn_,gc_,window_,XCB_GC_GRAPHICS_EXPOSURES,gc_values)) ||
            !checked(xcb_map_window_checked(conn_,window_))) {
            status_=PresentStatus::window_error;return;
        }
        xcb_flush(conn_);
        status_=PresentStatus::ok;
    }
    WindowPresenter(const WindowPresenter&)=delete;
    WindowPresenter& operator=(const WindowPresenter&)=delete;
    ~WindowPresenter() {
        if (conn_) {
            if (gc_!=XCB_NONE) xcb_free_gc(conn_,gc_);
            if (window_!=XCB_WINDOW_NONE) xcb_destroy_window(conn_,window_);
            xcb_flush(conn_);
            xcb_disconnect(conn_);
        }
    }
    bool ready() const {
        return status_==PresentStatus::ok &&
               conn_ && xcb_connection_has_error(conn_)==0;
    }
    PresentStatus status() const { return status_; }
    PresentStatus present_and_readback(const std::vector<std::uint8_t>& rgba,
                                       std::vector<std::uint8_t>* observed) {
        if (!ready()) return PresentStatus::disconnected;
        const std::size_t pixels=std::size_t(width_)*height_;
        if (!observed || rgba.size()!=pixels*4) return PresentStatus::invalid_frame;
        std::vector<std::uint8_t> encoded(pixels*4);
        for (std::size_t i=0;i<pixels;++i) {
            encoded[4*i]=rgba[4*i+2]; // B
            encoded[4*i+1]=rgba[4*i+1]; // G
            encoded[4*i+2]=rgba[4*i]; // R
            encoded[4*i+3]=0;
        }
        if (!checked(xcb_put_image_checked(
                conn_,XCB_IMAGE_FORMAT_Z_PIXMAP,window_,gc_,
                width_,height_,0,0,0,24,
                static_cast<std::uint32_t>(encoded.size()),encoded.data())))
            return PresentStatus::window_error;
        xcb_get_image_cookie_t cookie=xcb_get_image(
            conn_,XCB_IMAGE_FORMAT_Z_PIXMAP,window_,0,0,width_,height_,0x00ffffffu);
        xcb_generic_error_t* error=nullptr;
        xcb_get_image_reply_t* reply=xcb_get_image_reply(conn_,cookie,&error);
        if (error) { std::free(error);std::free(reply);return PresentStatus::capture_error; }
        if (!reply) return PresentStatus::capture_error;
        auto count=xcb_get_image_data_length(reply);
        if (reply->depth!=24 || count!=static_cast<int>(encoded.size())) {
            std::free(reply);return PresentStatus::capture_error;
        }
        const auto* data=xcb_get_image_data(reply);
        for (std::size_t i=0;i<pixels;++i) {
            if (data[4*i]!=encoded[4*i] ||
                data[4*i+1]!=encoded[4*i+1] ||
                data[4*i+2]!=encoded[4*i+2]) {
                std::free(reply);return PresentStatus::pixel_mismatch;
            }
        }
        observed->assign(data,data+count);
        std::free(reply);
        return PresentStatus::ok;
    }
private:
    const std::uint16_t little_endian_check_=1;
};
} // namespace are::vulkan::xcb
