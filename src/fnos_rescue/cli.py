from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fnos_rescue import __version__

from .cases import RecoveryCase
from .devices import inspect_device
from .destinations import assert_destination_ready, inspect_destination
from .doctor import diagnose
from .errors import RescueError
from .executors import execute_job, start_background
from .jobs import JobStore
from .plugins.fnos_btrfs import FnosBtrfsPlugin
from .plugins.ext4 import Ext4DiagnosticPlugin
from .plugins.ntfs import NtfsDiagnosticPlugin
from .safety import assert_destination_not_source, protect_source
from .verify import verify_samples
from .reports import case_report
from .fnos import detect_fnos, quiesce_plan
from .web import serve


def _json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def command_inspect(args: argparse.Namespace) -> int:
    _json(inspect_device(args.device).to_dict())
    return 0


def command_protect(args: argparse.Namespace) -> int:
    paths = protect_source(
        args.device,
        confirmed_serial=args.confirm_serial,
        dry_run=args.dry_run,
    )
    _json({"device": args.device, "protected": paths, "dry_run": args.dry_run})
    return 0


def command_case_init(args: argparse.Namespace) -> int:
    facts = inspect_device(args.device)
    case = RecoveryCase.create(facts, filesystem=args.filesystem)
    path = case.save(args.output)
    _json({"case_id": case.case_id, "path": str(path)})
    return 0


def command_case_show(args: argparse.Namespace) -> int:
    _json(RecoveryCase.load(args.case).to_dict())
    return 0


def command_case_report(args: argparse.Namespace) -> int:
    _json(case_report(args.case))
    return 0


def command_btrfs_probe(args: argparse.Namespace) -> int:
    _json(FnosBtrfsPlugin().probe(Path(args.device)))
    return 0


def command_fs_probe(args: argparse.Namespace) -> int:
    plugins = {
        "btrfs": FnosBtrfsPlugin,
        "ext4": Ext4DiagnosticPlugin,
        "ntfs": NtfsDiagnosticPlugin,
    }
    _json(plugins[args.filesystem]().probe(Path(args.device)))
    return 0


def command_plan(args: argparse.Namespace) -> int:
    facts = inspect_device(args.device)
    assert_destination_not_source(args.device, args.destination)
    _json(
        {
            "source": facts.to_dict(),
            "destination": str(Path(args.destination).resolve()),
            "steps": [
                "protect every source layer read-only",
                "capture device and superblock evidence",
                "create an image or QCOW2 overlay",
                "list directories from readable metadata",
                "validate representative files",
                "restore selected paths to the destination",
                "write failure manifests and detach safely",
            ],
        }
    )
    return 0


def command_verify(args: argparse.Namespace) -> int:
    _json({"path": args.path, "samples": verify_samples(args.path, args.limit)})
    return 0


def command_destination_inspect(args: argparse.Namespace) -> int:
    facts = inspect_destination(args.path)
    assert_destination_ready(facts, args.required_bytes)
    _json(facts.to_dict())
    return 0


def command_doctor(_args: argparse.Namespace) -> int:
    report = diagnose()
    _json(report.to_dict())
    return 0 if report.ok else 3


def command_fnos_detect(_args: argparse.Namespace) -> int:
    environment = detect_fnos()
    _json(environment.to_dict())
    return 0 if environment.detected else 3


def command_fnos_quiesce_plan(args: argparse.Namespace) -> int:
    _json(quiesce_plan(args.device))
    return 0


def command_job_create(args: argparse.Namespace) -> int:
    parameters = json.loads(args.parameters)
    if not isinstance(parameters, dict):
        raise ValueError("job parameters must be a JSON object")
    job = JobStore(args.case).create(args.kind, parameters)
    _json(job.to_dict())
    return 0


def command_job_list(args: argparse.Namespace) -> int:
    _json([job.to_dict() for job in JobStore(args.case).list()])
    return 0


def command_job_show(args: argparse.Namespace) -> int:
    _json(JobStore(args.case).load(args.job_id).to_dict())
    return 0


def command_job_run(args: argparse.Namespace) -> int:
    store = JobStore(args.case)
    job = store.load(args.job_id)
    if args.background:
        pid = start_background(store, job)
        _json({"job_id": job.job_id, "status": job.status, "pid": pid})
        return 0
    _json(execute_job(store, job.job_id).to_dict())
    return 0


def command_job_control(args: argparse.Namespace) -> int:
    store = JobStore(args.case)
    job = store.load(args.job_id)
    store.request_control(job, args.action)
    _json(store.load(job.job_id).to_dict())
    return 0


