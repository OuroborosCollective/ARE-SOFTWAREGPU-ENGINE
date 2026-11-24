// A real Khronos loader client for the experimental ARE VkSampler resource.
// No mocks or faked Unity / GPU observations: this exercises only sampler
// object creation, state ownership, supported parameter admission and teardown.
#include <vulkan/vulkan.h>
#include <cstring>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void require(bool state, const char* label) {
    if (!state) throw std::runtime_error(label);
}
static void check(VkResult result, const char* label) {
    if (result != VK_SUCCESS)
        throw std::runtime_error(std::string(label) + " error=" + std::to_string(result));
}
static int run() {
    VkApplicationInfo app{};
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.apiVersion = VK_API_VERSION_1_0;
    VkInstanceCreateInfo ici{};
    ici.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    ici.pApplicationInfo = &app;
    VkInstance instance{};
    check(vkCreateInstance(&ici,nullptr,&instance), "vkCreateInstance");
    std::uint32_t n=0;
    check(vkEnumeratePhysicalDevices(instance,&n,nullptr),"enumerate_count");
    require(n==1, "Sampler real-client requires exactly one isolated ARE ICD");
    VkPhysicalDevice physical{};
    check(vkEnumeratePhysicalDevices(instance,&n,&physical),"enumerate_device");
    VkPhysicalDeviceProperties props{};
    vkGetPhysicalDeviceProperties(physical,&props);
    require(props.deviceType==VK_PHYSICAL_DEVICE_TYPE_CPU &&
            std::strstr(props.deviceName,"ARE SoftwareGPU")!=nullptr,
            "Non-ARE Vulkan device prohibited");
    require(props.limits.maxSamplerAllocationCount >= 4000 && props.limits.maxSamplerLodBias >= 2,
            "Sampler limits below Vulkan core minimum");
    float priority=1;
    VkDeviceQueueCreateInfo qi{};
    qi.sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    qi.queueFamilyIndex=0;
    qi.queueCount=1;
    qi.pQueuePriorities=&priority;
    VkDeviceCreateInfo dci{};
    dci.sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    dci.queueCreateInfoCount=1;
    dci.pQueueCreateInfos=&qi;
    VkDevice device{};
    check(vkCreateDevice(physical,&dci,nullptr,&device),"vkCreateDevice");
    auto create = reinterpret_cast<PFN_vkCreateSampler>(
        vkGetDeviceProcAddr(device,"vkCreateSampler"));
    auto destroy = reinterpret_cast<PFN_vkDestroySampler>(
        vkGetDeviceProcAddr(device,"vkDestroySampler"));
    require(create!=nullptr && destroy!=nullptr,
            "ARE_VK_SAMPLER_REAL_DISPATCH_MISSING");

    VkSamplerCreateInfo ci{};
    ci.sType=VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    ci.magFilter=VK_FILTER_NEAREST;
    ci.minFilter=VK_FILTER_NEAREST;
    ci.mipmapMode=VK_SAMPLER_MIPMAP_MODE_NEAREST;
    ci.addressModeU=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    ci.addressModeV=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    ci.addressModeW=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    ci.maxAnisotropy=1;
    ci.compareOp=VK_COMPARE_OP_ALWAYS;
    ci.borderColor=VK_BORDER_COLOR_FLOAT_TRANSPARENT_BLACK;
    VkSampler first=VK_NULL_HANDLE;
    check(create(device,&ci,nullptr,&first),"create_nearest");
    require(first!=VK_NULL_HANDLE,"Nearest sampler handle not real");
    VkSampler second=VK_NULL_HANDLE;
    ci.magFilter=VK_FILTER_LINEAR;
    ci.minFilter=VK_FILTER_LINEAR;
    ci.addressModeU=VK_SAMPLER_ADDRESS_MODE_REPEAT;
    check(create(device,&ci,nullptr,&second),"create_linear_repeat");
    require(second!=VK_NULL_HANDLE && second!=first,"No independent sampler ownership");

    VkSampler invalid=VK_NULL_HANDLE;
    ci.anisotropyEnable=VK_TRUE; // not supported by this restricted ICD
    ci.maxAnisotropy=16;
    VkResult anisotropic=create(device,&ci,nullptr,&invalid);
    require(anisotropic==VK_ERROR_FEATURE_NOT_PRESENT && invalid==VK_NULL_HANDLE,
            "Unimplemented anisotropy must not be advertised");
    ci.anisotropyEnable=VK_FALSE;
    ci.maxAnisotropy=1;
    VkBaseInStructure extension{};
    extension.sType=VK_STRUCTURE_TYPE_APPLICATION_INFO;
    ci.pNext=&extension;
    VkResult ext=create(device,&ci,nullptr,&invalid);
    require(ext==VK_ERROR_FEATURE_NOT_PRESENT && invalid==VK_NULL_HANDLE,
            "Unimplemented sampler pNext chain must be rejected");
    ci.pNext=nullptr;
    ci.unnormalizedCoordinates=VK_TRUE;
    ci.addressModeU=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    ci.mipLodBias=props.limits.maxSamplerLodBias;
    std::vector<VkSampler> owned(props.limits.maxSamplerAllocationCount-2);
    for (auto& sampler : owned) check(create(device,&ci,nullptr,&sampler),"fill_sampler_budget");
    require(create(device,&ci,nullptr,&invalid)==VK_ERROR_TOO_MANY_OBJECTS && invalid==VK_NULL_HANDLE,
            "Sampler allocation limit must be enforced");
    for (auto sampler : owned) destroy(device,sampler,nullptr);
    check(create(device,&ci,nullptr,&invalid),"reuse_sampler_capacity");
    destroy(device,invalid,nullptr);
    destroy(device,first,nullptr);
    destroy(device,second,nullptr);
    vkDestroyDevice(device,nullptr);
    vkDestroyInstance(instance,nullptr);
    std::cout << "ARE_VK_SAMPLER_REAL_CREATE_DESTROY_PASS two_distinct_handles=1 "
              << "unsupported_anisotropy=" << anisotropic
              << " unsupported_extension_chain=" << ext << "\n";
    return 0;
}
int main() {
    try {return run();}
    catch(const std::exception& e) {std::cerr << e.what() << "\n";return 3;}
}
