"""Pure Vulkan index gather contract: not a substitute for real Vulkan WSI tests."""
import unittest
import sys

# Only the native Linux Vulkan CI has the actual Vulkan Python bindings.
vk = np = Rejected = gather_indexed_vertices = None
if sys.platform == "linux":
    try:
        import vulkan as vk
    except ModuleNotFoundError as exc:
        if exc.name != "vulkan":
            raise
    if vk is not None:
        import numpy as np
        from software_gpu.drivers.weighted_icd import Rejected, gather_indexed_vertices


@unittest.skipUnless(vk is not None, "real Linux Vulkan bindings required")
class IndexedBufferTests(unittest.TestCase):
    def setUp(self):
        # Three actual vertex attributes: x/y/z + red/green/blue, 24 bytes each.
        self.vertices = np.array([
            [-1,-1,0,1,0,0],[1,-1,0,0,1,0],[-1,1,0,0,0,1]],
            dtype=np.float32).tobytes()

    def test_unchanged_triangle_indices(self):
        inds = np.array([0,1,2],dtype=np.uint16).tobytes()
        result = gather_indexed_vertices(self.vertices,0,inds,0,3,0,0,vk.VK_INDEX_TYPE_UINT16)
        self.assertTrue(np.array_equal(result,np.frombuffer(self.vertices,np.float32).reshape(3,6)))

    def test_independent_indexed_order(self):
        inds=np.array([2,0,1],dtype=np.uint32).tobytes()
        result=gather_indexed_vertices(self.vertices,0,inds,0,3,0,0,vk.VK_INDEX_TYPE_UINT32)
        expected=np.frombuffer(self.vertices,np.float32).reshape(3,6)[[2,0,1]]
        self.assertTrue(np.array_equal(result,expected))

    def test_out_of_range_vertex_reference_rejected(self):
        inds=np.array([0,1,9],dtype=np.uint16).tobytes()
        with self.assertRaises(Rejected):
            gather_indexed_vertices(self.vertices,0,inds,0,3,0,0,vk.VK_INDEX_TYPE_UINT16)

    def test_negative_vertex_offset_rejected(self):
        inds=np.array([0,1,2],dtype=np.uint16).tobytes()
        with self.assertRaises(Rejected):
            gather_indexed_vertices(self.vertices,0,inds,0,3,0,-1,vk.VK_INDEX_TYPE_UINT16)

    def test_index_buffer_bounds_rejected(self):
        inds=np.array([0,1,2],dtype=np.uint16).tobytes()
        with self.assertRaises(Rejected):
            gather_indexed_vertices(self.vertices,0,inds,0,3,1,0,vk.VK_INDEX_TYPE_UINT16)

    def test_index_type_unsupported_is_not_treated_as_u16(self):
        inds=np.array([0,1,2],dtype=np.uint8).tobytes()
        with self.assertRaises(Rejected):
            gather_indexed_vertices(self.vertices,0,inds,0,3,0,0,0)

    def test_unaligned_vertex_offset_rejected(self):
        inds=np.array([0,1,2],dtype=np.uint16).tobytes()
        with self.assertRaises(Rejected):
            gather_indexed_vertices(self.vertices,2,inds,0,3,0,0,vk.VK_INDEX_TYPE_UINT16)

    def test_negative_index_count_rejected(self):
        inds=np.array([0,1,2],dtype=np.uint16).tobytes()
        with self.assertRaises(Rejected):
            gather_indexed_vertices(self.vertices,0,inds,0,-1,0,0,vk.VK_INDEX_TYPE_UINT16)
