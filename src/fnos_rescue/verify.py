from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

from .runner import run


@dataclass(frozen=True)
class VerificationResult:
    path: str
    size: int
    sha256: str
    detected_type: str
    non_empty: bool


def sha256_file(path: Path, chunk_size: int = 4 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: str | Path) -> VerificationResult:
    source = Path(path)
    size = source.stat().st_size
    file_result = run(["file", "--brief", "--", source], check=False)
    detected = file_result.stdout.strip() or mimetypes.guess_type(source.name)[0] or "unknown"
    return VerificationResult(
        path=str(source),
        size=size,
        sha256=sha256_file(source),
        detected_type=detected,
        non_empty=size > 0,
    )


def iter_files(path: Path) -> Iterator[Path]:
    if path.is_file():
        yield path
        return
    for child in path.rglob("*"):
        if child.is_file():
            yield child


def verify_samples(path: str | Path, limit: int = 10) -> list[dict[str, object]]:
    results = []
    for source in iter_files(Path(path)):
        if source.stat().st_size == 0:
            continue
        results.append(asdict(verify_file(source)))
        if len(results) >= limit:
            break
    return results
