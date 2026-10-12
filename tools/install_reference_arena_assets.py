#!/usr/bin/env python3
"""Verify and install supplied original GLBs for the local Three.js reference viewer."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ALIASES = ('mage', 'assassin', 'axe', 'sword', 'log', 'boulder')
CHUNK = 1024 * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, help='user-supplied SoftwareGPU_Referenzarena_GLB_Modelle.zip')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'reference_arena'/'assets')
    args = parser.parse_args()
    manifest = json.loads((ROOT/'evidence'/'original-model-manifest-v1.json').read_text(encoding='utf-8'))
    entries = {item['alias']: item for item in manifest['files'] if 'duplicate_of' not in item}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.archive) as archive:
        members = archive.infolist()
        for alias in ALIASES:
            entry = entries[alias]
            matches = [item for item in members if Path(item.filename).name == entry['file']]
            if len(matches) != 1:
                raise SystemExit(f'{alias}: expected one archive entry named {entry["file"]!r}, found {len(matches)}')
            member = matches[0]
            if member.file_size != entry['bytes']:
                raise SystemExit(f'{alias}: archive size mismatch')
            target = args.output_dir/f'{alias}.glb'
            digest = hashlib.sha256()
            written = 0
            with archive.open(member) as source, tempfile.NamedTemporaryFile(dir=args.output_dir, delete=False) as temp:
                temp_path = Path(temp.name)
                while chunk := source.read(CHUNK):
                    written += len(chunk)
                    if written > entry['bytes']:
                        temp_path.unlink(missing_ok=True)
                        raise SystemExit(f'{alias}: archive expanded past expected size')
                    digest.update(chunk)
                    temp.write(chunk)
            if written != entry['bytes'] or digest.hexdigest() != entry['sha256']:
                temp_path.unlink(missing_ok=True)
                raise SystemExit(f'{alias}: original GLB checksum/size mismatch; no file installed')
            temp_path.replace(target)
            print(f'{alias}: verified {written:,} bytes sha256={digest.hexdigest()} -> {target}')
    print('All six original assets verified. Their GLB files are ignored by Git.')


if __name__ == '__main__':
    main()