def command_serve(args: argparse.Namespace) -> int:
    serve(args.host, args.port, args.static_dir, args.token_file)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fnos-rescue",
        description="Read-only-first FNOS Basic-disk Btrfs recovery toolkit",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect = subparsers.add_parser("inspect", help="inspect a Linux block device")
    inspect.add_argument("device")
    inspect.set_defaults(func=command_inspect)

    protect = subparsers.add_parser("protect", help="set a source device tree read-only")
    protect.add_argument("device")
    protect.add_argument("--confirm-serial", required=True)
    protect.add_argument("--dry-run", action="store_true")
    protect.set_defaults(func=command_protect)

    plan = subparsers.add_parser("plan", help="check source/destination and print a safe plan")
    plan.add_argument("device")
    plan.add_argument("destination")
    plan.set_defaults(func=command_plan)

    case_init = subparsers.add_parser("case-init", help="create a durable recovery case")
    case_init.add_argument("device")
    case_init.add_argument("output")
    case_init.add_argument("--filesystem")
    case_init.set_defaults(func=command_case_init)

    case_show = subparsers.add_parser("case-show", help="show a recovery case as JSON")
    case_show.add_argument("case")
    case_show.set_defaults(func=command_case_show)

    case_report_parser = subparsers.add_parser("case-report", help="summarize job and failure state")
    case_report_parser.add_argument("case")
    case_report_parser.set_defaults(func=command_case_report)

    btrfs_probe = subparsers.add_parser("btrfs-probe", help="inspect all Btrfs super mirrors")
    btrfs_probe.add_argument("device")
    btrfs_probe.set_defaults(func=command_btrfs_probe)

    fs_probe = subparsers.add_parser("fs-probe", help="run a read-only filesystem diagnostic")
    fs_probe.add_argument("filesystem", choices=("btrfs", "ext4", "ntfs"))
    fs_probe.add_argument("device")
    fs_probe.set_defaults(func=command_fs_probe)

    verify = subparsers.add_parser("verify", help="hash and identify representative files")
    verify.add_argument("path")
    verify.add_argument("--limit", type=int, default=10)
    verify.set_defaults(func=command_verify)

    destination_inspect = subparsers.add_parser(
        "destination-inspect", help="inspect destination mount, capacity, and write readiness"
    )
    destination_inspect.add_argument("path")
    destination_inspect.add_argument("--required-bytes", type=int, default=0)
    destination_inspect.set_defaults(func=command_destination_inspect)

    doctor = subparsers.add_parser("doctor", help="check Linux platform and recovery dependencies")
    doctor.set_defaults(func=command_doctor)

    fnos_detect = subparsers.add_parser("fnos-detect", help="detect fnOS and native app paths")
    fnos_detect.set_defaults(func=command_fnos_detect)

    fnos_plan = subparsers.add_parser(
        "fnos-quiesce-plan", help="print a dry-run service and mount safety plan"
    )
    fnos_plan.add_argument("device")
    fnos_plan.set_defaults(func=command_fnos_quiesce_plan)

    job_create = subparsers.add_parser("job-create", help="create a durable queued job")
    job_create.add_argument("case")
    job_create.add_argument("kind")
    job_create.add_argument("--parameters", default="{}", help="JSON object")
    job_create.set_defaults(func=command_job_create)

    job_list = subparsers.add_parser("job-list", help="list jobs in a recovery case")
    job_list.add_argument("case")
    job_list.set_defaults(func=command_job_list)

    job_show = subparsers.add_parser("job-show", help="show one recovery job")
    job_show.add_argument("case")
    job_show.add_argument("job_id")
    job_show.set_defaults(func=command_job_show)

    job_run = subparsers.add_parser("job-run", help="run or resume a supported recovery job")
    job_run.add_argument("case")
    job_run.add_argument("job_id")
    job_run.add_argument("--background", action="store_true")
    job_run.set_defaults(func=command_job_run)

    job_control = subparsers.add_parser("job-control", help="pause, resume, or cancel a job")
    job_control.add_argument("case")
    job_control.add_argument("job_id")
    job_control.add_argument("action", choices=("pause", "resume", "cancel"))
    job_control.set_defaults(func=command_job_control)

    web = subparsers.add_parser("serve", help="serve the local recovery web console")
    web.add_argument("--host", default="127.0.0.1", help="listen address; loopback by default")
    web.add_argument("--port", type=int, default=8790)
    web.add_argument("--static-dir")
    web.add_argument("--token-file", help="private file containing the Web access token")
    web.set_defaults(func=command_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (RescueError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
