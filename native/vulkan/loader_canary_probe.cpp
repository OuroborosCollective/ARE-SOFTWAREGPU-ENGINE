// Genuine Khronos Vulkan loader calls, restricted to the ARE canary ICD.
// CPU driver is NOT a functional graphics device yet; zero is required.
#include <vulkan/vulkan.h>
#include <cstdint>
#include <cstdio>
int main() {
    VkApplicationInfo app{};
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.pApplicationName = "ARE loader admission";
    app.apiVersion = VK_API_VERSION_1_0;
    VkInstanceCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    info.pApplicationInfo = &app;
    VkInstance instance = VK_NULL_HANDLE;
    const VkResult result = vkCreateInstance(&info, nullptr, &instance);
    if (result != VK_SUCCESS || instance == VK_NULL_HANDLE) {
        std::fprintf(stderr, "ARE_REAL_LOADER_INSTANCE_FAILED:%d\\n", static_cast<int>(result));
        return 10;
    }
    std::uint32_t count = 777u;
    const VkResult enumerated = vkEnumeratePhysicalDevices(instance, &count, nullptr);
    std::printf("ARE_REAL_LOADER_ENUMERATION_RESULT=%d COUNT=%u\\n",
                static_cast<int>(enumerated), count);
    vkDestroyInstance(instance, nullptr);
    // The real loader may synthesize VK_ERROR_INITIALIZATION_FAILED when
    // the ICD successfully enumerates zero physical devices. This is an
    // explicit NO-DEVICE *negative* admission, never proof of a GPU.
    const bool no_devices =
        (enumerated == VK_SUCCESS && count == 0u) ||
        (enumerated == VK_ERROR_INITIALIZATION_FAILED && count == 777u);
    return no_devices ? 0 : 11;
}
