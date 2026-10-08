from setuptools import setup, find_packages

setup(
    name="software_gpu",
    version="1.2.0",
    description="Software GPU Processor on Multi-Core CPU (SIMT, DirectX 11, Gaming AA, VPS Governor, Android IPC)",
    author="SoftwareGPU Team",
    packages=find_packages(),
    py_modules=["main"],
    python_requires=">=3.8",
    install_requires=[
        "numpy>=1.20.0",
    ],
    entry_points={
        "console_scripts": [
            "software-gpu=main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Topic :: Scientific/Engineering",
        "Topic :: Multimedia :: Graphics",
    ],
)
