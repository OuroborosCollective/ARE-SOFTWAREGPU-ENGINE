// Genuine standalone Vulkan Loader -> ARE CPU ICD vkCmdCopyBuffer client.
// Positive transfer, actual mapped bytes, and invalid-range rejection.
#include <vulkan/vulkan.h>
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

static void check(VkResult result, const char* operation) {
    if (result != VK_SUCCESS)
        throw std::runtime_error(std::string(operation) + " returned " + std::to_string(result));
}
#define CHECK(expr) check((expr), #expr)
static void require(bool pass, const char* operation) {
    if (!pass) throw std::runtime_error(operation);
}

static void run(const char* filename) {
    VkApplicationInfo app{};
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.apiVersion = VK_API_VERSION_1_0;
    VkInstanceCreateInfo ci{};
    ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    ci.pApplicationInfo = &app;
    VkInstance instance{};
    CHECK(vkCreateInstance(&ci, nullptr, &instance));
    std::uint32_t count = 0;
    CHECK(vkEnumeratePhysicalDevices(instance, &count, nullptr));
    require(count == 1, "Expected exactly one isolated ARE Vulkan device");
    VkPhysicalDevice physical{};
    CHECK(vkEnumeratePhysicalDevices(instance, &count, &physical));
    VkPhysicalDeviceProperties properties{};
    vkGetPhysicalDeviceProperties(physical, &properties);
    require(properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU &&
            std::strcmp(properties.deviceName, "ARE SoftwareGPU (experimental headless CPU)") == 0,
            "Non-ARE Vulkan device rejected");
    float priority = 1.0f;
    VkDeviceQueueCreateInfo qci{};
    qci.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    qci.queueFamilyIndex = 0;
    qci.queueCount = 1;
    qci.pQueuePriorities = &priority;
    VkDeviceCreateInfo dci{};
    dci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    VkDevice device{};
    CHECK(vkCreateDevice(physical, &dci, nullptr, &device));
    auto copy = reinterpret_cast<PFN_vkCmdCopyBuffer>(
        vkGetDeviceProcAddr(device, "vkCmdCopyBuffer"));
    require(copy != nullptr, "ARE Vulkan ICD lacks real vkCmdCopyBuffer dispatch");
    VkQueue queue{};
    vkGetDeviceQueue(device, 0, 0, &queue);
    require(queue != VK_NULL_HANDLE, "Missing actual Vulkan queue");
    VkBuffer source{}, destination{};
    VkDeviceMemory source_memory{}, destination_memory{};
    auto make_buffer = [&](VkBufferUsageFlags usage, VkBuffer* buffer,
                           VkDeviceMemory* memory) {
        VkBufferCreateInfo bi{};
        bi.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
        bi.size = 64;
        bi.usage = usage;
        bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        CHECK(vkCreateBuffer(device, &bi, nullptr, buffer));
        VkMemoryRequirements req{};
        vkGetBufferMemoryRequirements(device, *buffer, &req);
        require(req.memoryTypeBits & 1, "ARE host-coherent memory type is missing");
        VkMemoryAllocateInfo mi{};
        mi.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        mi.allocationSize = req.size;
        mi.memoryTypeIndex = 0;
        CHECK(vkAllocateMemory(device, &mi, nullptr, memory));
        CHECK(vkBindBufferMemory(device, *buffer, *memory, 0));
    };
    make_buffer(VK_BUFFER_USAGE_TRANSFER_SRC_BIT, &source, &source_memory);
    make_buffer(VK_BUFFER_USAGE_TRANSFER_DST_BIT, &destination, &destination_memory);
    std::array<std::uint8_t,64> original{};
    for (std::size_t i = 0; i < original.size(); ++i)
        original[i] = static_cast<std::uint8_t>((i*37+11)%256);
    void* mapped{};
    CHECK(vkMapMemory(device, source_memory, 0, VK_WHOLE_SIZE, 0, &mapped));
    std::memcpy(mapped, original.data(), original.size());
    vkUnmapMemory(device, source_memory);

    VkCommandPoolCreateInfo pool_info{};
    pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pool_info.queueFamilyIndex = 0;
    VkCommandPool pool{};
    CHECK(vkCreateCommandPool(device, &pool_info, nullptr, &pool));
    VkCommandBufferAllocateInfo ai{};
    ai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    ai.commandPool = pool;
    ai.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    ai.commandBufferCount = 2;
    VkCommandBuffer cb[2]{};
    CHECK(vkAllocateCommandBuffers(device, &ai, cb));
    VkCommandBufferBeginInfo bi{};
    bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    CHECK(vkBeginCommandBuffer(cb[0], &bi));
    VkBufferCopy range{};
    range.srcOffset = 4;
    range.dstOffset = 12;
    range.size = 20;
    copy(cb[0], source, destination, 1, &range);
    CHECK(vkEndCommandBuffer(cb[0]));
    VkSubmitInfo si{};
    si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    si.commandBufferCount = 1;
    si.pCommandBuffers = cb;
    CHECK(vkQueueSubmit(queue, 1, &si, VK_NULL_HANDLE));
    CHECK(vkQueueWaitIdle(queue));
    std::array<std::uint8_t,64> readback{};
    CHECK(vkMapMemory(device, destination_memory, 0, VK_WHOLE_SIZE, 0, &mapped));
    std::memcpy(readback.data(), mapped, readback.size());
    vkUnmapMemory(device, destination_memory);
    std::array<std::uint8_t,64> oracle{};
    for (std::size_t i=0;i<20;++i) oracle[12+i] = original[4+i];
    require(readback == oracle, "ARE buffer copy produced wrong live mapped bytes");

    CHECK(vkBeginCommandBuffer(cb[1], &bi));
    VkBufferCopy bad{};
    bad.srcOffset = 60;
    bad.dstOffset = 0;
    bad.size = 16;  // exceeds source capacity and must invalidate recording
    copy(cb[1], source, destination, 1, &bad);
    const VkResult invalid_end = vkEndCommandBuffer(cb[1]);
    require(invalid_end != VK_SUCCESS, "Invalid VkBufferCopy was silently accepted");

    VkBuffer unsupported{};
    VkBufferCreateInfo bad_info{};
    bad_info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bad_info.size = 64;
    bad_info.usage = VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT;  // not yet supported
    bad_info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    const VkResult unknown_usage = vkCreateBuffer(device,&bad_info,nullptr,&unsupported);
    require(unknown_usage != VK_SUCCESS, "Unsupported buffer usage was falsely advertised");

    std::ofstream result(filename, std::ios::binary | std::ios::trunc);
    require(result.good(), "Cannot create real buffer-copy output");
    result.write(reinterpret_cast<const char*>(readback.data()),readback.size());
    result.flush();
    require(result.good(), "Cannot write actual mapped buffer bytes");
    std::cout << "ARE_NATIVE_VK_CMD_COPY_BUFFER_PASS copied=20 output=64 "
              << "invalid_end=" << invalid_end << " unknown_usage=" << unknown_usage << "\n";
    vkDestroyCommandPool(device,pool,nullptr);
    vkDestroyBuffer(device,source,nullptr);
    vkDestroyBuffer(device,destination,nullptr);
    vkFreeMemory(device,source_memory,nullptr);
    vkFreeMemory(device,destination_memory,nullptr);
    vkDestroyDevice(device,nullptr);
    vkDestroyInstance(instance,nullptr);
}
int main(int argc,char** argv) {
    if (argc!=2) return 2;
    try {run(argv[1]);return 0;}
    catch(const std::exception& e) {std::cerr << e.what() << "\n";return 3;}
}
