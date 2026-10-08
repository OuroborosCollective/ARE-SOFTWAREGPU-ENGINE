"""Host-neutral, user-configurable output location for CPU rendering demos."""
import os
from pathlib import Path


def output_file(filename: str) -> str:
    """Return an output path in current working directory or explicit output dir."""
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
        raise ValueError("Output filename must be a basename")
    root = Path(os.environ.get("ARE_SOFTWAREGPU_OUTPUT_DIR") or os.getcwd()).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return str(root / filename)
