"""Generate manifest.json with SHA-256 hashes for every file in the build."""

import hashlib
import json
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(build_dir: Path, version: str) -> dict:
    files = {}
    for p in sorted(build_dir.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            rel = p.relative_to(build_dir).as_posix()
            files[rel] = sha256_file(p)
    return {"version": version, "files": files}


def main():
    if len(sys.argv) < 3:
        print("Usage: python build_manifest.py <build_dir> <version>")
        sys.exit(1)

    build_dir = Path(sys.argv[1])
    version = sys.argv[2]

    if not build_dir.is_dir():
        print(f"Error: {build_dir} is not a directory")
        sys.exit(1)

    manifest = build_manifest(build_dir, version)
    out_path = build_dir / "manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest: {out_path} ({len(manifest['files'])} files)")


if __name__ == "__main__":
    main()
