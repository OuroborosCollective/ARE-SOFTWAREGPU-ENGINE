"""Real native mip generation against independent area-overlap references."""
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest

from software_gpu.research.native_symbolic import FLAGS, NATIVE, compiler


HARNESS = r'''#include "model_material.hpp"
#include <iomanip>
#include <iostream>
using namespace are::rooms;
int main() {
    unsigned width,height,srgb,count;
    if(!(std::cin>>width>>height>>srgb>>count))return 2;
    SurfaceTexture texture;texture.srgb=srgb!=0;
    SurfaceMip base;base.width=width;base.height=height;
    for(unsigned i=0;i<count;++i){unsigned byte;if(!(std::cin>>byte)||byte>255)return 2;
        base.rgba.push_back(std::uint8_t(byte));}
    texture.mips.push_back(std::move(base));
    try{texture.build_mips();}catch(const std::exception& e){std::cerr<<e.what();return 1;}
    std::cout<<"{\"mips\":[";
    for(std::size_t level=0;level<texture.mips.size();++level){
        if(level)std::cout<<',';
        const auto& m=texture.mips[level];
        std::cout<<"{\"width\":"<<m.width<<",\"height\":"<<m.height<<",\"rgba\":[";
        for(std::size_t i=0;i<m.rgba.size();++i){if(i)std::cout<<',';std::cout<<unsigned(m.rgba[i]);}
        std::cout<<"]}";
    }
    // Exercise the real gradient-based minification path at its coarsest level.
    const auto sample=surface_sample_grad(texture,{.5f,.5f},{32,0},{0,32});
    std::cout<<"],\"sample\":["<<std::setprecision(17);
    for(unsigned c=0;c<4;++c){if(c)std::cout<<',';std::cout<<sample[c];}
    std::cout<<"]}\n";
}
'''


def _decode(byte):
    value = byte / 255
    return value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4


