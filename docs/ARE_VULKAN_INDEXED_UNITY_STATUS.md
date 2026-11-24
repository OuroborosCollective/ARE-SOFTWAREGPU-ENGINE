# ARE Vulkan 1.0 Index|Vertex buffers: genuine CPU draw admission

## Real Unity request and exact next missing feature

The same isolated Unity 6.6.8f1 Linux Player first crashed by calling an
unresolved vkCreateSampler. The actual sampler implementation in PR #346
resolved the null-call path, exposing a native vkCreateBuffer rejection.

Instrumentation in an isolated uncommitted diagnostic-only clone recorded:
- 4,194,304 bytes, usage 0xC0 = VK_BUFFER_USAGE_INDEX_BUFFER_BIT |
  VK_BUFFER_USAGE_VERTEX_BUFFER_BIT, flags=0, exclusive sharing, pNext=false.
- After implementing this exact storage-and-draw contract, Unity attempts
  8,388,608 bytes, usage 0x10 = VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT;
  the latter is genuinely unsupported by this ICD.

This is NOT a system-RAM-out-of-memory event. The ARE driver returns
VK_ERROR_FEATURE_NOT_PRESENT (-8) for the unsupported uniform usage.
No Unity frame is yet rendered.

## Implemented and independently verified

- VkBufferCreateInfo accepts only the exact supported mask, requiring actual
  bound VkDeviceMemory; unknown usages and modes remain rejected.
- vkCmdBindIndexBuffer binds a resource truly owned by the same VkDevice,
  with valid offset and uint16/uint32 element alignment.
- vkCmdDrawIndexed records real index and vertex bindings and converts actual
  little-endian bound host-coherent bytes into position/RGB vertex triangles
  at queue execution. Unsupported index types, invalid offsets, out-of-range
  references and negative vertex offsets are rejected.
- CPU native submission still uses the existing C++17 ARE raster pipeline and
  XCB surface + Acquire/Present + independent server GetImage.
- The new independent C++ client wsi_indexed_probe.cpp runs two actual
  Vulkan windows: A uses UINT16 indices, B uses UINT32 indices with cycle
  of RGB channels. Both render exactly the same triangle and colors as
  the established direct VkCmdDraw path.
- A deliberately invalid VkIndexType causes a genuine VkEndCommandBuffer
  rejection (VK_ERROR_FEATURE_NOT_PRESENT); this is checked as part of
  the native client before reporting its positive marker.

VPS baseline direct/indirect byte-identity observations (not a Unity claim):
- RGBA A: 23666fc9eba3c4db3a4e5c2da6a365ea656896e000ff4fc2c0a6b181090f64ad
- RGBA B: 904d3ed510928e5e70c36ef8fc10a721020645106b6d64610bc2f9a415b4faa0
- Depth A and B: fb05fcff09184665205a8c13099087551c41fe354ca6c19ad2fb4f9eb3e5da1b
- Isolated modified driver DSO: 555bfa35db20fa521e163c15b34c9958c2a64f96aa91428bc1d40d291d69e3ff

The GitHub real XCB pipeline must independently reproduce these two variant
results on the exact PR HEAD, including source and native library hashes,
and must keep the original direct-render acceptance tests intact.

## Explicitly not implemented, next real prerequisite

- Actual UNIFORM_BUFFER usage 0x10 is blocked until host-coherent storage,
  descriptor-set ownership/writes, actual shader uniform reads, push/binding
  validity and real output parity are implemented and measured.
- Indexed Vulkan acceptance does not establish Unity 6 Player/Editor support,
  Zink OpenGL, Unigine Heaven, CTS core conformance or global adapter install.
- Do not advertise false device limits or API version to sidestep the next
  Vulkan contract. Preserve the existing 100-ms gameplay tick independently.
