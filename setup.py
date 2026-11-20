from pathlib import Path
from setuptools import setup, find_packages

setup(
    name="ouroboroscollective-softwaregpu",
    version="1.2.0",
    description="Software GPU Processor on Multi-Core CPU (SIMT, DirectX 11, Gaming AA, VPS Governor, Android IPC)",
    author="OuroborosCollective",
    author_email=None,
    url="https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE",
    project_urls={
        "Documentation": "https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/blob/main/docs/QUICKSTART.md",
        "Source": "https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE",
        "Issues": "https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/issues",
        "Releases": "https://github.com/OuroborosCollective/ARE-SOFTWAREGPU-ENGINE/releases",
    },
    long_description=(Path(__file__).parent / "docs" / "PYPI_PACKAGE.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    license="PolyForm-Noncommercial-1.0.0",
    license_files=["LICENSE.md", "NOTICE"],
    keywords=["software gpu", "cpu renderer", "rasterization", "graphics", "deterministic", "research"],
    packages=find_packages(),
    py_modules=["main"],
    python_requires=">=3.11,<3.13",
    install_requires=[
        "numpy>=1.20.0",
    ],
    extras_require={
        # CPU LLVM JIT acceleration is opt-in. The default distribution
        # remains minimal and runs without Numba or a GPU.
        "jit": ["numba>=0.61.2,<0.67"],
        # Offline PNG/JPEG decoding is only needed for the opt-in AREMDL03 profile.
        "model-pbr": ["Pillow>=9.0"],
        # Private, opt-in research console. No web service in the default install.
        "gradio-arena": ["gradio>=5,<7", "Pillow>=9.0"],
    },
    entry_points={
        "console_scripts": [
            "software-gpu=main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering",
        "Topic :: Multimedia :: Graphics",
    ],
)
