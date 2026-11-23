// Experimental genuine Khronos Loader/ICD handshake only.
// NO VkPhysicalDevice is advertised until ARE implements real Vulkan operations.
// Does not copy, wrap, or rename Mesa/Lavapipe.
#include <vulkan/vulkan.h>
#include <vulkan/vk_icd.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <new>

namespace {
struct CanaryInstance {
    // Loader dispatchable-object contract: first word holds ICD loader magic.
    std::uintptr_t loader_magic = ICD_LOADER_MAGIC;
};
constexpr std::uint32_t supported_api = VK_API_VERSION_1_0;

VkResult VKAPI_CALL create_instance(const VkInstanceCreateInfo* info,
                                  const VkAllocationCallbacks* allocator,
                                  VkInstance* instance) {
    std::fprintf(stderr, "ARE_ICD_CREATE_CALLED info=%d flags=%u layers=%u ext=%u pnext=%d app_api=%u alloc=%d\\n",
        info != nullptr, info ? info->flags : 0u,
        info ? info->enabledLayerCount : 0u,
        info ? info->enabledExtensionCount : 0u,
        info && info->pNext != nullptr,
        info && info->pApplicationInfo ? info->pApplicationInfo->apiVersion : 0u,
        allocator != nullptr);
    if (!info || !instance || info->sType != VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO ||
        info->flags != 0 || info->enabledExtensionCount != 0 ||
        info->enabledLayerCount != 0 ||
        (info->pApplicationInfo &&
         info->pApplicationInfo->apiVersion > supported_api)) {
        return VK_ERROR_INCOMPATIBLE_DRIVER;
    }
    // No allocator support yet. Never pretend an unsupported allocator works.
    if (allocator) return VK_ERROR_INCOMPATIBLE_DRIVER;
    auto* result = new (std::nothrow) CanaryInstance();
    if (!result) return VK_ERROR_OUT_OF_HOST_MEMORY;
    *instance = reinterpret_cast<VkInstance>(result);
    return VK_SUCCESS;
}
void VKAPI_CALL destroy_instance(VkInstance instance, const VkAllocationCallbacks*) {
    delete reinterpret_cast<CanaryInstance*>(instance);
}
VkResult VKAPI_CALL enumerate_devices(VkInstance instance, std::uint32_t* count,
                                      VkPhysicalDevice* devices) {
    if (!instance || !count) return VK_ERROR_INITIALIZATION_FAILED;
    // A zero-device experimental ICD is intentionally NOT a graphics card.
    *count = 0;
    (void)devices;
    return VK_SUCCESS;
}
VkResult VKAPI_CALL enumerate_device_groups(VkInstance instance, std::uint32_t* count,
                                            VkPhysicalDeviceGroupProperties* groups) {
    if (!instance || !count) return VK_ERROR_INITIALIZATION_FAILED;
    *count = 0;
    (void)groups;
    return VK_SUCCESS;
}
VkResult VKAPI_CALL enumerate_extensions(const char* layer, std::uint32_t* count,
                                        VkExtensionProperties* properties) {
    if (!count || layer) return VK_ERROR_LAYER_NOT_PRESENT;
    *count = 0;
    (void)properties;
    return VK_SUCCESS;
}
VkResult VKAPI_CALL enumerate_version(std::uint32_t* version) {
    if (!version) return VK_ERROR_INITIALIZATION_FAILED;
    *version = supported_api;
    return VK_SUCCESS;
}
PFN_vkVoidFunction VKAPI_CALL device_proc_addr(VkDevice, const char*) {
    return nullptr; // No VkDevice is constructible from this canary.
}
// The Khronos Loader requires the *pointers* for all core 1.0 instance
// dispatch entries before accepting any ICD VkInstance, even a zero-device
// one. No physical-device handle can ever be enumerated from this canary.
// Never return invented Vulkan capabilities for an impossible physical device.
[[noreturn]] void unconstructible_physical_device() {
    std::fputs("ARE_LOADER_CANARY_PHYSICAL_DEVICE_NOT_CONSTRUCTIBLE\\n", stderr);
    std::abort();
}
void VKAPI_CALL unavailable_features(VkPhysicalDevice, VkPhysicalDeviceFeatures*) {
    unconstructible_physical_device();
}
void VKAPI_CALL unavailable_format(VkPhysicalDevice, VkFormat, VkFormatProperties*) {
    unconstructible_physical_device();
}
VkResult VKAPI_CALL unavailable_image_format(VkPhysicalDevice, VkFormat,
                   VkImageType, VkImageTiling, VkImageUsageFlags,
                   VkImageCreateFlags, VkImageFormatProperties*) {
    return VK_ERROR_INITIALIZATION_FAILED;
}
void VKAPI_CALL unavailable_properties(VkPhysicalDevice, VkPhysicalDeviceProperties*) {
    unconstructible_physical_device();
}
void VKAPI_CALL unavailable_queue_families(VkPhysicalDevice, std::uint32_t*,
                                           VkQueueFamilyProperties*) {
    unconstructible_physical_device();
}
void VKAPI_CALL unavailable_memory(VkPhysicalDevice, VkPhysicalDeviceMemoryProperties*) {
    unconstructible_physical_device();
}
VkResult VKAPI_CALL unavailable_create_device(VkPhysicalDevice,
               const VkDeviceCreateInfo*, const VkAllocationCallbacks*, VkDevice*) {
    return VK_ERROR_INITIALIZATION_FAILED;
}
VkResult VKAPI_CALL unavailable_device_extensions(VkPhysicalDevice, const char*,
                                                   std::uint32_t*, VkExtensionProperties*) {
    return VK_ERROR_INITIALIZATION_FAILED;
}
void VKAPI_CALL unavailable_sparse_image(VkPhysicalDevice, VkFormat, VkImageType,
        VkSampleCountFlagBits, VkImageUsageFlags, VkImageTiling, std::uint32_t*,
        VkSparseImageFormatProperties*) {
    unconstructible_physical_device();
}
PFN_vkVoidFunction VKAPI_CALL get_instance_proc_addr(VkInstance, const char* name);
template <typename Fn>
PFN_vkVoidFunction pfn(Fn fn) { return reinterpret_cast<PFN_vkVoidFunction>(fn); }
} // namespace

