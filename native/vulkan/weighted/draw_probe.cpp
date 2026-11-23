// Standalone Vulkan application. Link only to the system loader.
#include <vulkan/vulkan.h>
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

static void check(VkResult value, const char* what) {
    if (value != VK_SUCCESS) throw std::runtime_error(std::string(what) + " failed: " + std::to_string(value));
}
#define CHECK(expr) check((expr), #expr)

static std::vector<uint32_t> readShader(const std::string& path) {
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    auto n = file.tellg();
    if (!file || n <= 0 || n > 1048576 || n % 4) throw std::runtime_error("Invalid shader file");
    std::vector<uint32_t> words(static_cast<size_t>(n)/4);
    file.seekg(0);
    if (!file.read(reinterpret_cast<char*>(words.data()), n)) throw std::runtime_error("Shader read failed");
    return words;
}

static void run(const std::string& dir, const std::string& output) {
    constexpr uint32_t width = 32, height = 24;
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.apiVersion = VK_API_VERSION_1_0;
    VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    ici.pApplicationInfo = &app;
    VkInstance instance{};
    CHECK(vkCreateInstance(&ici, nullptr, &instance));
    uint32_t n = 0;
    CHECK(vkEnumeratePhysicalDevices(instance, &n, nullptr));
    if (n != 1) throw std::runtime_error("Expected isolated ARE device");
    VkPhysicalDevice physical{};
    CHECK(vkEnumeratePhysicalDevices(instance, &n, &physical));
    VkPhysicalDeviceProperties props{};
    vkGetPhysicalDeviceProperties(physical, &props);
    if (std::strcmp(props.deviceName, "ARE SoftwareGPU (experimental headless CPU)") ||
        props.deviceType != VK_PHYSICAL_DEVICE_TYPE_CPU) throw std::runtime_error("Wrong device identity");
    float priority = 1;
    VkDeviceQueueCreateInfo qi{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    qi.queueCount = 1; qi.pQueuePriorities = &priority;
    VkDeviceCreateInfo di{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    di.queueCreateInfoCount = 1; di.pQueueCreateInfos = &qi;
    VkDevice device{};
    CHECK(vkCreateDevice(physical, &di, nullptr, &device));
    VkQueue queue{};
    vkGetDeviceQueue(device, 0, 0, &queue);
    auto allocate = [&](VkMemoryRequirements req) {
        VkMemoryAllocateInfo ma{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
        ma.allocationSize = req.size;
        if (!(req.memoryTypeBits & 1)) throw std::runtime_error("Unexpected memory type");
        VkDeviceMemory mem{};
        CHECK(vkAllocateMemory(device, &ma, nullptr, &mem));
        return mem;
    };
    // Spatially asymmetric triangle. Interpolate RGB at each sample.
    const float vertices[][6] = {
        {-1,-1,.5f, 1,0,0},{1,-1,.5f, 0,1,0},{-1,1,.5f, 0,0,1}};
    VkBufferCreateInfo bi{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bi.size = sizeof(vertices); bi.usage = VK_BUFFER_USAGE_VERTEX_BUFFER_BIT;
    VkBuffer vb{};
    CHECK(vkCreateBuffer(device, &bi, nullptr, &vb));
    VkMemoryRequirements req{};
    vkGetBufferMemoryRequirements(device, vb, &req);
    auto vm = allocate(req);
    CHECK(vkBindBufferMemory(device, vb, vm, 0));
    void* mapped{};
    CHECK(vkMapMemory(device, vm, 0, sizeof(vertices), 0, &mapped));
    std::memcpy(mapped, vertices, sizeof(vertices));
    vkUnmapMemory(device, vm);

    VkFormat formats[] = {VK_FORMAT_R8G8B8A8_UNORM, VK_FORMAT_D32_SFLOAT};
    VkImage images[2]{}; VkImageView views[2]{}; VkDeviceMemory memory[2]{};
    VkAttachmentDescription attach[2]{};
    for (int i=0; i<2; ++i) {
        VkImageCreateInfo im{VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO};
        im.imageType = VK_IMAGE_TYPE_2D; im.format = formats[i]; im.extent = {width,height,1};
        im.mipLevels = im.arrayLayers = 1; im.samples = VK_SAMPLE_COUNT_1_BIT;
        im.tiling = VK_IMAGE_TILING_LINEAR;
        im.usage = i ? VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT : VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
        CHECK(vkCreateImage(device,&im,nullptr,&images[i]));
        vkGetImageMemoryRequirements(device,images[i],&req);
        memory[i] = allocate(req);
        CHECK(vkBindImageMemory(device,images[i],memory[i],0));
        VkImageViewCreateInfo vi{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
        vi.image = images[i]; vi.format = im.format; vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
        vi.subresourceRange = {i ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
        CHECK(vkCreateImageView(device,&vi,nullptr,&views[i]));
        attach[i].format = formats[i]; attach[i].samples = VK_SAMPLE_COUNT_1_BIT;
        attach[i].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR; attach[i].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
        attach[i].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
        attach[i].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
        attach[i].finalLayout = VK_IMAGE_LAYOUT_GENERAL;
    }
    VkAttachmentReference color{0,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL}, depth{1,VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL};
    VkSubpassDescription sub{}; sub.colorAttachmentCount = 1; sub.pColorAttachments = &color;
    sub.pDepthStencilAttachment = &depth; sub.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    VkRenderPassCreateInfo ri{VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO};
    ri.attachmentCount = 2; ri.pAttachments = attach; ri.subpassCount = 1; ri.pSubpasses = &sub;
    VkRenderPass pass{};
    CHECK(vkCreateRenderPass(device,&ri,nullptr,&pass));
    VkFramebufferCreateInfo fi{VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO};
    fi.renderPass = pass; fi.attachmentCount = 2; fi.pAttachments = views; fi.width=width; fi.height=height; fi.layers=1;
    VkFramebuffer fb{};
    CHECK(vkCreateFramebuffer(device,&fi,nullptr,&fb));
    VkShaderModule modules[2]{};
    VkPipelineShaderStageCreateInfo stages[2]{};
    for (int i=0;i<2;++i) {
        auto code = readShader(dir + (i ? "/frag.spv" : "/vert.spv"));
        VkShaderModuleCreateInfo sm{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
        sm.codeSize = code.size()*4; sm.pCode = code.data();
        CHECK(vkCreateShaderModule(device,&sm,nullptr,&modules[i]));
        stages[i].sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        stages[i].stage=i ? VK_SHADER_STAGE_FRAGMENT_BIT : VK_SHADER_STAGE_VERTEX_BIT;
        stages[i].module=modules[i]; stages[i].pName="main";
    }
    VkPipelineLayoutCreateInfo li{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};
    VkPipelineLayout layout{};
    CHECK(vkCreatePipelineLayout(device,&li,nullptr,&layout));
    VkVertexInputBindingDescription binding{0,24,VK_VERTEX_INPUT_RATE_VERTEX};
    VkVertexInputAttributeDescription attr[]={{0,0,VK_FORMAT_R32G32B32_SFLOAT,0},{1,0,VK_FORMAT_R32G32B32_SFLOAT,12}};
    VkPipelineVertexInputStateCreateInfo vin{VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    vin.vertexBindingDescriptionCount=1; vin.pVertexBindingDescriptions=&binding;
    vin.vertexAttributeDescriptionCount=2; vin.pVertexAttributeDescriptions=attr;
    VkPipelineInputAssemblyStateCreateInfo ia{VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO};
    ia.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    VkViewport vp{0,0,width,height,0,1}; VkRect2D rect{{0,0},{width,height}};
    VkPipelineViewportStateCreateInfo vs{VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO};
    vs.viewportCount=vs.scissorCount=1; vs.pViewports=&vp; vs.pScissors=&rect;
    VkPipelineRasterizationStateCreateInfo rs{VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO};
    rs.polygonMode=VK_POLYGON_MODE_FILL; rs.lineWidth=1;
    VkPipelineMultisampleStateCreateInfo ms{VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO};
    ms.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT;
    VkPipelineDepthStencilStateCreateInfo ds{VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO};
    ds.depthTestEnable=ds.depthWriteEnable=VK_TRUE; ds.depthCompareOp=VK_COMPARE_OP_LESS;
    VkPipelineColorBlendAttachmentState blend{}; blend.colorWriteMask=15;
    VkPipelineColorBlendStateCreateInfo bs{VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO};
    bs.attachmentCount=1; bs.pAttachments=&blend;
    VkGraphicsPipelineCreateInfo gi{VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO};
    gi.stageCount=2; gi.pStages=stages; gi.pVertexInputState=&vin; gi.pInputAssemblyState=&ia;
    gi.pViewportState=&vs; gi.pRasterizationState=&rs; gi.pMultisampleState=&ms;
    gi.pDepthStencilState=&ds; gi.pColorBlendState=&bs; gi.layout=layout; gi.renderPass=pass;
    VkPipeline pipeline{};
    CHECK(vkCreateGraphicsPipelines(device,VK_NULL_HANDLE,1,&gi,nullptr,&pipeline));

    VkCommandPoolCreateInfo pi{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    VkCommandPool pool{};
    CHECK(vkCreateCommandPool(device,&pi,nullptr,&pool));
    VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    ai.commandPool=pool; ai.commandBufferCount=1;
    VkCommandBuffer cmd{};
    CHECK(vkAllocateCommandBuffers(device,&ai,&cmd));
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    CHECK(vkBeginCommandBuffer(cmd,&begin));
    VkClearValue clears[2]{};
    clears[0].color.float32[3]=1; clears[1].depthStencil.depth=1;
    VkRenderPassBeginInfo render{VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};
    render.renderPass=pass; render.framebuffer=fb; render.renderArea=rect;
    render.clearValueCount=2; render.pClearValues=clears;
    vkCmdBeginRenderPass(cmd,&render,VK_SUBPASS_CONTENTS_INLINE);
    vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_GRAPHICS,pipeline);
    VkDeviceSize offset=0;
    vkCmdBindVertexBuffers(cmd,0,1,&vb,&offset);
    for (int i=0;i<32;++i) vkCmdDraw(cmd,3,1,0,0);
    vkCmdEndRenderPass(cmd);
    VkMemoryBarrier barrier{VK_STRUCTURE_TYPE_MEMORY_BARRIER};
    barrier.srcAccessMask=VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT|VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    barrier.dstAccessMask=VK_ACCESS_HOST_READ_BIT;
    vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_ALL_GRAPHICS_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,
                         1,&barrier,0,nullptr,0,nullptr);
    CHECK(vkEndCommandBuffer(cmd));
    VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO}; submit.commandBufferCount=1; submit.pCommandBuffers=&cmd;
    VkFenceCreateInfo fenceInfo{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    VkFence fence{};
    CHECK(vkCreateFence(device,&fenceInfo,nullptr,&fence));
    if (vkGetFenceStatus(device,fence) != VK_NOT_READY ||
        vkWaitForFences(device,1,&fence,VK_TRUE,0) != VK_TIMEOUT)
        throw std::runtime_error("Fence signaled before submit");
    CHECK(vkQueueSubmit(queue,1,&submit,fence));
    CHECK(vkWaitForFences(device,1,&fence,VK_TRUE,1000000000));
    vkDestroyFence(device,fence,nullptr);
    CHECK(vkQueueWaitIdle(queue));
    for (int i=0;i<2;++i) {
        VkImageSubresource subresource{i ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT,0,0};
        VkSubresourceLayout sublayout{};
        vkGetImageSubresourceLayout(device,images[i],&subresource,&sublayout);
        CHECK(vkMapMemory(device,memory[i],0,VK_WHOLE_SIZE,0,&mapped));
        std::ofstream file(output + (i ? ".depth" : ".rgba"), std::ios::binary);
        for (uint32_t y=0;y<height;++y)
            file.write(static_cast<const char*>(mapped)+sublayout.offset+y*sublayout.rowPitch,width*4);
        file.close();
        if (!file) throw std::runtime_error("frame readback write failed");
        vkUnmapMemory(device,memory[i]);
    }
    vkDestroyCommandPool(device,pool,nullptr);
    vkDestroyPipeline(device,pipeline,nullptr);
    vkDestroyPipelineLayout(device,layout,nullptr);
    vkDestroyFramebuffer(device,fb,nullptr);
    vkDestroyRenderPass(device,pass,nullptr);
    for (int i=0;i<2;++i) {
        vkDestroyShaderModule(device,modules[i],nullptr);
        vkDestroyImageView(device,views[i],nullptr);
        vkDestroyImage(device,images[i],nullptr);
        vkFreeMemory(device,memory[i],nullptr);
    }
    vkDestroyBuffer(device,vb,nullptr); vkFreeMemory(device,vm,nullptr);
    vkDestroyDevice(device,nullptr); vkDestroyInstance(instance,nullptr);
}
int main(int argc, char** argv) {
    if (argc != 3) return 2;
    try { run(argv[1],argv[2]); return 0; }
    catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
