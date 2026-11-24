#!/usr/bin/env python3
"""Derive the existing release version from the exact checkout's first parents."""
import argparse
import os
from pathlib import Path
import subprocess

from release_gate import release_tag_for_lineage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if head != args.sha:
        raise SystemExit("Release version checkout differs from event SHA")
    lineage = subprocess.check_output(["git", "rev-list", "--first-parent", head], text=True).splitlines()
    tag = release_tag_for_lineage(lineage, head)
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and os.environ.get("GITHUB_REF_NAME") != tag:
        raise SystemExit("Tag does not match first-parent release version")
    result = f"tag={tag}\nversion={tag[1:]}\n"
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as destination:
            destination.write(result)
    print(result, end="")


if __name__ == "__main__":
    main()
