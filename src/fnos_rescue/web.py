from __future__ import annotations

import getpass
import csv
import io
import json
import platform
import socket
import re
import secrets
from dataclasses import asdict
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.parse import parse_qs

from .cases import RecoveryCase
from .devices import DeviceFacts, inspect_device
from .destinations import assert_destination_ready, inspect_destination
from .errors import RescueError
from .executors import start_background
from .jobs import JobStore
from .runner import run
from .safety import assert_destination_not_source, confirm_serial, protect_source

MAX_BODY_BYTES = 16_384
CASE_ID = re.compile(r"^case-[0-9a-f]{12}$")
WEB_JOB_PARAMETERS = {
    "copy": {"source_device", "source_root", "destination", "paths"},
    "verify": {"path", "limit"},
    "btrfs-probe": {"device"},
    "btrfs-root-scan": {"device", "fsid", "start_gib", "end_gib", "timeout"},
    "btrfs-chunk-cache": {"device", "timeout"},
    "btrfs-list": {"device", "chunk_cache", "filesystem_root", "timeout"},
    "btrfs-extract-batch": {"device", "chunk_cache", "filesystem_root", "items", "per_file_timeout"},
}


def default_case_root() -> Path:
    return Path.home() / ".local" / "share" / "fnos-rescue" / "cases"


def case_directory(case_id: str, root: Path | None = None) -> Path:
    if not CASE_ID.fullmatch(case_id):
        raise ValueError("invalid case id")
    return (root or default_case_root()) / case_id


def list_cases(root: Path | None = None) -> list[dict[str, Any]]:
    base = root or default_case_root()
    if not base.is_dir():
        return []
    return [RecoveryCase.load(path).to_dict() for path in sorted(base.glob("case-*/case.json"))]


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1000 or unit == "PB":
            return f"{value:.2f} {unit}"
        value /= 1000
    return f"{value:.2f} PB"


def list_devices() -> list[dict[str, Any]]:
    if platform.system() != "Linux":
        return []
    result = run([
        "lsblk", "--json", "--bytes", "--output",
        "NAME,PATH,SIZE,RO,TYPE,FSTYPE,MODEL,SERIAL,UUID,MOUNTPOINTS",
    ])
    document = json.loads(result.stdout)
    devices: list[dict[str, Any]] = []
    for item in document.get("blockdevices", []):
        facts = _facts_from_lsblk(item)
        if facts.device_type not in {"disk", "loop", "nbd"}:
            continue
        devices.append({
            **asdict(facts),
            "size": _human_size(facts.size_bytes),
            "status": "只读保护" if facts.read_only else "待检查",
        })
    return devices


def _facts_from_lsblk(item: dict[str, Any]) -> DeviceFacts:
    return DeviceFacts(
        path=str(item.get("path") or f"/dev/{item['name']}"),
        name=str(item["name"]),
        size_bytes=int(item.get("size") or 0),
        read_only=bool(int(item.get("ro") or 0)),
        device_type=str(item.get("type") or "unknown"),
        filesystem=item.get("fstype"),
        model=(item.get("model") or "").strip() or None,
        serial=(item.get("serial") or "").strip() or None,
        uuid=item.get("uuid"),
        mountpoints=tuple(str(point) for point in item.get("mountpoints") or [] if point),
        children=tuple(_facts_from_lsblk(child) for child in item.get("children") or []),
    )


def environment() -> dict[str, Any]:
    return {
        "platform": platform.system(),
        "hostname": socket.gethostname(),
        "user": getpass.getuser(),
        "live": True,
    }


