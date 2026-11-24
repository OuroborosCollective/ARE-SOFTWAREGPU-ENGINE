// Standalone Vulkan application. Link only to the system loader.
#define VK_USE_PLATFORM_XCB_KHR 1
#include <vulkan/vulkan.h>
#include <xcb/xcb.h>
#include <cstdlib>
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

static void run(const std::string& dir, const std::string& output, bool alternate) {
    constexpr uint32_t width = 32, height = 24;
    VkApplicationInfo app{}; app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.apiVersion = VK_API_VERSION_1_0;
    xcb_connection_t* xc = xcb_connect(nullptr, nullptr);
    if (!xc || xcb_connection_has_error(xc)) throw std::runtime_error("No real XCB connection");
    auto* screen = xcb_setup_roots_iterator(xcb_get_setup(xc)).data;
    if (!screen) throw std::runtime_error("No XCB root screen");
    const auto window = xcb_generate_id(xc);
    const uint32_t wvalues[] = {screen->black_pixel,XCB_EVENT_MASK_STRUCTURE_NOTIFY};
    auto ck = xcb_create_window_checked(xc,screen->root_depth,window,screen->root,
        0,0,width,height,0,XCB_WINDOW_CLASS_INPUT_OUTPUT,screen->root_visual,
        XCB_CW_BACK_PIXEL|XCB_CW_EVENT_MASK,wvalues);
    auto* error=xcb_request_check(xc,ck);
    if (error) {std::free(error);throw std::runtime_error("XCB window create failed");}
    ck=xcb_map_window_checked(xc,window);
    error=xcb_request_check(xc,ck);
    if (error) {std::free(error);throw std::runtime_error("XCB window map failed");}
    xcb_flush(xc);
    const char* instance_extensions[]={VK_KHR_SURFACE_EXTENSION_NAME,
                                       VK_KHR_XCB_SURFACE_EXTENSION_NAME};
    VkInstanceCreateInfo ici{}; ici.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    ici.pApplicationInfo = &app;
    ici.enabledExtensionCount=2;
    ici.ppEnabledExtensionNames=instance_extensions;
    VkInstance instance{};
    CHECK(vkCreateInstance(&ici, nullptr, &instance));
    auto createSurface = reinterpret_cast<PFN_vkCreateXcbSurfaceKHR>(
        vkGetInstanceProcAddr(instance,"vkCreateXcbSurfaceKHR"));
    auto destroySurface = reinterpret_cast<PFN_vkDestroySurfaceKHR>(
        vkGetInstanceProcAddr(instance,"vkDestroySurfaceKHR"));
    if (!createSurface || !destroySurface) throw std::runtime_error("No surface Vulkan dispatch");
    VkXcbSurfaceCreateInfoKHR surfaceInfo{}; surfaceInfo.sType = VK_STRUCTURE_TYPE_XCB_SURFACE_CREATE_INFO_KHR;
    surfaceInfo.connection=xc;
    surfaceInfo.window=window;
    VkSurfaceKHR surface{};
    CHECK(createSurface(instance,&surfaceInfo,nullptr,&surface));
    uint32_t n = 0;
    CHECK(vkEnumeratePhysicalDevices(instance, &n, nullptr));
    if (n != 1) throw std::runtime_error("Expected isolated ARE device");
    VkPhysicalDevice physical{};
    CHECK(vkEnumeratePhysicalDevices(instance, &n, &physical));
    VkPhysicalDeviceProperties props{};
    vkGetPhysicalDeviceProperties(physical, &props);
    if (std::strcmp(props.deviceName, "ARE SoftwareGPU (experimental headless CPU)") ||
        props.deviceType != VK_PHYSICAL_DEVICE_TYPE_CPU) throw std::runtime_error("Wrong device identity");
    if (props.limits.maxDrawIndexedIndexValue != 0x00ffffffu)
        throw std::runtime_error("Wrong advertised indexed-draw limit");
    float priority = 1;
    VkDeviceQueueCreateInfo qi{}; qi.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    qi.queueCount = 1; qi.pQueuePriorities = &priority;
    VkDeviceCreateInfo di{}; di.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    di.queueCreateInfoCount = 1; di.pQueueCreateInfos = &qi;
    const char* ext[]={VK_KHR_SWAPCHAIN_EXTENSION_NAME};
    di.enabledExtensionCount=1; di.ppEnabledExtensionNames=ext;
    VkDevice device{};
    CHECK(vkCreateDevice(physical, &di, nullptr, &device));
    auto createSwapchain=reinterpret_cast<PFN_vkCreateSwapchainKHR>(
        vkGetDeviceProcAddr(device,"vkCreateSwapchainKHR"));
    auto destroySwapchain=reinterpret_cast<PFN_vkDestroySwapchainKHR>(
        vkGetDeviceProcAddr(device,"vkDestroySwapchainKHR"));
    auto swapchainImages=reinterpret_cast<PFN_vkGetSwapchainImagesKHR>(
        vkGetDeviceProcAddr(device,"vkGetSwapchainImagesKHR"));
    auto acquireNext=reinterpret_cast<PFN_vkAcquireNextImageKHR>(
        vkGetDeviceProcAddr(device,"vkAcquireNextImageKHR"));
    auto present=reinterpret_cast<PFN_vkQueuePresentKHR>(
        vkGetDeviceProcAddr(device,"vkQueuePresentKHR"));
    if(!createSwapchain||!destroySwapchain||!swapchainImages||!acquireNext||!present)
        throw std::runtime_error("Missing Vulkan swapchain dispatch");
    VkSwapchainCreateInfoKHR sci{}; sci.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR;
    sci.surface=surface; sci.minImageCount=2;
    sci.imageFormat=VK_FORMAT_R8G8B8A8_UNORM;
    sci.imageColorSpace=VK_COLOR_SPACE_SRGB_NONLINEAR_KHR;
    sci.imageExtent={width,height}; sci.imageArrayLayers=1;
    sci.imageUsage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
    sci.imageSharingMode=VK_SHARING_MODE_EXCLUSIVE;
    sci.preTransform=VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR;
    sci.compositeAlpha=VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    sci.presentMode=VK_PRESENT_MODE_FIFO_KHR; sci.clipped=VK_TRUE;
    VkSwapchainKHR swapchain{};
    CHECK(createSwapchain(device,&sci,nullptr,&swapchain));
    uint32_t swapCount=0;
    CHECK(swapchainImages(device,swapchain,&swapCount,nullptr));
    if(swapCount!=2) throw std::runtime_error("Expected exactly two real Vulkan images");
    VkImage swapImages[2]{};
    CHECK(swapchainImages(device,swapchain,&swapCount,swapImages));
    VkSemaphoreCreateInfo sei{}; sei.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
    VkSemaphore imageReady{},drawFinished{};
    CHECK(vkCreateSemaphore(device,&sei,nullptr,&imageReady));
    CHECK(vkCreateSemaphore(device,&sei,nullptr,&drawFinished));
    uint32_t index=0;
    CHECK(acquireNext(device,swapchain,0,imageReady,VK_NULL_HANDLE,&index));
    if(index>=2) throw std::runtime_error("Invalid acquired image index");
    VkPresentInfoKHR early{}; early.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
    early.swapchainCount=1; early.pSwapchains=&swapchain; early.pImageIndices=&index;
    VkQueue queue{};
    vkGetDeviceQueue(device, 0, 0, &queue);
    if(present(queue,&early)==VK_SUCCESS)
        throw std::runtime_error("Present-before-render was accepted");
    auto allocate = [&](VkMemoryRequirements req) {
        VkMemoryAllocateInfo ma{}; ma.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        ma.allocationSize = req.size;
        if (!(req.memoryTypeBits & 1)) throw std::runtime_error("Unexpected memory type");
        VkDeviceMemory mem{};
        CHECK(vkAllocateMemory(device, &ma, nullptr, &mem));
        return mem;
    };
    // Spatially asymmetric triangle. Interpolate RGB at each sample.
    float vertices[][6] = {
        {0,0,.5f, 0,0,0}, {-1,1,.5f, 0,0,1},
        {-1,-1,.5f, 1,0,0}, {1,-1,.5f, 0,1,0}};
    if (alternate) {
        // Rotate RGB components without changing geometry, coverage or depth.
        for (auto& v : vertices) {
            const float r = v[3],g = v[4],b = v[5];
            v[3] = b; v[4] = r; v[5] = g;
        }
    }
    // The very same combined Index|Vertex usage requested by Unity 6.
    // This native probe genuinely binds and draws those indices on ARE.
    // Both unsigned index formats use a valid negative signed base vertex.
    const std::uint16_t indices16[] = {3, 4, 2};
    const std::uint32_t indices32[] = {3, 4, 2};
    const VkDeviceSize indexBytes = alternate ? sizeof(indices32) : sizeof(indices16);
    VkBufferCreateInfo bi{}; bi.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bi.size = sizeof(vertices) + indexBytes;
    bi.usage = VK_BUFFER_USAGE_VERTEX_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT;
    VkBuffer vb{};
    CHECK(vkCreateBuffer(device, &bi, nullptr, &vb));
    VkMemoryRequirements req{};
    vkGetBufferMemoryRequirements(device, vb, &req);
    auto vm = allocate(req);
    CHECK(vkBindBufferMemory(device, vb, vm, 0));
    void* mapped{};
    CHECK(vkMapMemory(device, vm, 0, sizeof(vertices) + indexBytes, 0, &mapped));
    std::memcpy(mapped, vertices, sizeof(vertices));
    std::memset(static_cast<char*>(mapped) + sizeof(vertices), 0, indexBytes);
    vkUnmapMemory(device, vm);

    VkFormat formats[] = {VK_FORMAT_R8G8B8A8_UNORM, VK_FORMAT_D32_SFLOAT};
    VkImage images[2]{swapImages[index],VK_NULL_HANDLE};
    VkImageView views[2]{}; VkDeviceMemory memory[2]{};
    VkAttachmentDescription attach[2]{};
    for (int i=0; i<2; ++i) {
        VkImageCreateInfo im{}; im.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
        im.imageType = VK_IMAGE_TYPE_2D; im.format = formats[i]; im.extent = {width,height,1};
        im.mipLevels = im.arrayLayers = 1; im.samples = VK_SAMPLE_COUNT_1_BIT;
        im.tiling = VK_IMAGE_TILING_LINEAR;
        im.usage = i ? VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT : VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
        if (i==1) {
            CHECK(vkCreateImage(device,&im,nullptr,&images[i]));
            vkGetImageMemoryRequirements(device,images[i],&req);
            memory[i] = allocate(req);
            CHECK(vkBindImageMemory(device,images[i],memory[i],0));
        }
        VkImageViewCreateInfo vi{}; vi.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
        vi.image = images[i]; vi.format = im.format; vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
        vi.subresourceRange = {i ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
        CHECK(vkCreateImageView(device,&vi,nullptr,&views[i]));
        attach[i].format = formats[i]; attach[i].samples = VK_SAMPLE_COUNT_1_BIT;
        attach[i].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR; attach[i].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
        attach[i].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
        attach[i].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
        attach[i].finalLayout = i ? VK_IMAGE_LAYOUT_GENERAL : VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
    }
    VkAttachmentReference color{0,VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL}, depth{1,VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL};
    VkSubpassDescription sub{}; sub.colorAttachmentCount = 1; sub.pColorAttachments = &color;
    sub.pDepthStencilAttachment = &depth; sub.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    VkRenderPassCreateInfo ri{}; ri.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    ri.attachmentCount = 2; ri.pAttachments = attach; ri.subpassCount = 1; ri.pSubpasses = &sub;
    VkRenderPass pass{};
    CHECK(vkCreateRenderPass(device,&ri,nullptr,&pass));
    VkFramebufferCreateInfo fi{}; fi.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
    fi.renderPass = pass; fi.attachmentCount = 2; fi.pAttachments = views; fi.width=width; fi.height=height; fi.layers=1;
    VkFramebuffer fb{};
    CHECK(vkCreateFramebuffer(device,&fi,nullptr,&fb));
    VkShaderModule modules[2]{};
    VkPipelineShaderStageCreateInfo stages[2]{};
    for (int i=0;i<2;++i) {
        auto code = readShader(dir + (i ? "/frag.spv" : "/vert.spv"));
        VkShaderModuleCreateInfo sm{}; sm.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        sm.codeSize = code.size()*4; sm.pCode = code.data();
        CHECK(vkCreateShaderModule(device,&sm,nullptr,&modules[i]));
        stages[i].sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        stages[i].stage=i ? VK_SHADER_STAGE_FRAGMENT_BIT : VK_SHADER_STAGE_VERTEX_BIT;
        stages[i].module=modules[i]; stages[i].pName="main";
    }
    VkPipelineLayoutCreateInfo li{}; li.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    VkPipelineLayout layout{};
    CHECK(vkCreatePipelineLayout(device,&li,nullptr,&layout));
    VkVertexInputBindingDescription binding{0,24,VK_VERTEX_INPUT_RATE_VERTEX};
    VkVertexInputAttributeDescription attr[]={{0,0,VK_FORMAT_R32G32B32_SFLOAT,0},{1,0,VK_FORMAT_R32G32B32_SFLOAT,12}};
    VkPipelineVertexInputStateCreateInfo vin{}; vin.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
    vin.vertexBindingDescriptionCount=1; vin.pVertexBindingDescriptions=&binding;
    vin.vertexAttributeDescriptionCount=2; vin.pVertexAttributeDescriptions=attr;
    VkPipelineInputAssemblyStateCreateInfo ia{}; ia.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    ia.topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    VkViewport vp{0,0,width,height,0,1}; VkRect2D rect{{0,0},{width,height}};
    VkPipelineViewportStateCreateInfo vs{}; vs.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    vs.viewportCount=vs.scissorCount=1; vs.pViewports=&vp; vs.pScissors=&rect;
    VkPipelineRasterizationStateCreateInfo rs{}; rs.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rs.polygonMode=VK_POLYGON_MODE_FILL; rs.lineWidth=1;
    VkPipelineMultisampleStateCreateInfo ms{}; ms.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    ms.rasterizationSamples=VK_SAMPLE_COUNT_1_BIT;
    VkPipelineDepthStencilStateCreateInfo ds{}; ds.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO;
    ds.depthTestEnable=ds.depthWriteEnable=VK_TRUE; ds.depthCompareOp=VK_COMPARE_OP_LESS;
    VkPipelineColorBlendAttachmentState blend{}; blend.colorWriteMask=15;
    VkPipelineColorBlendStateCreateInfo bs{}; bs.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    bs.attachmentCount=1; bs.pAttachments=&blend;
    VkGraphicsPipelineCreateInfo gi{}; gi.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    gi.stageCount=2; gi.pStages=stages; gi.pVertexInputState=&vin; gi.pInputAssemblyState=&ia;
    gi.pViewportState=&vs; gi.pRasterizationState=&rs; gi.pMultisampleState=&ms;
    gi.pDepthStencilState=&ds; gi.pColorBlendState=&bs; gi.layout=layout; gi.renderPass=pass;
    VkPipeline pipeline{};
    CHECK(vkCreateGraphicsPipelines(device,VK_NULL_HANDLE,1,&gi,nullptr,&pipeline));

    VkCommandPoolCreateInfo pi{}; pi.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    VkCommandPool pool{};
    CHECK(vkCreateCommandPool(device,&pi,nullptr,&pool));
    VkCommandBufferAllocateInfo ai{}; ai.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    ai.commandPool=pool; ai.commandBufferCount=1;
    VkCommandBuffer cmd{};
    CHECK(vkAllocateCommandBuffers(device,&ai,&cmd));
    VkCommandBufferBeginInfo begin{}; begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    CHECK(vkBeginCommandBuffer(cmd,&begin));
    VkClearValue clears[2]{};
    clears[0].color.float32[3]=1; clears[1].depthStencil.depth=1;
    VkRenderPassBeginInfo render{}; render.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    render.renderPass=pass; render.framebuffer=fb; render.renderArea=rect;
    render.clearValueCount=2; render.pClearValues=clears;
    vkCmdBeginRenderPass(cmd,&render,VK_SUBPASS_CONTENTS_INLINE);
    vkCmdBindPipeline(cmd,VK_PIPELINE_BIND_POINT_GRAPHICS,pipeline);
    VkDeviceSize offset=0;
    vkCmdBindVertexBuffers(cmd,0,1,&vb,&offset);
    vkCmdBindIndexBuffer(cmd, vb, sizeof(vertices),
                         alternate ? VK_INDEX_TYPE_UINT32 : VK_INDEX_TYPE_UINT16);
    for (int i=0;i<32;++i) vkCmdDrawIndexed(cmd,3,1,0,-1,0);
    vkCmdEndRenderPass(cmd);
    VkMemoryBarrier barrier{}; barrier.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER;
    barrier.srcAccessMask=VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT|VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;
    barrier.dstAccessMask=VK_ACCESS_HOST_READ_BIT;
    vkCmdPipelineBarrier(cmd,VK_PIPELINE_STAGE_ALL_GRAPHICS_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,
                         1,&barrier,0,nullptr,0,nullptr);
    CHECK(vkEndCommandBuffer(cmd));
    VkSubmitInfo submit{}; submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount=1; submit.pCommandBuffers=&cmd;
    const VkPipelineStageFlags waitStage=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    submit.waitSemaphoreCount=1; submit.pWaitSemaphores=&imageReady;
    submit.pWaitDstStageMask=&waitStage;
    submit.signalSemaphoreCount=1; submit.pSignalSemaphores=&drawFinished;
    VkFenceCreateInfo fenceInfo{}; fenceInfo.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    VkFence fence{};
    CHECK(vkCreateFence(device,&fenceInfo,nullptr,&fence));
    if (vkGetFenceStatus(device,fence) != VK_NOT_READY ||
        vkWaitForFences(device,1,&fence,VK_TRUE,0) != VK_TIMEOUT)
        throw std::runtime_error("Fence signaled before submit");
    // Host-coherent index writes after recording must be observed at submission.
    CHECK(vkMapMemory(device,vm,0,bi.size,0,&mapped));
    std::memcpy(static_cast<char*>(mapped) + sizeof(vertices),
                alternate ? static_cast<const void*>(indices32) : static_cast<const void*>(indices16),
                indexBytes);
    vkUnmapMemory(device,vm);
    CHECK(vkQueueSubmit(queue,1,&submit,fence));
    CHECK(vkWaitForFences(device,1,&fence,VK_TRUE,1000000000));
    vkDestroyFence(device,fence,nullptr);
    CHECK(vkQueueWaitIdle(queue));
    VkPresentInfoKHR pi2{}; pi2.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
    pi2.waitSemaphoreCount=1;pi2.pWaitSemaphores=&drawFinished;
    pi2.swapchainCount=1;pi2.pSwapchains=&swapchain;pi2.pImageIndices=&index;
    CHECK(present(queue,&pi2));
    for (int i=0;i<2;++i) {
        VkImageSubresource subresource{i ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT,0,0};
        VkSubresourceLayout sublayout{};
        vkGetImageSubresourceLayout(device,images[i],&subresource,&sublayout);
        std::ofstream file(output + (i ? ".depth" : ".rgba"), std::ios::binary);
        if (i==0) {
            xcb_generic_error_t* readerror=nullptr;
            auto* reply=xcb_get_image_reply(xc,xcb_get_image(xc,XCB_IMAGE_FORMAT_Z_PIXMAP,
                window,0,0,width,height,0x00ffffffu),&readerror);
            if(readerror) {std::free(readerror);throw std::runtime_error("External XCB GetImage error");}
            if(!reply || reply->depth!=24 ||
               xcb_get_image_data_length(reply)!=static_cast<int>(width*height*4))
                throw std::runtime_error("External XCB window image invalid");
            const uint8_t* raw=xcb_get_image_data(reply);
            for(size_t i=0;i<size_t(width)*height;++i) {
                const char rgba[4]={static_cast<char>(raw[i*4+2]),
                                    static_cast<char>(raw[i*4+1]),
                                    static_cast<char>(raw[i*4]),static_cast<char>(255)};
                file.write(rgba,4);
            }
            std::free(reply);
        } else {
            CHECK(vkMapMemory(device,memory[i],0,VK_WHOLE_SIZE,0,&mapped));
            for (uint32_t y=0;y<height;++y)
                file.write(static_cast<const char*>(mapped)+sublayout.offset+y*sublayout.rowPitch,width*4);
            vkUnmapMemory(device,memory[i]);
        }
        file.close();
        if (!file) throw std::runtime_error("external framebuffer readback failed");
    }
    // Actual client-owned X11 resize, then Vulkan must reject old swapchain.
    const std::uint32_t resize_value[] = {31};
    auto resize_cookie = xcb_configure_window_checked(xc, window,
        XCB_CONFIG_WINDOW_WIDTH, resize_value);
    auto* resize_error = xcb_request_check(xc, resize_cookie);
    if (resize_error) {std::free(resize_error); throw std::runtime_error("Real XCB resize failed");}
    xcb_flush(xc);
    VkFenceCreateInfo resizeFenceInfo{}; resizeFenceInfo.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    VkFence resizeFence{};
    CHECK(vkCreateFence(device,&resizeFenceInfo,nullptr,&resizeFence));
    uint32_t staleIndex{};
    const auto stale = acquireNext(device,swapchain,0,VK_NULL_HANDLE,resizeFence,&staleIndex);
    if (stale != VK_ERROR_OUT_OF_DATE_KHR)
        throw std::runtime_error("Resized surface did not invalidate VkSwapchainKHR: " +
                                 std::to_string(stale));
    vkDestroyFence(device,resizeFence,nullptr);
    // Real native invalid index type must invalidate the actual Vulkan
    // command buffer, not silently record a placeholder draw.
    VkCommandBuffer badCmd{};
    CHECK(vkAllocateCommandBuffers(device,&ai,&badCmd));
    CHECK(vkBeginCommandBuffer(badCmd,&begin));
    vkCmdBindIndexBuffer(badCmd,vb,sizeof(vertices),static_cast<VkIndexType>(0x7fffffff));
    const VkResult unsupported_index_type = vkEndCommandBuffer(badCmd);
    if (unsupported_index_type != VK_ERROR_FEATURE_NOT_PRESENT)
        throw std::runtime_error("Invalid VkIndexType must return VK_ERROR_FEATURE_NOT_PRESENT");
    vkFreeCommandBuffers(device,pool,1,&badCmd);
    bi.usage=VK_BUFFER_USAGE_INDEX_BUFFER_BIT;
    VkBuffer onlyIndex{};
    CHECK(vkCreateBuffer(device,&bi,nullptr,&onlyIndex));
    CHECK(vkBindBufferMemory(device,onlyIndex,vm,0));
    CHECK(vkAllocateCommandBuffers(device,&ai,&badCmd));
    CHECK(vkBeginCommandBuffer(badCmd,&begin));
    vkCmdBindVertexBuffers(badCmd,0,1,&onlyIndex,&offset);
    if (vkEndCommandBuffer(badCmd)!=VK_ERROR_FEATURE_NOT_PRESENT)
        throw std::runtime_error("Index-only buffer accepted for vertex fetch");
    vkFreeCommandBuffers(device,pool,1,&badCmd);
    vkDestroyBuffer(device,onlyIndex,nullptr);
    vkDestroyCommandPool(device,pool,nullptr);
    vkDestroyPipeline(device,pipeline,nullptr);
    vkDestroyPipelineLayout(device,layout,nullptr);
    vkDestroyFramebuffer(device,fb,nullptr);
    vkDestroyRenderPass(device,pass,nullptr);
    for (int i=0;i<2;++i) {
        vkDestroyShaderModule(device,modules[i],nullptr);
        vkDestroyImageView(device,views[i],nullptr);
        if(i==1) {
            vkDestroyImage(device,images[i],nullptr);
            vkFreeMemory(device,memory[i],nullptr);
        }
    }
    vkDestroyBuffer(device,vb,nullptr); vkFreeMemory(device,vm,nullptr);
    vkDestroySemaphore(device,imageReady,nullptr);
    vkDestroySemaphore(device,drawFinished,nullptr);
    destroySwapchain(device,swapchain,nullptr);
    vkDestroyDevice(device,nullptr);
    destroySurface(instance,surface,nullptr);
    vkDestroyInstance(instance,nullptr);
    xcb_destroy_window(xc,window); xcb_flush(xc); xcb_disconnect(xc);
    std::cout << "ARE_VK_REAL_INDEXED_DRAW_AND_NEGATIVE_PASS index_type="
              << (alternate ? "UINT32" : "UINT16") << " signed_base_vertex=-1 max_index=16777215 two_framebuffer_receipts=1\n";
}
int main(int argc, char** argv) {
    if (argc != 3 && argc != 4) return 2;
    if (argc == 4 && std::strcmp(argv[3], "rgb-cycle") != 0) return 2;
    try { run(argv[1],argv[2],argc==4); return 0; }
    catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
