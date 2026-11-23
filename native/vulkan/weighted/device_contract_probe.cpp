// Real system-Vulkan-loader negative contract probe on ARE's actual CPU ICD.
// No fake Vulkan device or mocks. Reject reserved flags before resource ownership.
#include <vulkan/vulkan.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

static int fail(const char* what, VkResult status) {
    std::fprintf(stderr, "ARE_NEGATIVE_VK_DEVICE_FAIL:%s:%d\n", what, int(status));
    return 1;
}

int main() {
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.apiVersion = VK_API_VERSION_1_0;
    VkInstanceCreateInfo ii{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    ii.pApplicationInfo = &app;
    VkInstance instance = VK_NULL_HANDLE;
    if (VkResult r = vkCreateInstance(&ii, nullptr, &instance); r != VK_SUCCESS)
        return fail("create-instance",r);
    std::uint32_t count = 1;
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    if (VkResult r = vkEnumeratePhysicalDevices(instance,&count,&physical);
        r != VK_SUCCESS || count != 1 || physical == VK_NULL_HANDLE)
        return fail("enumerate-real-are",-1);
    float priority=1.0f;
    VkDeviceQueueCreateInfo queue{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    queue.queueFamilyIndex=0;
    queue.queueCount=1;
    queue.pQueuePriorities=&priority;
    VkDeviceCreateInfo info{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    info.queueCreateInfoCount=1;
    info.pQueueCreateInfos=&queue;
    // Vulkan 1.0 VkDeviceCreateInfo::flags are reserved zero.
    info.flags=1;
    VkDevice forbidden=VK_NULL_HANDLE;
    VkResult rejected=vkCreateDevice(physical,&info,nullptr,&forbidden);
    if (rejected == VK_SUCCESS || forbidden != VK_NULL_HANDLE)
        return fail("unsupported-device-flags-accepted",rejected);
    std::printf("ARE_REAL_VK_DEVICE_FLAGS_REJECTED=%d\n",int(rejected));
    info.flags=0;
    queue.flags=1;
    forbidden=VK_NULL_HANDLE;
    rejected=vkCreateDevice(physical,&info,nullptr,&forbidden);
    if (rejected == VK_SUCCESS || forbidden != VK_NULL_HANDLE)
        return fail("unsupported-queue-flags-accepted",rejected);
    std::printf("ARE_REAL_VK_QUEUE_FLAGS_REJECTED=%d\n",int(rejected));
    queue.flags=0;
    VkDevice valid=VK_NULL_HANDLE;
    VkResult accepted=vkCreateDevice(physical,&info,nullptr,&valid);
    if (accepted != VK_SUCCESS || valid==VK_NULL_HANDLE)
        return fail("valid-device-rejected",accepted);
    VkQueue actual=VK_NULL_HANDLE;
    vkGetDeviceQueue(valid,0,0,&actual);
    if(actual==VK_NULL_HANDLE) return fail("valid-queue-missing",-1);
    vkDestroyDevice(valid,nullptr);
    vkDestroyInstance(instance,nullptr);
    std::puts("ARE_REAL_VK_DEVICE_NEGATIVE_AND_VALID_PASS");
    return 0;
}
