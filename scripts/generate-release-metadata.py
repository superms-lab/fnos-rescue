from __future__ import annotations

import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version() -> str:
    namespace: dict[str, str] = {}
    exec((ROOT / "src/fnos_rescue/__init__.py").read_text(), namespace)
    return namespace["__version__"]


def components() -> list[dict[str, object]]:
    lock = json.loads((ROOT / "web/package-lock.json").read_text())
    result = []
    for name, data in sorted(lock.get("packages", {}).items()):
        if not name.startswith("node_modules/") or not data.get("version"):
            continue
        package = name.removeprefix("node_modules/")
        result.append({
            "type": "library",
            "name": package,
            "version": data["version"],
            "purl": f"pkg:npm/{package}@{data['version']}",
        })
    return result


def main() -> int:
    DIST.mkdir(exist_ok=True)
    release_version = version()
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {"type": "application", "name": "fnos-rescue", "version": release_version},
        },
        "components": components(),
    }
    sbom_path = DIST / f"fnos-rescue-{release_version}.cdx.json"
    sbom_path.write_text(json.dumps(sbom, ensure_ascii=False, indent=2) + "\n")

    artifacts = [path for path in DIST.iterdir() if path.is_file() and path.name != "SHA256SUMS"]
    (DIST / "SHA256SUMS").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(artifacts))
    )
    print(sbom_path)
    print(DIST / "SHA256SUMS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
