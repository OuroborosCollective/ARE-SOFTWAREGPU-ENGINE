"""Isolated Vulkan 1.0 headless triangle-list prototype, backed by ARE CPU draws.

Only the build-bound position/RGB shader pair is lowered. No implicit system
installation, display extension, arbitrary shader execution or Unity admission.
"""
from collections import namedtuple
import ctypes
import hashlib
import json
import os
from threading import Condition
from time import monotonic_ns
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import vulkan as vk

from software_gpu.drivers.clip_draws import record_clip_draws
from software_gpu.drivers.command_submission import submit_native_draws
from software_gpu.drivers.native_bridge import AREDriverBridge
from software_gpu.graphics.framebuffer import Framebuffer

ffi = vk.ffi
MAX_MEMORY = 128 * 1024 * 1024
RGBA, DEPTH = vk.VK_FORMAT_R8G8B8A8_UNORM, vk.VK_FORMAT_D32_SFLOAT
ImageSpec = namedtuple("ImageSpec", "width height format size")


def require(condition, result=vk.VK_ERROR_FEATURE_NOT_PRESENT):
    if not condition:
        raise Rejected(result)


class Rejected(Exception):
    pass


def key(ptr):
    return int(ffi.cast("uintptr_t", ptr))


def zero(ptr):
    ffi.buffer(ptr, ffi.sizeof(ffi.typeof(ptr).item))[:] = bytes(ffi.sizeof(ffi.typeof(ptr).item))


def enumerate_one(count, output, value):
    if not output:
        count[0] = 1
    elif count[0]:
        output[0] = value
        count[0] = 1
    else:
        return vk.VK_INCOMPLETE
    return vk.VK_SUCCESS


def image_spec(info):
    e = info.extent
    require(info.imageType == vk.VK_IMAGE_TYPE_2D and info.format in (RGBA, DEPTH)
            and info.tiling == vk.VK_IMAGE_TILING_LINEAR and e.depth == 1
            and 0 < e.width <= 4096 and 0 < e.height <= 4096 and e.width * e.height <= 4194304
            and info.mipLevels == info.arrayLayers == info.samples == 1,
            vk.VK_ERROR_FORMAT_NOT_SUPPORTED)
    return ImageSpec(e.width, e.height, info.format, e.width * e.height * 4)


