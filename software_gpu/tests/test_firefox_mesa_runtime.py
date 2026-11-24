"""Environment and manifest control regressions for the process-local Linux launcher."""
import json
from pathlib import Path
import sysconfig
import tempfile
import unittest

from tools.firefox_addon_runtime import clean_graphics_environment, mesa_environment, mesa_inputs


class FirefoxMesaRuntimeTest(unittest.TestCase):
    def test_retains_desktop_session_and_clears_driver_selection(self):
        desktop = {'DISPLAY': ':1', 'WAYLAND_DISPLAY': 'wayland-0', 'XAUTHORITY': '/session/auth'}
        inherited = dict(desktop, VK_LOADER_DRIVERS_SELECT='old*', VK_LOADER_DRIVERS_DISABLE='*',
                         LD_PRELOAD='other.so', LD_LIBRARY_PATH='/old', MESA_LOADER_DRIVER_OVERRIDE='old',
                         __EGL_VENDOR_LIBRARY_FILENAMES='/old', GALLIUM_DRIVER='other')
        self.assertEqual(clean_graphics_environment(inherited), desktop)
        self.assertIn('LD_LIBRARY_PATH', inherited)

    @unittest.skipUnless(sysconfig.get_config_var('MULTIARCH'), 'Linux multiarch layout')
    def test_receipt_inputs_and_relocated_icd_agree(self):
        # These are deliberately empty fixture libraries. No rendering claim is made here.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            library = root / 'lib' / sysconfig.get_config_var('MULTIARCH')
            (library / 'dri').mkdir(parents=True)
            for relative in ('libvulkan_lvp.so', 'libEGL_mesa.so.0', 'libGLX_mesa.so.0', 'dri/swrast_dri.so'):
                (library / relative).touch()
            directory = root / 'share/vulkan/icd.d'
            directory.mkdir(parents=True)
            source = directory / 'lvp_icd.json'
            source.write_text(json.dumps({'ICD': {'library_path': '/usr/lib/libvulkan_lvp.so'}}))
            inputs = mesa_inputs(root)
            env = mesa_environment(root, root, inputs=inputs)
            self.assertEqual(set(inputs), {'icd', 'egl', 'glx', 'dri', 'vulkan'})
            self.assertEqual(inputs['icd'], source)
            manifest = json.loads(Path(env['VK_DRIVER_FILES']).read_text())
            self.assertEqual(Path(manifest['ICD']['library_path']), inputs['vulkan'])
