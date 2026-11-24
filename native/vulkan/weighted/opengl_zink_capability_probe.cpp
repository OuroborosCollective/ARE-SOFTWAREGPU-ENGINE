// Capability admission uses the real Khronos Vulkan loader, not a test ICD.
// Nonzero exit 3 means the ARE device cannot yet run Mesa Zink OpenGL.
#include <vulkan/vulkan.h>
#include <algorithm>
#include <cstring>
#include <iostream>
#include <set>
#include <string>
#include <vector>

static const char* base_extensions[] = {
    "VK_KHR_maintenance1", "VK_KHR_maintenance5",
    "VK_KHR_create_renderpass2", "VK_KHR_imageless_framebuffer",
    "VK_KHR_timeline_semaphore", "VK_KHR_dynamic_rendering",
    "VK_EXT_custom_border_color", "VK_EXT_provoking_vertex",
    "VK_EXT_line_rasterization", "VK_KHR_swapchain_mutable_format",
    "VK_EXT_border_color_swizzle", "VK_KHR_descriptor_update_template",
    "VK_KHR_external_memory"
};
static void json_string(const std::string& s) {
    std::cout << '"';
    for (unsigned char c : s) {
        if (c=='"' || c=='\\') std::cout << '\\' << c;
        else if (c >= 32 && c < 127) std::cout << c;
        else std::cout << '?';
    }
    std::cout << '"';
}
static void json_list(const std::vector<std::string>& values) {
    std::cout << '[';
    for (std::size_t i=0;i<values.size();++i) {
        if (i) std::cout << ',';
        json_string(values[i]);
    }
    std::cout << ']';
}
int main() {
    VkApplicationInfo app{};
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.apiVersion = VK_API_VERSION_1_0;
    VkInstanceCreateInfo info{};
    info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    info.pApplicationInfo = &app;
    VkInstance instance{};
    VkResult result = vkCreateInstance(&info, nullptr, &instance);
    if (result != VK_SUCCESS || !instance) {
        std::cerr << "ARE_ZINK_PROBE_VULKAN_INSTANCE_FAILURE:" << result << "\n";
        return 2;
    }
    std::uint32_t n=0;
    result = vkEnumeratePhysicalDevices(instance,&n,nullptr);
    if (result != VK_SUCCESS || n!=1) {
        std::cerr << "ARE_ZINK_PROBE_DEVICE_ADMISSION_FAILURE:" << result << ":" << n << "\n";
        vkDestroyInstance(instance,nullptr);
        return 2;
    }
    VkPhysicalDevice physical{};
    result=vkEnumeratePhysicalDevices(instance,&n,&physical);
    if(result!=VK_SUCCESS || !physical) {
        std::cerr << "ARE_ZINK_PROBE_PHYSICAL_DEVICE_FAILURE:" << result << "\n";
        vkDestroyInstance(instance,nullptr);
        return 2;
    }
    VkPhysicalDeviceProperties props{};
    vkGetPhysicalDeviceProperties(physical,&props);
    const bool are_owned=props.deviceType==VK_PHYSICAL_DEVICE_TYPE_CPU &&
                         std::strstr(props.deviceName,"ARE SoftwareGPU")!=nullptr;
    if(!are_owned) {
        std::cerr << "ARE_ZINK_PROBE_REFUSED_NON_ARE_DEVICE\n";
        vkDestroyInstance(instance,nullptr);
        return 2;
    }
    VkPhysicalDeviceFeatures f{};
    vkGetPhysicalDeviceFeatures(physical,&f);
    std::vector<std::string> missing_features;
    if(!f.logicOp) missing_features.emplace_back("logicOp");
    if(!f.fillModeNonSolid) missing_features.emplace_back("fillModeNonSolid");
    if(!f.alphaToOne) missing_features.emplace_back("alphaToOne");
    if(!f.shaderClipDistance) missing_features.emplace_back("shaderClipDistance");
    if(!f.independentBlend) missing_features.emplace_back("independentBlend");
    std::uint32_t extn=0;
    result=vkEnumerateDeviceExtensionProperties(physical,nullptr,&extn,nullptr);
    if(result!=VK_SUCCESS) {
        std::cerr << "ARE_ZINK_PROBE_ENUMERATION_FAILURE:" << result << "\n";
        vkDestroyInstance(instance,nullptr);
        return 2;
    }
    std::vector<VkExtensionProperties> ext(extn);
    result=vkEnumerateDeviceExtensionProperties(physical,nullptr,&extn,ext.data());
    if(result!=VK_SUCCESS) {
        std::cerr << "ARE_ZINK_PROBE_EXTENSIONS_FAILURE:" << result << "\n";
        vkDestroyInstance(instance,nullptr);
        return 2;
    }
    std::set<std::string> advertised;
    for(std::uint32_t i=0;i<extn;i++) advertised.insert(ext[i].extensionName);
    std::vector<std::string> missing_extensions;
    for(const char* name:base_extensions) {
        if(!advertised.count(name)) missing_extensions.push_back(name);
    }
    if(!advertised.count("VK_EXT_robustness2") &&
       !advertised.count("VK_KHR_robustness2"))
        missing_extensions.emplace_back("VK_EXT_robustness2|VK_KHR_robustness2");
    if(!advertised.count("VK_EXT_scalar_block_layout") &&
       props.apiVersion<VK_API_VERSION_1_2)
        missing_extensions.emplace_back("VK_EXT_scalar_block_layout|Vulkan1.2");
    const bool gl21_ready =
        props.apiVersion >= VK_API_VERSION_1_0 &&
        missing_features.empty() && missing_extensions.empty();
    std::cout << "{\"protocol\":\"are.zink-capability-preflight.v1\","
              << "\"device\":";
    json_string(props.deviceName);
    std::cout << ",\"api_version\":{\"major\":"
              << VK_API_VERSION_MAJOR(props.apiVersion)
              << ",\"minor\":" << VK_API_VERSION_MINOR(props.apiVersion)
              << "},\"max_bound_descriptor_sets\":"
              << props.limits.maxBoundDescriptorSets
              << ",\"extensions_advertised\":";
    json_list(std::vector<std::string>(advertised.begin(),advertised.end()));
    std::cout << ",\"missing_gl21_features\":";
    json_list(missing_features);
    std::cout << ",\"missing_gl21_extensions\":";
    json_list(missing_extensions);
    std::cout << ",\"minimum_gl21_ready\":"
              << (gl21_ready?"true":"false")
              << ",\"gl45_and_heaven_verified\":false}\n";
    vkDestroyInstance(instance,nullptr);
    return gl21_ready?0:3;
}
