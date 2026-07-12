from __future__ import annotations

import hashlib
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def _reject_caches(names: list[str], artifact: Path) -> None:
    cached = [name for name in names if "__pycache__" in name or name.endswith((".pyc", ".pyo"))]
    if cached:
        raise RuntimeError(f"cached Python files in {artifact.name}: {cached[0]}")


def verify() -> None:
    wheels = list(DIST.glob("*.whl"))
    sources = list(DIST.glob("*.tar.gz"))
    debs = list(DIST.glob("*.deb"))
    if len(wheels) != 1 or not sources or len(debs) != 1:
        raise RuntimeError("release requires exactly one wheel, one deb, and source/fnOS archives")
    with zipfile.ZipFile(wheels[0]) as archive:
        _reject_caches(archive.namelist(), wheels[0])
        if not any(name.endswith("/web_dist/index.html") for name in archive.namelist()):
            raise RuntimeError("wheel is missing Web assets")
    fnos_found = False
    for source in sources:
        with tarfile.open(source) as archive:
            names = archive.getnames()
            _reject_caches(names, source)
            if any(name.endswith("/manifest.json") for name in names):
                fnos_found = True
                for tool in ("scan_btrfs_roots", "fnos-rescue-btrfs", "fnos-rescue-web.service"):
                    if not any(name.endswith(f"/{tool}") for name in names):
                        raise RuntimeError(f"fnOS archive is missing {tool}")
    if not fnos_found:
        raise RuntimeError("fnOS archive is missing")
    listing = subprocess.run(["dpkg-deb", "--contents", str(debs[0])], check=True, text=True, capture_output=True).stdout
    for tool in ("usr/lib/fnos-rescue/bin/scan_btrfs_roots", "usr/lib/fnos-rescue/bin/fnos-rescue-btrfs"):
        if tool not in listing:
            raise RuntimeError(f"deb is missing {tool}")
    if "__pycache__" in listing or ".pyc" in listing:
        raise RuntimeError("deb contains cached Python files")

    sums = DIST / "SHA256SUMS"
    if not sums.is_file():
        raise RuntimeError("SHA256SUMS is missing")
    for line in sums.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        path = DIST / name.strip()
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"checksum mismatch: {name}")


if __name__ == "__main__":
    try:
        verify()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print("release artifacts verified")
