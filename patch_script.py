import re

with open('software_gpu/graphics/shader.py', 'r') as f:
    content = f.read()

# Add math to imports
if 'import math' not in content:
    content = re.sub(r'import numpy as np', 'import math\nimport numpy as np', content)

search_pattern = r"""        import math
        if math\.isnan\(r\) or math\.isnan\(g\) or math\.isnan\(b\):
            raise ValueError\("NaN"\)

        return \(
            0 if r < 0\.0 else 255 if r >= 1\.0 else int\(np\.float64\(r\) \* 255\.0\),
            0 if g < 0\.0 else 255 if g >= 1\.0 else int\(np\.float64\(g\) \* 255\.0\),
            0 if b < 0\.0 else 255 if b >= 1\.0 else int\(np\.float64\(b\) \* 255\.0\),
            255
        \)"""

replacement = """        if math.isnan(r) or math.isnan(g) or math.isnan(b):
            raise ValueError("NaN")

        return (
            0 if r < 0.0 else 255 if r >= 1.0 else int(r * 255.0),
            0 if g < 0.0 else 255 if g >= 1.0 else int(g * 255.0),
            0 if b < 0.0 else 255 if b >= 1.0 else int(b * 255.0),
            255
        )"""

content = re.sub(search_pattern, replacement, content)

with open('software_gpu/graphics/shader.py', 'w') as f:
    f.write(content)
