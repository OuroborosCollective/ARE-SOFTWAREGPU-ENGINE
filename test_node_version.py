import subprocess
import shutil

node = shutil.which("node")
if node:
    result = subprocess.run([node, "-v"], capture_output=True, text=True)
    print(f"Node version: {result.stdout}")
else:
    print("Node not found")
