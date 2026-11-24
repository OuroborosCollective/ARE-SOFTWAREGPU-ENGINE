"""Launch Linux Firefox against a process-local Mesa GL and lavapipe installation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sysconfig
import tempfile


def clean_graphics_environment(inherited):
    """Preserve desktop/session settings while removing driver and loader overrides."""
    exact = {"LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT", "GALLIUM_DRIVER",
             "MOZ_WEBRENDER", "MOZ_X11_EGL", "MOZ_FORCE_DISABLE_E10S"}
    prefixes = ("VK_", "MESA_", "LIBGL_", "__EGL_", "__GLX_", "MOZ_DISABLE_")
    return {key: value for key, value in inherited.items()
            if key not in exact and not key.startswith(prefixes)}


def mesa_inputs(prefix):
    """Name the source ICD and the actual required library entry points."""
    prefix = Path(prefix).resolve(strict=True)
    library_dir = prefix / "lib" / sysconfig.get_config_var("MULTIARCH")
    manifests = sorted((prefix / "share/vulkan/icd.d").glob("lvp_icd*.json"))
    if len(manifests) != 1:
        raise ValueError("Expected one lavapipe manifest in the Mesa prefix")
    paths = {"icd": manifests[0],
             "vulkan": library_dir / "libvulkan_lvp.so",
             "egl": library_dir / "libEGL_mesa.so.0",
             "glx": library_dir / "libGLX_mesa.so.0",
             "dri": library_dir / "dri/swrast_dri.so"}
    for path in paths.values():
        if not path.is_file():
            raise ValueError(f"Missing Mesa runtime file: {path}")
    return paths


def mesa_environment(prefix, run_directory, *, inputs=None):
    """Relocate the packaged lavapipe manifest alongside the caller's private files."""
    inputs = mesa_inputs(prefix) if inputs is None else inputs
    library_dir = inputs["vulkan"].parent
    manifest = json.loads(inputs["icd"].read_text())
    name = Path(manifest["ICD"]["library_path"]).name
    if name != "libvulkan_lvp.so":
        raise ValueError("The selected manifest must identify Mesa lavapipe")
    manifest["ICD"]["library_path"] = str(library_dir / name)
    path = Path(run_directory).resolve() / "lavapipe.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    return {
        "LD_LIBRARY_PATH": str(library_dir),
        "LIBGL_DRIVERS_PATH": str(library_dir / "dri"),
        "VK_DRIVER_FILES": str(path),
        "VK_ICD_FILENAMES": str(path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesa-prefix", type=Path, required=True,
                        help="Extracted Jammy Mesa /usr directory with GL and Vulkan drivers")
    parser.add_argument("--firefox", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True, help="Dedicated desktop profile directory")
    parser.add_argument("url", nargs="?", default="about:blank")
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("Launch Firefox as the desktop user")
    if args.url.startswith("-"):
        parser.error("Expected a URL")
    firefox = args.firefox.resolve(strict=True)
    profile = args.profile.resolve()
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="are-firefox-mesa-") as run:
        env = clean_graphics_environment(os.environ)
        env.update(mesa_environment(args.mesa_prefix, run))
        return subprocess.call([str(firefox), "-no-remote", "-profile", str(profile), args.url], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
