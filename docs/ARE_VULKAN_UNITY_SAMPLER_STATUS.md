# Unity 6 / ARE Vulkan VkSampler real ICD slice

## Real failure and causal source location

The original Linux Unity 6.6.8f1 Player on the older ARE ICD reached
Vulkan 1.0 device enumeration, requested Vulkan 1.1, and crashed with a
null indirect call before MonoBehaviour Start(). Using an isolated
Ubuntu 22.04 GDB 12.1, the actual x86-64 RIP was 0x0. The call site in
UnityPlayer.so (Build-ID 73db52a591fab943baec987fdc3a21d9d7860db1)
was 0x0288e3f7, with the global dispatch pointer at 0x02e1dbd0.
The initialization code at 0x028d465e loads the literal
"vkCreateSampler" from UnityPlayer.so .rodata 0x0029bfa0. The old
ARE ICD had no vkCreateSampler address. This is a verified cause of
that **specific** null-pointer path, not a promise of Unity support.

## Real implementation and scope

ARE now validates a bounded VkSamplerCreateInfo, allocates distinct
device-owned opaque VkSampler handles and stores immutable descriptor
values. It frees the actual resource on vkDestroySampler. Unsupported
anisotropy, non-null extension chains, unnormalized coordinates and
feature requests exceeding the current ICD profile fail closed with
VK_ERROR_FEATURE_NOT_PRESENT. The native sampler_probe.cpp queries
vkGetDeviceProcAddr from the real Khronos loader, performs actual
create/destroy with two independent handles and checks negative results.
The Linux GitHub WSI workflow binds it to the same real ICD binary,
with a SHA256 digest inventory and exact source SHA.

The driver still advertises no sampled-image texture format/feature,
and does not yet support shader texture reads or descriptor set
allocation. Sampler object creation therefore does NOT establish
functional texture sampling, Mesa Zink, full Unity Vulkan compliance,
or hardware GPU support.

## Unity regression and next real contract

With an isolated rebuilt ARE ICD on the same Unity test Player, the
original vkCreateSampler null-pointer crash no longer occurs.
Unity proceeds into vkCreateBuffer, which rejects a not-yet-supported
usage (VkResult -8), and reports "Vulkan - Out of memory! (allocating
memory for buffer)" before another SIGSEGV (exit 139). This text does
not prove real system RAM exhaustion; it maps to ARE's feature rejection.

The next slice must inspect the actual Unity VkBufferCreateInfo
(size, usage, sharing mode) and implement valid buffer/resource
operations and independent native readbacks before expanding the
advertised profile. No invented buffer capability flags. The real
Unity acceptance gate remains both distinct genuine ARE frames
and ARE_UNITY_TWO_TRIANGLE_READBACKS_PASS in the exact source+binary
runtime identity, followed by an independent Unity Editor test.
