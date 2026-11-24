"""Frozen desktop entry point; the engine CLI remains the canonical runtime."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> int:
    args = sys.argv[1:]
    if args in (["--version"], ["--build-info"]):
        metadata = json.loads((Path(__file__).resolve().parent / "release.json").read_text(encoding="utf-8"))
        print(metadata["version"] if args == ["--version"] else json.dumps(metadata, sort_keys=True))
        return 0
    # Opening the executable must never start the legacy --all stress sequence.
    if not args:
        sys.argv.append("--help")
    import main as engine_cli
    engine_cli.main()
    return 0


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    raise SystemExit(main())
