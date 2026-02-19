"""Build a patch zip by comparing the current build with the previous release manifest."""

import json
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

GITHUB_RELEASES_REPO = "DevonTheDev/timco-dwg-releases"


def get_previous_manifest() -> dict | None:
    """Download manifest.json from the latest GitHub release."""
    api_url = f"https://api.github.com/repos/{GITHUB_RELEASES_REPO}/releases/latest"
    headers = {"Accept": "application/vnd.github+json"}

    try:
        req = Request(api_url, headers=headers)
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"Could not fetch latest release: {e}")
        return None

    for asset in data.get("assets", []):
        if asset.get("name") == "manifest.json":
            dl_url = asset["browser_download_url"]
            try:
                req = Request(dl_url, headers=headers)
                with urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode())
            except Exception as e:
                print(f"Could not download previous manifest: {e}")
                return None

    print("No manifest.json in latest release — patch not possible.")
    return None


def build_patch(
    build_dir: Path,
    new_manifest: dict,
    old_manifest: dict,
    output: Path,
) -> bool:
    new_files = new_manifest["files"]
    old_files = old_manifest.get("files", {})

    changed = [f for f, h in new_files.items() if old_files.get(f) != h]
    deleted = [f for f in old_files if f not in new_files]

    if not changed and not deleted:
        print("No file changes detected — skipping patch.")
        return False

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in changed:
            full_path = build_dir / rel_path
            if full_path.exists():
                zf.write(full_path, rel_path)

        # Always include the new manifest so the client stays current
        manifest_path = build_dir / "manifest.json"
        if manifest_path.exists():
            zf.write(manifest_path, "manifest.json")

        # Patch metadata (deleted files list)
        meta = {"deleted": deleted, "changed": changed}
        zf.writestr("_patch_meta.json", json.dumps(meta, indent=2))

    size = output.stat().st_size
    print(f"Patch: {output} ({size:,} bytes)")
    print(f"  Changed: {len(changed)} files")
    print(f"  Deleted: {len(deleted)} files")
    return True


def main():
    if len(sys.argv) < 3:
        print("Usage: python build_patch.py <build_dir> <version>")
        sys.exit(1)

    build_dir = Path(sys.argv[1])
    version = sys.argv[2]

    manifest_path = build_dir / "manifest.json"
    if not manifest_path.exists():
        print("Error: manifest.json not found. Run build_manifest.py first.")
        sys.exit(1)

    new_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    old_manifest = get_previous_manifest()
    if old_manifest is None:
        print("No previous manifest available — skipping patch creation.")
        sys.exit(0)

    output = build_dir.parent / f"TimcoDWG-v{version}-patch.zip"
    build_patch(build_dir, new_manifest, old_manifest, output)


if __name__ == "__main__":
    main()
