"""Build the release zip: dist/ForgeLabNavigator-<version>.zip (+ .sha256).

Contains only the plugin folder (no caches, no user state), plus a
MANIFEST.json with every file's SHA-256 so an install can be verified.
Local preparation only; nothing is uploaded.
"""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin" / "ForgeLabNavigator"
sys.path.insert(0, str(PLUGIN))
from forgelab_nav import __version__  # noqa: E402

SKIP_DIRS = {"__pycache__", "user"}


def files():
    for path in sorted(PLUGIN.rglob("*")):
        if path.is_file() and not SKIP_DIRS.intersection(path.relative_to(PLUGIN).parts) \
                and path.suffix not in (".pyc", ".tmp"):
            yield path


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    manifest = {"name": "ForgeLab Navigator", "version": __version__,
                "files": {p.relative_to(PLUGIN).as_posix(): sha(p) for p in files()}}
    out = dist / f"ForgeLabNavigator-{__version__}.zip"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in files():
            z.write(path, "ForgeLabNavigator/" + path.relative_to(PLUGIN).as_posix())
        z.writestr("ForgeLabNavigator/MANIFEST.json", json.dumps(manifest, indent=1, sort_keys=True))
    digest = sha(out)
    (dist / (out.name + ".sha256")).write_text(f"{digest}  {out.name}\n")
    size = sum((PLUGIN / f).stat().st_size for f in manifest["files"])
    print(f"{out.name}: {out.stat().st_size / 1e6:.1f} MB zipped, {size / 1e6:.1f} MB installed, "
          f"{len(manifest['files'])} files, sha256 {digest[:16]}")


if __name__ == "__main__":
    main()
