from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
import shutil
import sqlite3
import struct
import subprocess
import tarfile
import xml.etree.ElementTree as ET
import zipfile
import zlib
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
    classification: str
    validator: str
    validation_ok: bool | None
    validation_error: str | None


def sha256_file(path: Path, chunk_size: int = 4 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _consume(handle, chunk_size: int = 4 << 20) -> None:
    while handle.read(chunk_size):
        pass


def _validate_png(path: Path) -> None:
    with path.open("rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError("invalid PNG signature")
        seen_iend = False
        while not seen_iend:
            length_bytes = handle.read(4)
            if len(length_bytes) != 4:
                raise ValueError("truncated PNG chunk length")
            length = struct.unpack(">I", length_bytes)[0]
            if length > 64 << 20:
                raise ValueError("unreasonable PNG chunk length")
            kind = handle.read(4)
            data = handle.read(length)
            checksum = handle.read(4)
            if len(kind) != 4 or len(data) != length or len(checksum) != 4:
                raise ValueError("truncated PNG chunk")
            expected = struct.unpack(">I", checksum)[0]
            actual = zlib.crc32(kind + data) & 0xFFFFFFFF
            if expected != actual:
                raise ValueError("PNG chunk checksum mismatch")
            seen_iend = kind == b"IEND"
        if handle.read(1):
            raise ValueError("unexpected bytes after PNG IEND")


def _validate_structure(path: Path) -> tuple[str, bool | None, str | None]:
    suffix = path.suffix.lower()
    with path.open("rb") as handle:
        head = handle.read(16)

    try:
        if head.startswith(b"PK\x03\x04") or suffix in {".zip", ".docx", ".xlsx", ".pptx", ".jar", ".apk"}:
            with zipfile.ZipFile(path) as archive:
                bad = archive.testzip()
                if bad:
                    raise ValueError(f"ZIP CRC failure in {bad}")
            return "zip-crc", True, None
        if head.startswith(b"\x1f\x8b") or suffix == ".gz":
            with gzip.open(path, "rb") as handle:
                _consume(handle)
            return "gzip-crc", True, None
        if tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as archive:
                for member in archive:
                    if member.isfile():
                        extracted = archive.extractfile(member)
                        if extracted is None:
                            raise ValueError(f"cannot read TAR member {member.name}")
                        with extracted:
                            _consume(extracted)
            return "tar-stream", True, None
        if head.startswith(b"\x89PNG\r\n\x1a\n") or suffix == ".png":
            _validate_png(path)
            return "png-crc", True, None
        if head.startswith(b"\xff\xd8") or suffix in {".jpg", ".jpeg"}:
            with path.open("rb") as handle:
                handle.seek(-2, 2)
                if handle.read(2) != b"\xff\xd9":
                    raise ValueError("JPEG end marker is missing")
            return "jpeg-markers", True, None
        if head.startswith((b"GIF87a", b"GIF89a")) or suffix == ".gif":
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - 64))
                if not handle.read().rstrip(b"\x00").endswith(b";"):
                    raise ValueError("GIF trailer is missing")
            return "gif-trailer", True, None
        if head.startswith(b"%PDF-") or suffix == ".pdf":
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - (1 << 20)))
                if b"%%EOF" not in handle.read():
                    raise ValueError("PDF EOF marker is missing")
            return "pdf-envelope", True, None
        if head.startswith(b"SQLite format 3\x00") or suffix in {".sqlite", ".sqlite3", ".db"}:
            uri = f"file:{path.resolve()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as database:
                result = database.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                raise ValueError(f"SQLite quick_check failed: {result}")
            return "sqlite-quick-check", True, None
        if suffix == ".json":
            with path.open("r", encoding="utf-8") as handle:
                json.load(handle)
            return "json-parser", True, None
        if suffix in {".xml", ".svg"}:
            ET.parse(path)
            return "xml-parser", True, None
        if suffix in {".txt", ".md", ".csv", ".tsv", ".log", ".ini", ".conf", ".yaml", ".yml"}:
            with path.open("r", encoding="utf-8") as handle:
                _consume(handle)
            return "utf8-decoder", True, None
        if suffix in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".mp3", ".m4a", ".flac", ".wav", ".ogg"}:
            ffprobe = shutil.which("ffprobe")
            if ffprobe is None:
                return "ffprobe-unavailable", None, "no structural validator is installed"
            subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=format_name,duration", "-of", "json", str(path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return "ffprobe", True, None
    except (OSError, ValueError, EOFError, gzip.BadGzipFile, tarfile.TarError, zipfile.BadZipFile,
            sqlite3.DatabaseError, ET.ParseError, subprocess.SubprocessError) as exc:
        return "structural-parser", False, str(exc)
    return "none", None, "no structural validator is available for this file type"


def verify_file(
    path: str | Path,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
    expected_empty: bool = False,
) -> VerificationResult:
    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise ValueError(f"verification target must be a regular non-symlink file: {source}")
    size = source.stat().st_size
    digest = sha256_file(source)
    file_result = run(["file", "--brief", "--", source], check=False)
    detected = file_result.stdout.strip() or mimetypes.guess_type(source.name)[0] or "unknown"

    if expected_size is not None and size != expected_size:
        validator, ok, error = "expected-size", False, f"expected {expected_size} bytes, got {size}"
    elif expected_sha256 is not None:
        normalized = expected_sha256.strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            validator, ok, error = "expected-sha256", False, "expected SHA256 is invalid"
        elif digest != normalized:
            validator, ok, error = "expected-sha256", False, "SHA256 does not match trusted inventory"
        else:
            validator, ok, error = "expected-sha256", True, None
    elif size == 0:
        if expected_empty and expected_size == 0:
            validator, ok, error = "inode-size-and-extractor-status", True, None
        else:
            validator, ok, error = "empty-unclassified", None, "zero bytes without trusted empty-file evidence"
    else:
        validator, ok, error = _validate_structure(source)

    if size == 0 and ok is True:
        classification = "genuine_empty"
    elif ok is True:
        classification = "validated"
    elif ok is False:
        classification = "invalid"
    else:
        classification = "unvalidated"
    return VerificationResult(
        path=str(source),
        size=size,
        sha256=digest,
        detected_type=detected,
        non_empty=size > 0,
        classification=classification,
        validator=validator,
        validation_ok=ok,
        validation_error=error,
    )


def iter_files(path: Path) -> Iterator[Path]:
    if path.is_file() and not path.is_symlink():
        yield path
        return
    for child in path.rglob("*"):
        if child.is_file() and not child.is_symlink():
            yield child


def verify_samples(path: str | Path, limit: int = 10) -> list[dict[str, object]]:
    results = []
    for source in iter_files(Path(path)):
        results.append(asdict(verify_file(source)))
        if len(results) >= limit:
            break
    return results