class RescueWebHandler(SimpleHTTPRequestHandler):
    server_version = "FNOSRescue/0.1"

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._json(HTTPStatus.OK, {"ok": True, "service": "fnos-rescue"})
            return
        if path == "/api/devices":
            try:
                self._json(HTTPStatus.OK, {"devices": list_devices(), "environment": environment(), "csrf_token": self.server.csrf_token})
            except (OSError, RescueError, ValueError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        if path == "/api/cases":
            self._json(HTTPStatus.OK, {"cases": list_cases()})
            return
        if path == "/api/jobs":
            try:
                case_id = parse_qs(parsed.query).get("case", [""])[0]
                jobs = JobStore(case_directory(case_id)).list()
                self._json(HTTPStatus.OK, {"jobs": [job.to_dict() for job in jobs]})
            except (OSError, RescueError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if path == "/api/job-status":
            try:
                query = parse_qs(parsed.query)
                case_id = query.get("case", [""])[0]
                job_id = query.get("job", [""])[0]
                store = JobStore(case_directory(case_id))
                job = store.load(job_id)
                directory = store.root / job.job_id
                events = _jsonl_tail(directory / "progress.jsonl", 100)
                failures = _jsonl_tail(directory / "failures.jsonl", 100)
                self._json(HTTPStatus.OK, {"job": job.to_dict(), "events": events, "failures": failures})
            except (OSError, RescueError, ValueError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if path == "/api/inventory":
            try:
                query = parse_qs(parsed.query)
                store = JobStore(case_directory(query.get("case", [""])[0]))
                job = store.load(query.get("job", [""])[0])
                if job.kind != "btrfs-list" or job.status not in {"completed", "completed_with_errors"}:
                    raise ValueError("inventory is available only for a completed btrfs-list job")
                inventory = store.root / job.job_id / "btrfs-files.tsv"
                self._json(HTTPStatus.OK, {"items": _read_inventory(inventory)})
            except (OSError, RescueError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/api/protect", "/api/cases", "/api/destination", "/api/jobs", "/api/jobs/start", "/api/jobs/control"}:
            self._json(HTTPStatus.NOT_FOUND, {"error": "unknown API endpoint"})
            return
        if self.headers.get("Origin") not in {None, f"http://{self.headers.get('Host')}"}:
            self._json(HTTPStatus.FORBIDDEN, {"error": "cross-origin requests are forbidden"})
            return
        if not secrets.compare_digest(self.headers.get("X-FNOS-Token", ""), self.server.csrf_token):
            self._json(HTTPStatus.FORBIDDEN, {"error": "missing or invalid session token"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("invalid request size")
            body = json.loads(self.rfile.read(length))
            if path == "/api/protect":
                device, serial = self._device_confirmation(body)
                protected = protect_source(device, confirmed_serial=serial)
                self._json(HTTPStatus.OK, {"device": device, "protected": protected})
            elif path == "/api/cases":
                device, serial = self._device_confirmation(body)
                facts = inspect_device(device)
                confirm_serial(facts, serial)
                if not facts.read_only:
                    raise ValueError("source device must be read-only before creating a case")
                case = RecoveryCase.create(facts, filesystem=body.get("filesystem"))
                root = default_case_root()
                root.mkdir(parents=True, exist_ok=True, mode=0o700)
                case.save(root / case.case_id)
                self._json(HTTPStatus.CREATED, case.to_dict())
            elif path == "/api/destination":
                destination = str(body.get("path") or "")
                source_device = str(body.get("source_device") or "")
                if not destination or not source_device.startswith("/dev/"):
                    raise ValueError("destination and source device are required")
                facts = inspect_destination(destination)
                assert_destination_not_source(source_device, facts.existing_ancestor)
                assert_destination_ready(facts, int(body.get("required_bytes") or 0))
                self._json(HTTPStatus.OK, facts.to_dict())
            elif path == "/api/jobs":
                case_id = str(body.get("case_id") or "")
                kind = str(body.get("kind") or "")
                if kind not in WEB_JOB_PARAMETERS:
                    raise ValueError("job kind is not exposed by the web console")
                parameters = body.get("parameters")
                if not isinstance(parameters, dict):
                    raise ValueError("job parameters must be an object")
                unexpected = set(parameters) - WEB_JOB_PARAMETERS[kind]
                if unexpected:
                    raise ValueError(f"job parameters are not allowed: {', '.join(sorted(unexpected))}")
                job = JobStore(case_directory(case_id)).create(kind, parameters)
                self._json(HTTPStatus.CREATED, job.to_dict())
            elif path == "/api/jobs/start":
                store, job = self._job_from_body(body)
                pid = start_background(store, job)
                self._json(HTTPStatus.ACCEPTED, {"job_id": job.job_id, "pid": pid})
            else:
                store, job = self._job_from_body(body)
                action = str(body.get("action") or "")
                store.request_control(job, action)
                self._json(HTTPStatus.OK, store.load(job.job_id).to_dict())
        except (OSError, RescueError, ValueError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    @staticmethod
    def _device_confirmation(body: dict[str, Any]) -> tuple[str, str]:
        device, serial = body.get("device"), body.get("serial")
        if not isinstance(device, str) or not device.startswith("/dev/"):
            raise ValueError("a /dev device path is required")
        if not isinstance(serial, str) or not serial.strip():
            raise ValueError("serial confirmation is required")
        return device, serial

    @staticmethod
    def _job_from_body(body: dict[str, Any]):
        store = JobStore(case_directory(str(body.get("case_id") or "")))
        return store, store.load(str(body.get("job_id") or ""))

    def log_message(self, format: str, *args: Any) -> None:
        print(f"web: {format % args}")


def _jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    lines = path.read_text(errors="replace").splitlines()[-limit:]
    return [json.loads(line) for line in lines if line.strip()]


def _read_inventory(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError("inventory artifact is missing")
    text = path.read_text(errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    if not reader.fieldnames or "path" not in reader.fieldnames:
        raise ValueError("inventory has no path column")
    items = []
    for row in reader:
        value = str(row.get("path") or "").strip()
        if not value or value.startswith("/") or ".." in Path(value).parts:
            continue
        item = {key: str(value or "") for key, value in row.items() if key}
        item["inode"] = item.get("inode") or item.get("objectid", "")
        item["expected_size"] = item.get("expected_size") or item.get("size", "")
        items.append(item)
        if len(items) >= 50_000:
            break
    return items


def serve(host: str, port: int, static_dir: str | Path | None = None) -> None:
    bundled = Path(__file__).with_name("web_dist")
    development = Path(__file__).resolve().parents[2] / "web" / "dist"
    root = Path(static_dir) if static_dir else (bundled if bundled.is_dir() else development)
    if not (root / "index.html").is_file():
        raise RescueError(f"web assets not found: {root}; run npm run build in web/")
    handler = lambda *args, **kwargs: RescueWebHandler(*args, directory=str(root), **kwargs)
    server = ThreadingHTTPServer((host, port), handler)
    server.csrf_token = secrets.token_urlsafe(32)
    print(f"FNOS Rescue web console: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
