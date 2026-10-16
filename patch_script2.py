import re

with open('software_gpu/graphics/shader.py', 'r') as f:
    content = f.read()

# Add math to imports
if 'import math' not in content:
    content = re.sub(r'import numpy as np', 'import math\nimport numpy as np', content)

with open('software_gpu/graphics/shader.py', 'w') as f:
    f.write(content)