// Export ONLY the loader-specific entry points. Do not interpose libvulkan.so.
#if defined(__GNUC__)
#define EXPORT extern "C" __attribute__((visibility("default")))
#else
#define EXPORT extern "C"
#endif

EXPORT VkResult VKAPI_CALL vk_icdNegotiateLoaderICDInterfaceVersion(std::uint32_t* version) {
    if (!version || *version < 2) return VK_ERROR_INCOMPATIBLE_DRIVER;
    *version = std::min<std::uint32_t>(*version, 2u);
    return VK_SUCCESS;
}
EXPORT PFN_vkVoidFunction VKAPI_CALL vk_icdGetPhysicalDeviceProcAddr(VkInstance, const char*) {
    return nullptr;
}
EXPORT PFN_vkVoidFunction VKAPI_CALL vk_icdGetInstanceProcAddr(VkInstance instance, const char* name) {
    return get_instance_proc_addr(instance, name);
}
namespace {
PFN_vkVoidFunction VKAPI_CALL get_instance_proc_addr(VkInstance instance, const char* name) {
    if (!name) return nullptr;
    if (!std::strcmp(name, "vk_icdNegotiateLoaderICDInterfaceVersion"))
        return pfn(&vk_icdNegotiateLoaderICDInterfaceVersion);
    if (!std::strcmp(name, "vk_icdGetInstanceProcAddr"))
        return pfn(&vk_icdGetInstanceProcAddr);
    if (!std::strcmp(name, "vk_icdGetPhysicalDeviceProcAddr"))
        return pfn(&vk_icdGetPhysicalDeviceProcAddr);
    if (!std::strcmp(name, "vkGetInstanceProcAddr"))
        return pfn(&vk_icdGetInstanceProcAddr);
    if (!std::strcmp(name, "vkGetDeviceProcAddr"))
        return pfn(&device_proc_addr);
    if (!std::strcmp(name, "vkCreateInstance")) return pfn(&create_instance);
    if (!std::strcmp(name, "vkEnumerateInstanceExtensionProperties"))
        return pfn(&enumerate_extensions);
    if (!std::strcmp(name, "vkEnumerateInstanceVersion")) return pfn(&enumerate_version);
    if (!instance) return nullptr;
    if (!std::strcmp(name, "vkGetPhysicalDeviceFeatures"))
        return pfn(&unavailable_features);
    if (!std::strcmp(name, "vkGetPhysicalDeviceFormatProperties"))
        return pfn(&unavailable_format);
    if (!std::strcmp(name, "vkGetPhysicalDeviceImageFormatProperties"))
        return pfn(&unavailable_image_format);
    if (!std::strcmp(name, "vkGetPhysicalDeviceProperties"))
        return pfn(&unavailable_properties);
    if (!std::strcmp(name, "vkGetPhysicalDeviceQueueFamilyProperties"))
        return pfn(&unavailable_queue_families);
    if (!std::strcmp(name, "vkGetPhysicalDeviceMemoryProperties"))
        return pfn(&unavailable_memory);
    if (!std::strcmp(name, "vkCreateDevice"))
        return pfn(&unavailable_create_device);
    if (!std::strcmp(name, "vkEnumerateDeviceExtensionProperties"))
        return pfn(&unavailable_device_extensions);
    if (!std::strcmp(name, "vkGetPhysicalDeviceSparseImageFormatProperties"))
        return pfn(&unavailable_sparse_image);
    if (!std::strcmp(name, "vkDestroyInstance")) return pfn(&destroy_instance);
    if (!std::strcmp(name, "vkEnumeratePhysicalDevices")) return pfn(&enumerate_devices);
    if (!std::strcmp(name, "vkEnumeratePhysicalDeviceGroups"))
        return pfn(&enumerate_device_groups);
    return nullptr;
}
}
