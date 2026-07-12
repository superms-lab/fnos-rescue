from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fnos_rescue import __version__

from .cases import RecoveryCase
from .devices import inspect_device
from .errors import RescueError
from .plugins.fnos_btrfs import FnosBtrfsPlugin
from .safety import assert_destination_not_source, protect_source
from .verify import verify_samples


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


def command_btrfs_probe(args: argparse.Namespace) -> int:
    _json(FnosBtrfsPlugin().probe(Path(args.device)))
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

    btrfs_probe = subparsers.add_parser("btrfs-probe", help="inspect all Btrfs super mirrors")
    btrfs_probe.add_argument("device")
    btrfs_probe.set_defaults(func=command_btrfs_probe)

    verify = subparsers.add_parser("verify", help="hash and identify representative files")
    verify.add_argument("path")
    verify.add_argument("--limit", type=int, default=10)
    verify.set_defaults(func=command_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (RescueError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
