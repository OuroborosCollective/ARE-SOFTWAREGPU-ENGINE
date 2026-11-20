"""Distribution version for a checkout, release builder, or unpacked source distribution."""
from email.parser import Parser
import os
from pathlib import Path
import re


def build_version(root):
    tag = os.environ.get("ARE_BUILD_TAG")
    if tag:
        match = re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta|rc)\.(0|[1-9]\d*))?", tag)
        if not match:
            raise ValueError(f"Invalid release tag {tag!r}")
        base = ".".join(match.groups()[:3])
        return base + ({"alpha": "a", "beta": "b", "rc": "rc"}[match[4]] + match[5] if match[4] else "")
    metadata = Path(root) / "PKG-INFO"
    if metadata.is_file():
        return Parser().parsestr(metadata.read_text(encoding="utf-8"), headersonly=True)["Version"]
    return "1.2.1"
