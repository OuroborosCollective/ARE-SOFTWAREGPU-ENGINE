"""SHA-pinned original Meshy GLB download/admission; no substitute models or stub measurements."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from urllib.parse import urlparse

MANIFEST = Path(__file__).resolve().parents[1] / "evidence" / "meshy-public-assets-20261013.json"
CHUNK = 1024*1024


def load_manifest(path=MANIFEST):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value.get("protocol") != "are.meshy-owner-approved-public-assets.v1":
        raise ValueError("MESHY_MANIFEST_PROTOCOL")
    if len(value.get("assets", [])) != 3:
        raise ValueError("MESHY_MANIFEST_ASSET_COUNT")
    names = set()
    for asset in value["assets"]:
        alias, digest, n = asset["alias"], asset["sha256"], asset["bytes"]
        if alias in names or alias not in ("azure-knight","crimson-dragon","maize-field"):
            raise ValueError("MESHY_ALIAS")
        names.add(alias)
        if type(n) is not int or not 32 <= n <= 300000000 or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("MESHY_HASH_OR_SIZE")
        url = asset.get("source_url")
        if url is not None and (urlparse(url).scheme != "https"
                or urlparse(url).hostname != "d2ol7oe51mr4n9.cloudfront.net"):
            raise ValueError("MESHY_SOURCE_HOST")
    return value


def verify(path, asset):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != asset["bytes"]:
        raise ValueError("MESHY_SIZE_MISMATCH")
    h = hashlib.sha256()
    with path.open("rb") as f:
        if f.read(4) != b"glTF":
            raise ValueError("MESHY_NOT_GLB")
        f.seek(0)
        while buf := f.read(CHUNK):
            h.update(buf)
    if h.hexdigest() != asset["sha256"]:
        raise ValueError("MESHY_HASH_MISMATCH")
    return {"alias":asset["alias"],"bytes":asset["bytes"],"sha256":h.hexdigest(),"verified":True}


def fetch_one(asset, dest):
    if not asset.get("source_url"):
        raise ValueError("MESHY_PUBLIC_SOURCE_NOT_READY")
    dest = Path(dest)
    if dest.is_file():
        return verify(dest, asset)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(".unverified")
    temp.unlink(missing_ok=True)
    try:
        req = urllib.request.Request(asset["source_url"], headers={"User-Agent":"ARE-SoftwareGPU-Asset-Verification/1.0"})
        with urllib.request.urlopen(req, timeout=40) as r, temp.open("wb") as out:
            if r.status != 200:
                raise ValueError("MESHY_HTTP_STATUS")
            limit = asset["bytes"]
            written=0
            while buf := r.read(CHUNK):
                written+=len(buf)
                if written>limit:
                    raise ValueError("MESHY_TOO_LARGE")
                out.write(buf)
        receipt = verify(temp, asset)
        temp.replace(dest)
        return receipt
    finally:
        temp.unlink(missing_ok=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--aliases",nargs="+",default=["azure-knight","crimson-dragon"])
    p.add_argument("--verify-only",action="store_true")
    p.add_argument("--receipt",type=Path)
    a=p.parse_args()
    manifest=load_manifest()
    known={e["alias"]:e for e in manifest["assets"]}
    if len(set(a.aliases))!=len(a.aliases) or any(alias not in known for alias in a.aliases):
        p.error("invalid or duplicate aliases")
    results=[]
    for alias in a.aliases:
        asset=known[alias]; path=a.output_dir / asset["file"]
        results.append(verify(path,asset) if a.verify_only else fetch_one(asset,path))
    report={"protocol":"are.meshy.original-asset-readback.v1","status":"PASS",
            "assets":results,"originals_modified":False}
    if a.receipt:
        a.receipt.parent.mkdir(parents=True,exist_ok=True)
        a.receipt.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
