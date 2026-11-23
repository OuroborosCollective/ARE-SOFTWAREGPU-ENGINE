// Developer-only Linux ICD. CPython owns bounded Vulkan objects and queue policy.
// Submitted packed triangles execute in the native raster adapter in this DSO.
#include <Python.h>
#include <vulkan/vk_icd.h>
#include <dlfcn.h>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <mutex>

namespace {
std::once_flag init;
PyObject* dispatch = nullptr;

void initialize() {
    // Extension modules need the Python C API in the global link scope when
    // the system Vulkan loader has opened this ICD with RTLD_LOCAL.
    Dl_info python{}, self{};
    const bool own = !Py_IsInitialized();
    if (!dladdr(reinterpret_cast<void*>(initialize), &self)) return;
    if (own && (!dladdr(reinterpret_cast<void*>(Py_Initialize), &python) ||
                !dlopen(python.dli_fname, RTLD_NOW | RTLD_GLOBAL))) return;
    if (own) Py_Initialize();
    auto state = PyGILState_Ensure();
    auto* module = PyImport_ImportModule("software_gpu.drivers.weighted_icd");
    if (module) {
        auto* result = PyObject_CallMethod(module, "open_driver", "s", self.dli_fname);
        if (result) dispatch = result;
        Py_DECREF(module);
    }
    if (!dispatch && PyErr_Occurred()) PyErr_Print();
    PyGILState_Release(state);
    if (own) PyEval_SaveThread();
}

long invoke(const char* name, std::initializer_list<uintptr_t> args) {
    std::call_once(init, initialize);
    if (!dispatch) return VK_ERROR_INITIALIZATION_FAILED;
    auto state = PyGILState_Ensure();
    auto* tuple = PyTuple_New(args.size() + 1);
    long result = VK_ERROR_OUT_OF_HOST_MEMORY;
    if (tuple) {
        size_t i = 0;
        PyTuple_SET_ITEM(tuple, i++, PyUnicode_FromString(name));
        for (auto arg : args) PyTuple_SET_ITEM(tuple, i++, PyLong_FromUnsignedLongLong(arg));
        auto* value = PyObject_CallObject(dispatch, tuple);
        Py_DECREF(tuple);
        if (value) { result = PyLong_AsLong(value); Py_DECREF(value); }
    }
    if (PyErr_Occurred()) { PyErr_Print(); result = VK_ERROR_DEVICE_LOST; }
    PyGILState_Release(state);
    return result;
}
#include "are_dispatch.inc"
} // namespace

extern "C" VKAPI_ATTR VkResult VKAPI_CALL vk_icdNegotiateLoaderICDInterfaceVersion(uint32_t* v) {
    if (!v || *v < 2) return VK_ERROR_INCOMPATIBLE_DRIVER;
    if (*v > 5) *v = 5;
    return VK_SUCCESS;
}
extern "C" VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vk_icdGetPhysicalDeviceProcAddr(VkInstance, const char*) { return nullptr; }

static PFN_vkVoidFunction VKAPI_CALL deviceProc(VkDevice, const char* name) {
    return name ? lookupDevice(name) : nullptr;
}
extern "C" VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL
vk_icdGetInstanceProcAddr(VkInstance, const char* name) {
    if (!name) return nullptr;
    if (!std::strcmp(name,"vkGetInstanceProcAddr"))
        return reinterpret_cast<PFN_vkVoidFunction>(vk_icdGetInstanceProcAddr);
    if (!std::strcmp(name,"vkGetDeviceProcAddr"))
        return reinterpret_cast<PFN_vkVoidFunction>(deviceProc);
    auto fn = lookupInstance(name);
    return fn ? fn : lookupDevice(name);
}
extern "C" {
#include "are_shaders.inc"
}
