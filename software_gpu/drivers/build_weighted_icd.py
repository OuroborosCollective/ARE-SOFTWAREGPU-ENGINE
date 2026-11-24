"""Build an isolated experimental Linux ICD and its exact supported shader pair."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import sysconfig
import xml.etree.ElementTree as ET

from software_gpu.research.native_symbolic import FLAGS, compiler


def write_dispatch(registry, output):
    from software_gpu.drivers.weighted_icd import Driver
    entries = {n for n in vars(Driver) if n.startswith("vk")}
    tables = {"Device": [], "Instance": []}
    source = []
    for cmd in ET.parse(registry).findall("./commands/command"):
        name = cmd.findtext("proto/name")
        if name not in entries:
            continue
        entries.remove(name)
        params = cmd.findall("param")
        decl = ", ".join("".join(p.itertext()) for p in params)
        args = ", ".join("(uintptr_t)" + p.findtext("name") for p in params)
        result = cmd.findtext("proto/type")
        fn = "are_" + name
        source.append(f"static {result} VKAPI_CALL {fn}({decl}) {{")
        source.append(f'    return ({result})invoke("{name}", {{{args}}});\n}}')
        group = "Device" if params[0].findtext("type") in ("VkDevice", "VkCommandBuffer", "VkQueue") else "Instance"
        tables[group].append((name, fn))
    if entries:
        raise ValueError(f"Unknown Vulkan commands: {entries}")
    for group, rows in tables.items():
        source.append(f"static PFN_vkVoidFunction lookup{group}(const char* name) {{")
        for name, fn in rows:
            source.append(f'    if (!std::strcmp(name, "{name}")) return reinterpret_cast<PFN_vkVoidFunction>({fn});')
        source.append("    return nullptr;\n}")
    output.write_text("\n".join(source) + "\n")


def build(out, registry, include):
    if not (3, 11) <= sys.version_info[:2] <= (3, 12) or sys.platform != "linux":
        raise RuntimeError("Developer ICD requires 64-bit Linux and project CPython 3.11 or 3.12")
    if sys.maxsize < 2**63 - 1:
        raise RuntimeError("Developer ICD requires a 64-bit Vulkan ABI")
    root = Path(__file__).resolve().parents[2]
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    write_dispatch(registry, out / "are_dispatch.inc")
    lowerings = {
        "vert": "e2ec4ac81a82e2a4e083c4d0cf57e26f90ab96f579fdc80383df4ce8f0039999",
        "frag": "2e8c7991cefeff80f0691ec56051f9942f1f44ded2d7d2a082a7c11d8f94dfe3",
    }
    for stage, expected in lowerings.items():
        source = root / "software_gpu/drivers" / ("shader_probe." + stage)
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError("Shader source has no verified ARE native lowering: " + stage)
        path = out / (stage + ".spv")
        subprocess.run(["glslangValidator", "-V", "--target-env", "vulkan1.0",
                        str(source), "-o", str(path)], check=True)
        subprocess.run(["spirv-val", "--target-env", "vulkan1.0", str(path)], check=True)
    # Bind the only supported native lowering to the two actual compiled modules.
    (out / "are_shaders.inc").write_text("\n".join(
        f'const char* are_{s}_sha() {{ return "{hashlib.sha256((out/(s+".spv")).read_bytes()).hexdigest()}"; }}'
        for s in ("vert", "frag")) + "\n")
    lib = out / "libare_weighted.so"
    pyroot = Path(sys.base_prefix)
    inc = pyroot / "include" / ("python" + sysconfig.get_python_version())
    if not (inc / "Python.h").is_file():
        inc = Path(sysconfig.get_path("include"))
    libdir = pyroot / "lib"
    if not (libdir / sysconfig.get_config_var("LDLIBRARY")).exists():
        libdir = Path(sysconfig.get_config_var("LIBDIR"))
    subprocess.run([compiler(), *FLAGS, "-shared", "-fPIC", "-I" + str(include),
                    "-I" + str(out), "-I" + str(inc), str(root / "native/vulkan/weighted/entry.cpp"),
                    str(root / "native/raster/driver_adapter.cpp"),
                    str(root / "native/vulkan/weighted/xcb_wsi.cpp"), "-L" + str(libdir),
                    "-Wl,-rpath," + str(libdir), "-lpython" + sysconfig.get_python_version(),
                    "-ldl", "-lxcb", "-o", str(lib)], check=True)
    manifest = out / "are.json"
    manifest.write_text(json.dumps({"file_format_version":"1.0.0",
                                   "ICD":{"library_path":str(lib), "api_version":"1.0.0"}}) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--registry", type=Path, default=Path("/usr/share/vulkan/registry/vk.xml"))
    parser.add_argument("--include", type=Path, default=Path("/usr/include"))
    args = parser.parse_args()
    print(build(args.output, args.registry, args.include))