class Driver:
    def __init__(self, path):
        self.binary = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.bridge = AREDriverBridge(path, self.binary)
        self.shaders = {}
        for stage, name in [(vk.VK_SHADER_STAGE_VERTEX_BIT, "vert"), (vk.VK_SHADER_STAGE_FRAGMENT_BIT, "frag")]:
            read = getattr(self.bridge._lib, "are_" + name + "_sha")
            read.restype = ctypes.c_char_p
            self.shaders[read().decode("ascii")] = stage
        self.fences = Condition()
        self.objects = {}
        self.signatures = {}

    def dispatch(self, name, *args):
        try:
            types = self.signatures.get(name)
            if types is None:
                types = self.signatures[name] = ffi.typeof("PFN_" + name).args
            values = [ffi.cast(t, a) if t.kind in ("pointer", "function") else a
                      for t, a in zip(types, args)]
            return getattr(self, name)(*values) or 0
        except (Rejected, KeyError, ValueError, MemoryError, OverflowError, IndexError) as exc:
            if os.getenv("ARE_VK_DIAGNOSTICS"):
                import sys
                print(name, repr(exc), file=sys.stderr, flush=True)
            if name.startswith("vkCmd") and args and args[0] in self.objects:
                self.objects[args[0]].invalid = True
            if isinstance(exc, Rejected):
                return exc.args[0]
            return vk.VK_ERROR_OUT_OF_HOST_MEMORY if isinstance(exc, MemoryError) else vk.VK_ERROR_DEVICE_LOST

    def new(self, kind, parent=None, **data):
        require(len(self.objects) < 65536, vk.VK_ERROR_TOO_MANY_OBJECTS)
        block = ffi.new("uintptr_t[2]", [0x01CDC0DE, 0])
        obj = SimpleNamespace(block=block, handle=ffi.cast("Vk" + kind, block),
                              kind=kind, parent=key(parent) if parent else 0, **data)
        self.objects[key(block)] = obj
        return obj

    def drop(self, handle):
        addr = key(handle)
        if not addr:
            return
        for child in [n for n, obj in self.objects.items() if obj.parent == addr]:
            self.drop(self.objects[child].handle)
        self.objects.pop(addr, None)

    def vkCreateInstance(self, p, alloc, out):
        require(not alloc and not p.enabledExtensionCount and not p.enabledLayerCount)
        instance = self.new("Instance")
        instance.phys = self.new("PhysicalDevice", instance.handle)
        out[0] = instance.handle

    def vkDestroyInstance(self, instance, alloc):
        self.drop(instance)

    def vkEnumerateInstanceExtensionProperties(self, layer, count, props):
        require(not layer, vk.VK_ERROR_LAYER_NOT_PRESENT)
        count[0] = 0

    def vkEnumeratePhysicalDevices(self, instance, count, out):
        return enumerate_one(count, out, self.objects[key(instance)].phys.handle)

    def vkGetPhysicalDeviceProperties(self, phys, out):
        zero(out)
        out.apiVersion = vk.VK_API_VERSION_1_0
        out.driverVersion = 1
        out.deviceType = vk.VK_PHYSICAL_DEVICE_TYPE_CPU
        out.deviceName = b"ARE SoftwareGPU (experimental headless CPU)"
        ffi.memmove(out.pipelineCacheUUID, bytes.fromhex(self.binary)[:16], 16)
        lim = out.limits
        lim.maxImageDimension2D = lim.maxFramebufferWidth = lim.maxFramebufferHeight = 4096
        lim.maxMemoryAllocationCount = 512
        lim.maxBoundDescriptorSets = 0
        lim.maxVertexInputAttributes = 2
        lim.maxVertexInputBindings = 1
        lim.maxVertexInputBindingStride = 24
        lim.maxVertexInputAttributeOffset = 12
        lim.maxFragmentOutputAttachments = lim.maxColorAttachments = 1
        lim.maxViewports = lim.maxFramebufferLayers = 1
        lim.maxViewportDimensions[0] = lim.maxViewportDimensions[1] = 4096
        lim.viewportBoundsRange[1] = 4096
        lim.framebufferColorSampleCounts = lim.framebufferDepthSampleCounts = 1
        lim.minMemoryMapAlignment = lim.nonCoherentAtomSize = 1

    def vkGetPhysicalDeviceFeatures(self, phys, out):
        zero(out)

    def vkGetPhysicalDeviceMemoryProperties(self, phys, out):
        zero(out)
        out.memoryTypeCount = out.memoryHeapCount = 1
        out.memoryTypes[0].propertyFlags = (vk.VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
            vk.VK_MEMORY_PROPERTY_HOST_COHERENT_BIT | vk.VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)
        out.memoryHeaps[0].size = MAX_MEMORY
        out.memoryHeaps[0].flags = vk.VK_MEMORY_HEAP_DEVICE_LOCAL_BIT

    def vkGetPhysicalDeviceQueueFamilyProperties(self, phys, count, out):
        if out and count[0]:
            zero(out)
            out[0].queueFlags = vk.VK_QUEUE_GRAPHICS_BIT
            out[0].queueCount = 1
            e = out[0].minImageTransferGranularity
            e.width = e.height = e.depth = 1
        if not out or count[0]:
            count[0] = 1

    def vkGetPhysicalDeviceFormatProperties(self, phys, fmt, out):
        zero(out)
        if fmt == RGBA:
            out.linearTilingFeatures = vk.VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT
        elif fmt == DEPTH:
            out.linearTilingFeatures = vk.VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT
        elif fmt == vk.VK_FORMAT_R32G32B32_SFLOAT:
            out.bufferFeatures = vk.VK_FORMAT_FEATURE_VERTEX_BUFFER_BIT

    def vkGetPhysicalDeviceImageFormatProperties(self, phys, fmt, typ, tile, usage, flags, out):
        zero(out)
        allowed = {RGBA: vk.VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT,
                   DEPTH: vk.VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT}.get(fmt, 0)
        require(allowed and typ == vk.VK_IMAGE_TYPE_2D and tile == vk.VK_IMAGE_TILING_LINEAR
                and not flags and not usage & ~allowed, vk.VK_ERROR_FORMAT_NOT_SUPPORTED)
        out.maxExtent.width = out.maxExtent.height = 4096
        out.maxExtent.depth = out.maxMipLevels = out.maxArrayLayers = out.sampleCounts = 1
        out.maxResourceSize = 4194304 * 4

    def vkGetPhysicalDeviceSparseImageFormatProperties(self, phys, fmt, typ, smp, usage, tile, count, out):
        count[0] = 0

    def vkEnumerateDeviceExtensionProperties(self, phys, layer, count, props):
        return self.vkEnumerateInstanceExtensionProperties(layer, count, props)

    def vkCreateDevice(self, phys, p, alloc, out):
        require(not alloc and not p.enabledExtensionCount and p.queueCreateInfoCount == 1)
        q = p.pQueueCreateInfos[0]
        require(q.queueFamilyIndex == 0 and q.queueCount == 1 and not q.flags)
        if p.pEnabledFeatures:
            require(not any(bytes(ffi.buffer(p.pEnabledFeatures))))
        device = self.new("Device", phys, allocated=0, allocations=0)
        device.queue = self.new("Queue", device.handle)
        out[0] = device.handle

    def vkDestroyDevice(self, dev, alloc):
        self.drop(dev)

    def vkGetDeviceQueue(self, dev, family, index, out):
        require(family == index == 0)
        out[0] = self.objects[key(dev)].queue.handle

    def vkDeviceWaitIdle(self, dev):
        require(key(dev) in self.objects)

    vkQueueWaitIdle = vkDeviceWaitIdle

    def vkAllocateMemory(self, dev, p, alloc, out):
        device = self.objects[key(dev)]
        require(not alloc and p.memoryTypeIndex == 0 and 0 < p.allocationSize <= MAX_MEMORY - device.allocated
                and device.allocations < 512, vk.VK_ERROR_OUT_OF_DEVICE_MEMORY)
        data = bytearray(p.allocationSize)
        out[0] = self.new("DeviceMemory", dev, data=data, mapped=False).handle
        device.allocated += len(data)
        device.allocations += 1

    def vkFreeMemory(self, dev, handle, alloc):
        if handle:
            self.objects[key(dev)].allocated -= len(self.objects[key(handle)].data)
            self.objects[key(dev)].allocations -= 1
            self.drop(handle)

    def vkMapMemory(self, dev, handle, offset, size, flags, out):
        mem = self.objects[key(handle)]
        require(not mem.mapped and flags == 0 and offset < len(mem.data)
                and (size == 2**64-1 or 0 < size <= len(mem.data)-offset), vk.VK_ERROR_MEMORY_MAP_FAILED)
        out[0] = ffi.cast("char *", ffi.from_buffer(mem.data)) + offset
        mem.mapped = True

    def vkUnmapMemory(self, dev, handle):
        self.objects[key(handle)].mapped = False

    def vkCreateBuffer(self, dev, p, alloc, out):
        require(not alloc and not p.flags and 0 < p.size <= MAX_MEMORY and
                p.usage == vk.VK_BUFFER_USAGE_VERTEX_BUFFER_BIT and
                p.sharingMode == vk.VK_SHARING_MODE_EXCLUSIVE)
        out[0] = self.new("Buffer", dev, size=int(p.size), mem=None).handle

    def vkCreateImage(self, dev, p, alloc, out):
        spec = image_spec(p)
        expected = vk.VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT if p.format == RGBA else vk.VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT
        require(not alloc and not p.flags and p.usage == expected and p.sharingMode == vk.VK_SHARING_MODE_EXCLUSIVE)
        out[0] = self.new("Image", dev, spec=spec, size=spec.size, mem=None).handle

    def vkGetBufferMemoryRequirements(self, dev, buf, out):
        out.size = self.objects[key(buf)].size
        out.alignment = 4
        out.memoryTypeBits = 1

    vkGetImageMemoryRequirements = vkGetBufferMemoryRequirements

    def vkBindBufferMemory(self, dev, handle, memory, offset):
        obj, mem = self.objects[key(handle)], self.objects[key(memory)]
        require(obj.parent == mem.parent == key(dev) and not obj.mem and offset % 4 == 0 and
                offset + obj.size <= len(mem.data))
        obj.mem, obj.offset = key(memory), offset

    vkBindImageMemory = vkBindBufferMemory

    def vkGetImageSubresourceLayout(self, dev, img, sub, out):
        obj = self.objects[key(img)]
        zero(out)
        out.size = out.depthPitch = out.arrayPitch = obj.size
        out.rowPitch = obj.spec.width * 4

    def vkCreateImageView(self, dev, p, alloc, out):
        image = self.objects[key(p.image)]
        rng = p.subresourceRange
        require(not alloc and not p.flags and p.viewType == vk.VK_IMAGE_VIEW_TYPE_2D and p.format == image.spec.format
                and rng.baseMipLevel == rng.baseArrayLayer == 0 and rng.levelCount == rng.layerCount == 1
                and rng.aspectMask == (vk.VK_IMAGE_ASPECT_COLOR_BIT if p.format == RGBA else vk.VK_IMAGE_ASPECT_DEPTH_BIT)
                and all(getattr(p.components,k) == vk.VK_COMPONENT_SWIZZLE_IDENTITY for k in "rgba"))
        out[0] = self.new("ImageView", dev, image=key(p.image)).handle

    def vkDestroyBuffer(self, dev, handle, alloc):
        self.drop(handle)

    vkDestroyImage = vkDestroyImageView = vkDestroyBuffer
    vkDestroyPipeline = vkDestroyPipelineLayout = vkDestroyShaderModule = vkDestroyBuffer
    vkDestroyRenderPass = vkDestroyFramebuffer = vkDestroyCommandPool = vkDestroyBuffer
    vkDestroyFence = vkDestroyBuffer

    def vkCreateShaderModule(self, dev, p, alloc, out):
        require(not alloc and not p.flags and 0 < p.codeSize <= 1024 * 1024)
        digest = hashlib.sha256(ffi.buffer(p.pCode, p.codeSize)).hexdigest()
        require(digest in self.shaders)
        out[0] = self.new("ShaderModule", dev, stage=self.shaders[digest], digest=digest).handle

    def vkCreatePipelineLayout(self, dev, p, alloc, out):
        require(not alloc and not p.flags and not p.setLayoutCount and not p.pushConstantRangeCount)
        out[0] = self.new("PipelineLayout", dev).handle

    def vkCreateRenderPass(self, dev, p, alloc, out):
        require(not alloc and not p.flags and p.attachmentCount == 2 and p.subpassCount == 1 and not p.dependencyCount)
        for i, fmt in enumerate((RGBA, DEPTH)):
            a = p.pAttachments[i]
            require(a.format == fmt and a.samples == 1 and a.loadOp == vk.VK_ATTACHMENT_LOAD_OP_CLEAR
                    and a.storeOp == vk.VK_ATTACHMENT_STORE_OP_STORE and a.finalLayout == vk.VK_IMAGE_LAYOUT_GENERAL)
        s = p.pSubpasses[0]
        require(s.pipelineBindPoint == vk.VK_PIPELINE_BIND_POINT_GRAPHICS and not s.inputAttachmentCount
                and s.colorAttachmentCount == 1 and s.pColorAttachments[0].attachment == 0
                and s.pDepthStencilAttachment and s.pDepthStencilAttachment.attachment == 1
                and not s.pResolveAttachments and not s.preserveAttachmentCount)
        out[0] = self.new("RenderPass", dev).handle

    def vkCreateFramebuffer(self, dev, p, alloc, out):
        require(not alloc and not p.flags and p.attachmentCount == 2 and p.layers == 1)
        images = tuple(self.objects[key(p.pAttachments[i])].image for i in range(2))
        specs = [self.objects[i].spec for i in images]
        require([s.format for s in specs] == [RGBA, DEPTH] and
                all((s.width,s.height)==(p.width,p.height) for s in specs))
        out[0] = self.new("Framebuffer", dev, images=images, width=p.width, height=p.height,
                          render_pass=key(p.renderPass)).handle

    def vkCreateGraphicsPipelines(self, dev, cache, count, infos, alloc, out):
        for i in range(count):
            out[i] = ffi.NULL
        require(not alloc and not cache and count == 1)
        p = infos[0]
        require(not p.flags and not p.subpass and not p.basePipelineHandle and p.stageCount == 2
                and not p.pTessellationState and not p.pDynamicState and key(p.layout) in self.objects
                and key(p.renderPass) in self.objects)
        for i in range(2):
            stage = p.pStages[i]
            require(not stage.flags and ffi.string(stage.pName) == b"main" and not stage.pSpecializationInfo
                    and stage.stage == self.objects[key(stage.module)].stage)
        require({p.pStages[i].stage for i in range(2)} == set(self.shaders.values()))
        vi, ia = p.pVertexInputState, p.pInputAssemblyState
        require(vi and ia and vi.vertexBindingDescriptionCount == 1 and vi.vertexAttributeDescriptionCount == 2
                and ia.topology == vk.VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST and not ia.primitiveRestartEnable)
        binding = vi.pVertexBindingDescriptions[0]
        require(binding.binding == 0 and binding.stride == 24 and binding.inputRate == vk.VK_VERTEX_INPUT_RATE_VERTEX)
        attrs = {(a.location,a.binding,a.format,a.offset) for a in vi.pVertexAttributeDescriptions[0:2]}
        require(attrs == {(0,0,vk.VK_FORMAT_R32G32B32_SFLOAT,0),(1,0,vk.VK_FORMAT_R32G32B32_SFLOAT,12)})
        rs, ms, ds, bl = p.pRasterizationState, p.pMultisampleState, p.pDepthStencilState, p.pColorBlendState
        require(rs and ms and ds and bl and not rs.depthClampEnable and not rs.rasterizerDiscardEnable
                and rs.polygonMode == vk.VK_POLYGON_MODE_FILL and rs.cullMode == 0 and not rs.depthBiasEnable
                and ms.rasterizationSamples == 1 and not ms.sampleShadingEnable and not ms.alphaToCoverageEnable
                and not ms.alphaToOneEnable and (not ms.pSampleMask or ms.pSampleMask[0] & 1)
                and ds.depthTestEnable and ds.depthWriteEnable and ds.depthCompareOp == vk.VK_COMPARE_OP_LESS
                and not ds.stencilTestEnable and not ds.depthBoundsTestEnable and not bl.logicOpEnable
                and bl.attachmentCount == 1 and not bl.pAttachments[0].blendEnable
                and bl.pAttachments[0].colorWriteMask == 15)
        vs = p.pViewportState
        require(vs and vs.viewportCount == vs.scissorCount == 1)
        vp, sc = vs.pViewports[0], vs.pScissors[0]
        require(vp.x == vp.y == vp.minDepth == 0 and vp.maxDepth == 1 and
                sc.offset.x == sc.offset.y == 0 and vp.width == sc.extent.width and vp.height == sc.extent.height)
        out[0] = self.new("Pipeline", dev, extent=(int(vp.width),int(vp.height)), render_pass=key(p.renderPass)).handle

    def vkCreateCommandPool(self, dev, p, alloc, out):
        require(not alloc and p.queueFamilyIndex == 0 and not p.flags & ~3)
        out[0] = self.new("CommandPool", dev, flags=p.flags).handle

    def vkAllocateCommandBuffers(self, dev, p, out):
        require(0 < p.commandBufferCount <= 64 and p.level == vk.VK_COMMAND_BUFFER_LEVEL_PRIMARY)
        pool = self.objects[key(p.commandPool)]
        require(pool.parent == key(dev))
        for i in range(p.commandBufferCount):
            out[i] = self.new("CommandBuffer", pool.handle, state="initial").handle

    def vkFreeCommandBuffers(self, dev, pool, count, buffers):
        for i in range(count):
            self.drop(buffers[i])

    def vkBeginCommandBuffer(self, handle, p):
        cmd = self.objects[key(handle)]
        require(cmd.state != "recording" and (cmd.state == "initial" or
                self.objects[cmd.parent].flags & vk.VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT))
        cmd.state, cmd.invalid, cmd.pass_open = "recording", False, False
        cmd.target = cmd.clear = cmd.pipe = cmd.binding = None
        cmd.draws = []

    def vkCmdBeginRenderPass(self, handle, p, contents):
        cmd, fb = self.objects[key(handle)], self.objects[key(p.framebuffer)]
        rect = p.renderArea
        require(cmd.state == "recording" and cmd.target is None and p.clearValueCount == 2
                and key(p.renderPass) == fb.render_pass and contents == vk.VK_SUBPASS_CONTENTS_INLINE
                and rect.offset.x == rect.offset.y == 0 and rect.extent.width == fb.width
                and rect.extent.height == fb.height)
        color = np.array(list(p.pClearValues[0].color.float32), dtype=np.float32)
        depth = float(p.pClearValues[1].depthStencil.depth)
        require(np.isfinite(color).all() and 0 <= depth <= 1)
        cmd.clear = (np.rint(np.clip(color, 0, 1) * 255).astype(np.uint8), depth)
        cmd.target, cmd.pass_open = key(p.framebuffer), True

    def vkCmdBindPipeline(self, handle, point, pipeline):
        cmd = self.objects[key(handle)]
        require(cmd.state == "recording" and point == vk.VK_PIPELINE_BIND_POINT_GRAPHICS)
        cmd.pipe = key(pipeline)

    def vkCmdBindVertexBuffers(self, handle, first, count, buffers, offsets):
        cmd = self.objects[key(handle)]
        require(cmd.state == "recording" and first == 0 and count == 1)
        cmd.binding = key(buffers[0]), int(offsets[0])

    def vkCmdDraw(self, handle, count, instances, first, first_instance):
        cmd = self.objects[key(handle)]
        require(cmd.state == "recording" and cmd.pass_open and cmd.pipe and cmd.binding and
                instances == 1 and not first_instance and len(cmd.draws) < 256)
        fb, pipe = self.objects[cmd.target], self.objects[cmd.pipe]
        require(pipe.extent == (fb.width, fb.height) and pipe.render_pass == fb.render_pass)
        buf, offset = cmd.binding
        require(count <= 600000 and offset + (first+count)*24 <= self.objects[buf].size)
        cmd.draws.append((buf, offset + first*24, count - count % 3))

    def vkCmdEndRenderPass(self, handle):
        cmd = self.objects[key(handle)]
        require(cmd.pass_open)
        cmd.pass_open = False

    def vkEndCommandBuffer(self, handle):
        cmd = self.objects[key(handle)]
        require(cmd.state == "recording" and not cmd.invalid and not cmd.pass_open)
        cmd.state = "executable"

    def vkCreateFence(self, dev, p, alloc, out):
        require(not alloc and not p.flags & ~vk.VK_FENCE_CREATE_SIGNALED_BIT)
        out[0] = self.new("Fence", dev, signaled=bool(p.flags)).handle

    def vkWaitForFences(self, dev, count, fences, wait_all, timeout):
        objects = [self.objects[key(fences[i])] for i in range(count)]
        test = all if wait_all else any
        until = monotonic_ns() + timeout
        with self.fences:
            while not test(f.signaled for f in objects):
                remaining = until - monotonic_ns()
                if remaining <= 0:
                    return vk.VK_TIMEOUT
                self.fences.wait(min(remaining / 1e9, 3600))

    def vkCmdPipelineBarrier(self, handle, src, dst, flags, nc, memory, nb, buffers, ni, images):
        cmd = self.objects[key(handle)]
        # All rendering is synchronous into coherent host memory. This specific
        # dependency is fulfilled by the staged render commit before queue return.
        require(cmd.state == "recording" and not cmd.pass_open and not flags and nc == 1
                and not nb and not ni and dst == vk.VK_PIPELINE_STAGE_HOST_BIT
                and src == vk.VK_PIPELINE_STAGE_ALL_GRAPHICS_BIT
                and memory[0].dstAccessMask == vk.VK_ACCESS_HOST_READ_BIT
                and memory[0].srcAccessMask == (vk.VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
                                                 vk.VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT))

    def vkGetFenceStatus(self, dev, f):
        return 0 if self.objects[key(f)].signaled else vk.VK_NOT_READY

    def vkResetFences(self, dev, count, fences):
        for i in range(count):
            self.objects[key(fences[i])].signaled = False

    def view(self, obj):
        mem = self.objects[obj.mem]
        return memoryview(mem.data)[obj.offset:obj.offset+obj.size]

    def execute(self, cmd):
        require(cmd.state == "executable" and not cmd.invalid)
        if cmd.target is None:
            return
        fb = self.objects[cmd.target]
        destinations = [self.view(self.objects[i]) for i in fb.images]
        frame = Framebuffer(fb.width, fb.height)
        frame.color_buffer[:] = cmd.clear[0]
        frame.depth_buffer.fill(cmd.clear[1])
        draws = []
        for buf, start, count in cmd.draws:
            data = self.view(self.objects[buf])
            v = np.frombuffer(data, dtype=np.float32, count=count*6, offset=start).reshape(-1,6)
            pos = np.ones((count,4), np.float32)
            pos[:,:3] = v[:,:3]
            draws.append((pos, v[:,3:]))
        if draws:
            packet = record_clip_draws(draws, fb.width, fb.height)
            result = submit_native_draws(self.bridge, frame, packet, _icd_pipeline=self.pipeline_scope)
        destinations[0][:] = frame.color_buffer.tobytes()
        destinations[1][:] = frame.depth_buffer.tobytes()
        if draws and os.getenv("ARE_VK_RECEIPTS"):
            evidence = {"event":"vkQueueSubmit/graphics", "driver_sha256":self.binary,
                        "pipeline_sha256":self.pipeline_scope, "native_submission":result}
            try:
                with open(os.environ["ARE_VK_RECEIPTS"], "a", encoding="utf8") as f:
                    f.write(json.dumps(evidence, sort_keys=True) + "\n")
            except OSError:
                pass  # Optional diagnostics cannot retroactively fail the draw.

    def vkQueueSubmit(self, queue, count, batches, fence):
        require(key(queue) in self.objects)
        commands = []
        for i in range(count):
            batch = batches[i]
            require(not batch.waitSemaphoreCount and not batch.signalSemaphoreCount)
            commands.extend(self.objects[key(h)] for h in batch.pCommandBuffers[0:batch.commandBufferCount])
        for c in commands:
            self.execute(c)
        if fence:
            with self.fences:
                self.objects[key(fence)].signaled = True
                self.fences.notify_all()


def open_driver(path):
    driver = Driver(path)
    sources = (Path(__file__), Path(__file__).with_name("clip_draws.py"),
               Path(__file__).parents[1] / "graphics/geometry.py")
    digest = hashlib.sha256()
    for src in sources:
        digest.update(hashlib.sha256(src.read_bytes()).digest())
    for shader in sorted(driver.shaders):
        digest.update(bytes.fromhex(shader))
    driver.pipeline_scope = digest.hexdigest()
    return driver.dispatch
