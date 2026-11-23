// OuroborosCollective - LICENSE.md applies.
// Minimal *real* Vulkan ICD loader boundary for admission tests.
// Intentionally enumerates ZERO VkPhysicalDevices until Vulkan resources,
// command buffers, pipelines, synchronization and native shader execution work.
// It is NOT a usable Vulkan GPU, WSI driver, or Unity device.
// Build with system Khronos Vulkan headers and the existing ARE C++ raster ABI.
#include <vulkan/vulkan.h>
#include <vulkan/vk_icd.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>

#if defined(_WIN32)
#define ARE_VK_EXPORT extern "C" __declspec(dllexport)
#else
#define ARE_VK_EXPORT extern "C" __attribute__((visibility("default")))
#endif

ARE_VK_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vk_icdGetInstanceProcAddr(VkInstance, const char*);
ARE_VK_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vk_icdGetDeviceProcAddr(VkDevice, const char*);

struct VkInstance_T {
    VK_LOADER_DATA loader_data;
    std::uint32_t protocol_version;
};

namespace {
constexpr std::uint32_t kLoaderInterface = 5;
constexpr std::uint32_t kInstanceProtocol = 0x41524531; // "ARE1"

void trace(const char* stage) {
    const char* enabled = std::getenv("ARE_ICD_TRACE");
    if (enabled && enabled[0] == '1' && enabled[1] == '\0')
        std::fprintf(stderr, "ARE_ICD_ACTUAL_ENTRY:%s\\n", stage);
}

bool valid_instance(VkInstance instance) {
    // Caller is the Vulkan loader, which owns the opaque handle boundary.
    return instance && instance->protocol_version == kInstanceProtocol;
}

VKAPI_ATTR VkResult VKAPI_CALL create_instance(
    const VkInstanceCreateInfo* info, const VkAllocationCallbacks*,
    VkInstance* instance) {
    trace("create-instance");
    if (!info || !instance || info->sType != VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO)
        return VK_ERROR_INITIALIZATION_FAILED;
    *instance = VK_NULL_HANDLE;
    if (info->enabledLayerCount) return VK_ERROR_LAYER_NOT_PRESENT;
    if (info->enabledExtensionCount) return VK_ERROR_EXTENSION_NOT_PRESENT;
    const std::uint32_t version = info->pApplicationInfo
        ? info->pApplicationInfo->apiVersion : VK_API_VERSION_1_0;
    if (VK_API_VERSION_MAJOR(version) != 1 || VK_API_VERSION_MINOR(version) > 0)
        return VK_ERROR_INCOMPATIBLE_DRIVER;
    auto* value = new (std::nothrow) VkInstance_T{};
    if (!value) return VK_ERROR_OUT_OF_HOST_MEMORY;
    set_loader_magic_value(value);
    value->protocol_version = kInstanceProtocol;
    *instance = value;
    if (std::getenv("ARE_ICD_TRACE")) std::fprintf(stderr, "ARE_ICD_INSTANCE_ALLOCATED:%p proto=%08x\\n", static_cast<void*>(value), value->protocol_version);
    return VK_SUCCESS;
}

VKAPI_ATTR void VKAPI_CALL destroy_instance(
    VkInstance instance, const VkAllocationCallbacks*) {
    if (!valid_instance(instance)) return;
    instance->protocol_version = 0;
    delete instance;
}

VKAPI_ATTR VkResult VKAPI_CALL enumerate_physical_devices(
    VkInstance instance, std::uint32_t* count, VkPhysicalDevice* devices) {
    trace("enumerate-zero-devices");
    if (std::getenv("ARE_ICD_TRACE")) std::fprintf(stderr, "ARE_ICD_ENUM_INSTANCE:%p proto=%08x countptr=%p\\n", static_cast<void*>(instance), instance ? instance->protocol_version : 0u, static_cast<void*>(count));
    if (!valid_instance(instance) || !count) return VK_ERROR_INITIALIZATION_FAILED;
    // No fake CPU GPU or dummy queues may reach Vulkan clients.
    *count = 0;
    (void)devices;
    trace("icd-return-zero-devices-vk-success");
    return VK_SUCCESS;
}

VKAPI_ATTR VkResult VKAPI_CALL enumerate_instance_extensions(
    const char* layer, std::uint32_t* count, VkExtensionProperties*) {
    if (layer) return VK_ERROR_LAYER_NOT_PRESENT;
    if (!count) return VK_ERROR_INITIALIZATION_FAILED;
    *count = 0;
    return VK_SUCCESS;
}

VKAPI_ATTR VkResult VKAPI_CALL enumerate_instance_layers(
    std::uint32_t* count, VkLayerProperties*) {
    if (!count) return VK_ERROR_INITIALIZATION_FAILED;
    *count = 0;
    return VK_SUCCESS;
}

VKAPI_ATTR VkResult VKAPI_CALL enumerate_instance_version(std::uint32_t* version) {
    if (!version) return VK_ERROR_INITIALIZATION_FAILED;
    *version = VK_API_VERSION_1_0;
    return VK_SUCCESS;
}

/* Required Vulkan 1.0 physical-device dispatch pointers.
 * No physical device is ever returned to an application, hence none of these
 * report any capability. An invalid/unadvertised handle receives no features.
 * They are not substitutes for a real future VkPhysicalDevice implementation.
 */
VKAPI_ATTR void VKAPI_CALL physical_features(VkPhysicalDevice, VkPhysicalDeviceFeatures* v) {
    if (v) std::memset(v, 0, sizeof(*v));
}
VKAPI_ATTR void VKAPI_CALL physical_properties(VkPhysicalDevice, VkPhysicalDeviceProperties* v) {
    if (v) std::memset(v, 0, sizeof(*v));
}
VKAPI_ATTR void VKAPI_CALL physical_memory(VkPhysicalDevice, VkPhysicalDeviceMemoryProperties* v) {
    if (v) std::memset(v, 0, sizeof(*v));
}
VKAPI_ATTR void VKAPI_CALL physical_queue_families(
    VkPhysicalDevice, std::uint32_t* count, VkQueueFamilyProperties*) {
    if (count) *count = 0;
}
VKAPI_ATTR void VKAPI_CALL physical_format(
    VkPhysicalDevice, VkFormat, VkFormatProperties* v) {
    if (v) std::memset(v, 0, sizeof(*v));
}
VKAPI_ATTR VkResult VKAPI_CALL physical_image_format(
    VkPhysicalDevice, VkFormat, VkImageType, VkImageTiling,
    VkImageUsageFlags, VkImageCreateFlags, VkImageFormatProperties*) {
    return VK_ERROR_FORMAT_NOT_SUPPORTED;
}
VKAPI_ATTR void VKAPI_CALL physical_sparse_format(
    VkPhysicalDevice, VkFormat, VkImageType, VkSampleCountFlagBits,
    VkImageUsageFlags, VkImageTiling, std::uint32_t* count,
    VkSparseImageFormatProperties*) {
    if (count) *count = 0;
}
VKAPI_ATTR VkResult VKAPI_CALL enumerate_device_extensions(
    VkPhysicalDevice, const char* layer, std::uint32_t* count, VkExtensionProperties*) {
    if (layer) return VK_ERROR_LAYER_NOT_PRESENT;
    if (!count) return VK_ERROR_INITIALIZATION_FAILED;
    *count = 0;
    return VK_SUCCESS;
}
VKAPI_ATTR VkResult VKAPI_CALL reject_create_device(
    VkPhysicalDevice, const VkDeviceCreateInfo*, const VkAllocationCallbacks*, VkDevice* device) {
    if (device) *device = VK_NULL_HANDLE;
    return VK_ERROR_INCOMPATIBLE_DRIVER;
}

PFN_vkVoidFunction resolve(const char* name) {
    if (!name) return nullptr;
#define FN(s, ptr) if (std::strcmp(name, s) == 0) return reinterpret_cast<PFN_vkVoidFunction>(ptr)
    FN("vkCreateInstance", create_instance);
    FN("vkDestroyInstance", destroy_instance);
    FN("vkEnumeratePhysicalDevices", enumerate_physical_devices);
    FN("vkEnumerateInstanceExtensionProperties", enumerate_instance_extensions);
    FN("vkEnumerateInstanceLayerProperties", enumerate_instance_layers);
    FN("vkEnumerateInstanceVersion", enumerate_instance_version);
    FN("vkGetPhysicalDeviceFeatures", physical_features);
    FN("vkGetPhysicalDeviceProperties", physical_properties);
    FN("vkGetPhysicalDeviceMemoryProperties", physical_memory);
    FN("vkGetPhysicalDeviceQueueFamilyProperties", physical_queue_families);
    FN("vkGetPhysicalDeviceFormatProperties", physical_format);
    FN("vkGetPhysicalDeviceImageFormatProperties", physical_image_format);
    FN("vkGetPhysicalDeviceSparseImageFormatProperties", physical_sparse_format);
    FN("vkEnumerateDeviceExtensionProperties", enumerate_device_extensions);
    FN("vkCreateDevice", reject_create_device);
    FN("vkGetInstanceProcAddr", vk_icdGetInstanceProcAddr);
    FN("vkGetDeviceProcAddr", vk_icdGetDeviceProcAddr);
#undef FN
    return nullptr;
}
} // namespace

ARE_VK_EXPORT VKAPI_ATTR VkResult VKAPI_CALL
vk_icdNegotiateLoaderICDInterfaceVersion(std::uint32_t* version) {
    trace("negotiate-loader-interface");
    if (!version || *version < 2) return VK_ERROR_INCOMPATIBLE_DRIVER;
    if (*version > kLoaderInterface) *version = kLoaderInterface;
    return VK_SUCCESS;
}

ARE_VK_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vk_icdGetInstanceProcAddr(VkInstance, const char* name) {
    if (name && (std::strcmp(name, "vkCreateInstance") == 0 ||
                 std::strcmp(name, "vkEnumeratePhysicalDevices") == 0 ||
                 std::strcmp(name, "vkDestroyInstance") == 0 ||
                 std::strcmp(name, "vkGetPhysicalDeviceFeatures") == 0)) trace(name);
    return resolve(name);
}

ARE_VK_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vk_icdGetPhysicalDeviceProcAddr(VkInstance, const char*) {
    return nullptr; // no physical devices, so no physical-device extensions
}

ARE_VK_EXPORT VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vk_icdGetDeviceProcAddr(VkDevice, const char*) {
    return nullptr; // no devices: NEVER advertise queue or draw support
}