def _area_reference(width, height, rgba, srgb):
    """Integrate complete source texel cells using exact rational overlaps."""
    dw, dh = max(1, width // 2), max(1, height // 2)
    result = []
    for y in range(dh):
        for x in range(dw):
            left, right = Fraction(x * width, dw), Fraction((x + 1) * width, dw)
            top, bottom = Fraction(y * height, dh), Fraction((y + 1) * height, dh)
            samples = []
            # Deliberately scan all source cells, independent of the native bounds.
            for sy in range(height):
                oy = max(Fraction(0), min(bottom, sy + 1) - max(top, sy))
                for sx in range(width):
                    ox = max(Fraction(0), min(right, sx + 1) - max(left, sx))
                    if ox and oy:
                        samples.append(((sy * width + sx) * 4, ox * oy / ((right-left) * (bottom-top))))
            for c in range(4):
                if srgb and c < 3:
                    value = math.fsum(_decode(rgba[at+c]) * float(weight) for at, weight in samples)
                    encoded = 12.92 * value if value <= .0031308 else 1.055 * value ** (1/2.4) - .055
                    result.append(math.floor(encoded * 255 + .5))
                else:
                    value = sum((rgba[at+c] * weight for at, weight in samples), Fraction(0))
                    result.append(math.floor(value + Fraction(1, 2)))
    return dict(width=dw, height=dh, rgba=result)


def _pattern(width, height):
    return [(17*x + 53*y + 19*c) % 256
            for y in range(height) for x in range(width) for c in range(4)]


class TestNativeMipCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='are-mip-coverage-')
        root = Path(cls.temp.name)
        source = root / 'mips.cpp'
        source.write_text(HARNESS, encoding='utf-8')
        cls.exe = root / 'mips'
        built = subprocess.run([compiler(), *FLAGS, f'-I{NATIVE}', str(source), '-o', str(cls.exe)],
                               capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise RuntimeError('MODEL_MIP_TEST_BUILD:' + built.stderr[-6000:])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def native(self, width, height, rgba, srgb=False, error=None):
        data = f'{width} {height} {int(srgb)} {len(rgba)}\n' + ' '.join(map(str, rgba))
        result = subprocess.run([str(self.exe)], input=data, capture_output=True, text=True, timeout=10)
        if error is not None:
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(result.stderr, error)
            return None
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_last_row_and_column_reach_mips_and_minified_sampling(self):
        for width, height in ((3, 1), (1, 3), (3, 3), (3, 2), (2, 3)):
            for srgb in (False, True):
                with self.subTest(size=(width, height), srgb=srgb):
                    pixels = [0, 0, 0, 255] * (width * height)
                    pixels[-4:] = [255, 255, 255, 255]
                    actual = self.native(width, height, pixels, srgb)
                    expected = _area_reference(width, height, pixels, srgb)
                    self.assertEqual(actual['mips'][1], expected)
                    expected_sample = _decode(expected['rgba'][0]) if srgb else expected['rgba'][0] / 255
                    self.assertGreater(expected_sample, 0)
                    for value in actual['sample'][:3]:
                        self.assertAlmostEqual(value, expected_sample, places=14)
                    self.assertEqual(actual['sample'][3], 1)

    def test_odd_and_mixed_dimensions_match_independent_area_reference(self):
        for width, height in ((5, 1), (1, 5), (5, 3), (3, 5), (7, 6), (6, 7), (9, 2), (2, 9), (15, 9)):
            for srgb in (False, True):
                with self.subTest(size=(width, height), srgb=srgb):
                    actual = self.native(width, height, _pattern(width, height), srgb)['mips']
                    for previous, current in zip(actual, actual[1:]):
                        # Even levels have an independently frozen byte-parity gate below.
                        if any(n > 1 and n % 2 for n in (previous['width'], previous['height'])):
                            self.assertEqual(current, _area_reference(**previous, srgb=srgb))
                    self.assertEqual((actual[-1]['width'], actual[-1]['height']), (1, 1))

    def test_constant_rgb_and_linear_alpha_survive(self):
        for color in ([10, 11, 128, 17], [255, 0, 255, 0], [17, 33, 85, 255]):
            for srgb in (False, True):
                with self.subTest(color=color, srgb=srgb):
                    actual = self.native(9, 5, color * 45, srgb)
                    for mip in actual['mips']:
                        self.assertEqual(mip['rgba'], color * (mip['width'] * mip['height']))

    def test_even_levels_keep_original_bytes(self):
        observed = []
        for width, height in ((1, 1), (2, 2), (1, 16), (16, 1), (8, 4), (16, 16), (6, 4), (10, 6)):
            for srgb in (False, True):
                mips = self.native(width, height, _pattern(width, height), srgb)['mips']
                # Non-power-of-two inputs eventually reach odd levels; only the
                # base and first (even-source) level retain the old contract there.
                observed.append(mips[:2] if width in (6, 10) else mips)
        digest = hashlib.sha256(json.dumps(observed, separators=(',', ':')).encode()).hexdigest()
        # Captured from the actual native pre-fix source at 1f4d48d38c58ccabdb6d695aa9caddfdefdc945e.
        self.assertEqual(digest, 'f5f8389c2a63e30035ba5b89828af5d2fd5979a1c475aca87f183fda2d841e31')

    def test_largest_odd_axis_keeps_last_texel(self):
        for width, height in ((4095, 1), (1, 4095)):
            for srgb in (False, True):
                with self.subTest(size=(width, height), srgb=srgb):
                    pixels = [0, 0, 0, 255] * (width * height)
                    pixels[-4:] = [255, 255, 255, 255]
                    first = self.native(width, height, pixels, srgb)['mips'][1]
                    # The last cell's coverage is exactly 2047/4095 of the destination cell.
                    expected = 187 if srgb else 127
                    self.assertEqual(first['rgba'][-4:], [expected] * 3 + [255])

    def test_shape_and_dimension_rejections_remain(self):
        self.native(0, 1, [], error='MODEL_TEXTURE_SHAPE')
        self.native(2, 1, [255] * 4, error='MODEL_TEXTURE_SHAPE')
        self.native(4097, 1, [255] * (4097 * 4), error='MODEL_TEXTURE_DIMENSIONS')


if __name__ == '__main__':
    unittest.main()
