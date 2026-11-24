// Native independent Vulkan Loader + real XCB window/surface admission test.
// No library-direct calls, simulated graphics device, or fixture window.
#define VK_USE_PLATFORM_XCB_KHR 1
#include <vulkan/vulkan.h>
#include <xcb/xcb.h>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
static void check(VkResult r, const char* name) {
    if (r != VK_SUCCESS) throw std::runtime_error(std::string(name) + ":" + std::to_string(r));
}
#define CHECK(e) check((e), #e)
template<typename T> T instance_fn(VkInstance inst, const char* name) {
    const auto p = vkGetInstanceProcAddr(inst, name);
    if (!p) throw std::runtime_error(std::string("Missing dispatch:") + name);
    return reinterpret_cast<T>(p);
}
int main() {
    try {
        auto* xc = xcb_connect(nullptr, nullptr);
        if (!xc || xcb_connection_has_error(xc)) throw std::runtime_error("No real XCB connection");
        auto* screen = xcb_setup_roots_iterator(xcb_get_setup(xc)).data;
        if (!screen) throw std::runtime_error("No real XCB screen");
        const auto window = xcb_generate_id(xc);
        const std::uint32_t values[] = {screen->black_pixel, XCB_EVENT_MASK_STRUCTURE_NOTIFY};
        auto cookie = xcb_create_window_checked(xc, screen->root_depth, window, screen->root, 0,0,
                        32,24,0,XCB_WINDOW_CLASS_INPUT_OUTPUT,screen->root_visual,
                        XCB_CW_BACK_PIXEL | XCB_CW_EVENT_MASK, values);
        auto* error = xcb_request_check(xc, cookie);
        if (error) {std::free(error); throw std::runtime_error("Real window creation rejected");}
        cookie = xcb_map_window_checked(xc, window);
        error = xcb_request_check(xc, cookie);
        if (error) {std::free(error); throw std::runtime_error("Real window map rejected");}
        xcb_flush(xc);

        const char *extensions[] = {VK_KHR_SURFACE_EXTENSION_NAME,
                                    VK_KHR_XCB_SURFACE_EXTENSION_NAME};
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
        app.apiVersion = VK_API_VERSION_1_0;
        VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
        ici.pApplicationInfo = &app;
        ici.enabledExtensionCount = 2;
        ici.ppEnabledExtensionNames = extensions;
        VkInstance instance{};
        CHECK(vkCreateInstance(&ici, nullptr, &instance));
        const auto create = instance_fn<PFN_vkCreateXcbSurfaceKHR>(instance, "vkCreateXcbSurfaceKHR");
        const auto destroy = instance_fn<PFN_vkDestroySurfaceKHR>(instance, "vkDestroySurfaceKHR");
        const auto support = instance_fn<PFN_vkGetPhysicalDeviceSurfaceSupportKHR>(instance, "vkGetPhysicalDeviceSurfaceSupportKHR");
        const auto caps = instance_fn<PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR>(instance, "vkGetPhysicalDeviceSurfaceCapabilitiesKHR");
        const auto formats = instance_fn<PFN_vkGetPhysicalDeviceSurfaceFormatsKHR>(instance, "vkGetPhysicalDeviceSurfaceFormatsKHR");
        const auto modes = instance_fn<PFN_vkGetPhysicalDeviceSurfacePresentModesKHR>(instance, "vkGetPhysicalDeviceSurfacePresentModesKHR");
        const auto xcb_support = instance_fn<PFN_vkGetPhysicalDeviceXcbPresentationSupportKHR>(instance, "vkGetPhysicalDeviceXcbPresentationSupportKHR");
        std::uint32_t count=0;
        CHECK(vkEnumeratePhysicalDevices(instance, &count, nullptr));
        if (count!=1) throw std::runtime_error("ARE device identity: expected one");
        VkPhysicalDevice physical{};
        CHECK(vkEnumeratePhysicalDevices(instance, &count, &physical));
        VkPhysicalDeviceProperties props{};
        vkGetPhysicalDeviceProperties(physical, &props);
        if (std::strstr(props.deviceName, "ARE SoftwareGPU")==nullptr ||
            props.deviceType != VK_PHYSICAL_DEVICE_TYPE_CPU)
            throw std::runtime_error("Not the ARE-owned Vulkan physical device");
        if (!xcb_support(physical, 0, xc, screen->root_visual))
            throw std::runtime_error("XCB visual not supported");
        VkXcbSurfaceCreateInfoKHR ci{VK_STRUCTURE_TYPE_XCB_SURFACE_CREATE_INFO_KHR};
        ci.connection = xc;
        ci.window = window;
        VkSurfaceKHR surface{};
        CHECK(create(instance, &ci, nullptr, &surface));
        if (!surface) throw std::runtime_error("No VkSurfaceKHR returned");
        VkBool32 presented=VK_FALSE;
        CHECK(support(physical, 0, surface, &presented));
        if (!presented) throw std::runtime_error("Queue cannot present");
        VkSurfaceCapabilitiesKHR capabilities{};
        CHECK(caps(physical, surface, &capabilities));
        if (capabilities.currentExtent.width != 32 || capabilities.currentExtent.height != 24 ||
            capabilities.minImageCount != 2 || capabilities.maxImageCount != 2)
            throw std::runtime_error("Real XCB surface extent/count mismatch");
        std::uint32_t num=0;
        CHECK(formats(physical, surface, &num, nullptr));
        if (num!=1) throw std::runtime_error("Unexpected advertised formats");
        VkSurfaceFormatKHR sf{};
        CHECK(formats(physical, surface, &num, &sf));
        if (sf.format!=VK_FORMAT_R8G8B8A8_UNORM) throw std::runtime_error("Unexpected Vulkan format");
        num=0;
        CHECK(modes(physical, surface, &num, nullptr));
        if(num!=1) throw std::runtime_error("Unexpected present modes");
        VkPresentModeKHR mode{};
        CHECK(modes(physical, surface, &num, &mode));
        if(mode!=VK_PRESENT_MODE_FIFO_KHR) throw std::runtime_error("Missing FIFO present");
        float priority = 1.0f;
        VkDeviceQueueCreateInfo qi{};
        qi.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
        qi.queueFamilyIndex = 0;
        qi.queueCount = 1;
        qi.pQueuePriorities = &priority;
        const char *device_extensions[] = { VK_KHR_SWAPCHAIN_EXTENSION_NAME };
        VkDeviceCreateInfo di{};
        di.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
        di.queueCreateInfoCount = 1;
        di.pQueueCreateInfos = &qi;
        di.enabledExtensionCount = 1;
        di.ppEnabledExtensionNames = device_extensions;
        VkDevice device{};
        CHECK(vkCreateDevice(physical, &di, nullptr, &device));
        vkDestroyDevice(device, nullptr);
        const auto badwindow = window + 40000000u;
        ci.window = badwindow;
        VkSurfaceKHR invalid{};
        const auto invalid_result = create(instance, &ci, nullptr, &invalid);
        if (invalid_result==VK_SUCCESS || invalid) throw std::runtime_error("Invalid XCB window accepted");
        destroy(instance,surface,nullptr);
        vkDestroyInstance(instance,nullptr);
        xcb_destroy_window(xc,window);
        xcb_flush(xc);
        xcb_disconnect(xc);
        std::cout << "ARE_REAL_VULKAN_XCB_SURFACE_PASS " << props.deviceName << " 32x24\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "ARE_REAL_VULKAN_XCB_SURFACE_FAIL:" << e.what() << "\n";
        return 3;
    }
}
