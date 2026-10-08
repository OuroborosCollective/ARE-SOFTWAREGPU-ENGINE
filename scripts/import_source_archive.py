#!/usr/bin/env python3
"""Source-only, hash-pinned import. Never extract TAR members using extractall()."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

ARCHIVE_SHA256 = "b8b44a39b46ecfb50a2de121b2534c5d9912fccda2b1b0475faf194fe8e589b8"
SOURCE_COUNT = 62
SOURCE_EXTENSIONS = frozenset({".py", ".md", ".go", ".hpp", ".js", ".cs", ".rs", ".h", ".kt"})
UPSTREAM_NOTICE = (
    "# Original upstream README - unverified claims\n\n"
    "Preserved for provenance. Performance and native CUDA, DirectX or Android "
    "compatibility have not been independently verified.\n\n---\n\n"
)


def collect(archive: Path) -> tuple[str, list[tuple[str, bytes]]]:
    with archive.open("rb") as fp:
        digest = hashlib.file_digest(fp, "sha256").hexdigest()
    if digest != ARCHIVE_SHA256:
        raise ValueError(f"Archive SHA-256 mismatch: {digest}")
    seen: set[str] = set()
    output: list[tuple[str, bytes]] = []
    total = 0
    with tarfile.open(archive, "r:*") as tf:
        members = tf.getmembers()
        if len(members) > 2048:
            raise ValueError("Too many TAR entries")
        for member in members:
            name = member.name[2:] if member.name.startswith("./") else member.name
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe archive path: {name}")
            if member.issym() or member.islnk():
                if name.startswith("workspace/software_gpu/") and "__pycache__" not in path.parts:
                    raise ValueError(f"Linked source is forbidden: {name}")
                continue
            if not member.isfile() or not name.startswith("workspace/"):
                continue
            subpath = name[len("workspace/"):]
            sub = PurePosixPath(subpath)
            if subpath not in {"README.md", "main.py", "setup.py"} and not (
                subpath.startswith("software_gpu/")
                and sub.suffix in SOURCE_EXTENSIONS
                and "__pycache__" not in sub.parts
            ):
                continue
            dest = "docs/UPSTREAM_README.md" if subpath == "README.md" else subpath
            if dest in seen or member.size > 131072 or member.size < 0:
                raise ValueError(f"Duplicate or oversized source: {dest}")
            seen.add(dest)
            src = tf.extractfile(member)
            if src is None:
                raise ValueError(f"Unreadable TAR member: {name}")
            raw = src.read()
            content = raw.decode("utf-8")
            if "\x00" in content:
                raise ValueError(f"NUL character in source: {dest}")
            if subpath == "README.md":
                content = UPSTREAM_NOTICE + content
            encoded = content.encode("utf-8")
            total += len(encoded)
            if total > 2_000_000:
                raise ValueError("Aggregate source-size limit exceeded")
            output.append((dest, encoded))
    if len(output) != SOURCE_COUNT:
        raise ValueError(f"Expected {SOURCE_COUNT} sources, found {len(output)}")
    return digest, sorted(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=Path("."))
    args = parser.parse_args()
    digest, sources = collect(args.archive)
    root = args.destination.resolve()
    entries: list[dict[str, object]] = []
    # Validate ALL destinations before writing any source.
    for relative, data in sources:
        target = (root / relative).resolve()
        if root not in target.parents:
            raise ValueError(f"Destination escapes checkout: {relative}")
        if target.exists() and target.read_bytes() != data:
            raise ValueError(f"Would overwrite modified source: {relative}")
    for relative, data in sources:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        entries.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    manifest = root / "evidence/source-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({
            "archive_sha256": digest,
            "archive_version": "1.2.0",
            "source_file_count": len(entries),
            "verified_native_gpu_compatibility": False,
            "files": entries,
        }, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"IMPORT_OK count={len(entries)} archive_sha256={digest}")


if __name__ == "__main__":
    main()
