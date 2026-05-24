"""CLI helpers for inspecting and cancelling gateway social errands."""

from __future__ import annotations

from argparse import Namespace
from argparse import _SubParsersAction

from gateway.social_errands import SocialErrandStore


def register_errands_subparser(subparsers: _SubParsersAction):
    parser = subparsers.add_parser(
        "errands",
        help="Inspect and cancel ambient social errands",
        description="Manage pending ambient social errands such as relays and cue-triggered replies.",
    )
    errands_subparsers = parser.add_subparsers(dest="errands_command")
    list_parser = errands_subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="List social errands",
    )
    list_parser.add_argument(
        "--status",
        choices=["pending", "completed", "expired", "cancelled"],
        default=None,
        help="Filter by errand status",
    )
    cancel_parser = errands_subparsers.add_parser("cancel", help="Cancel a social errand by ID")
    cancel_parser.add_argument("errand_id", help="Errand ID")
    cancel_parser.add_argument("--actor", default="operator", help="Who cancelled this errand")
    parser.set_defaults(func=cmd_errands)
    return parser


def _print_errand(errand) -> None:
    target = errand.target_person or errand.target_chat or "(no target)"
    trigger = f" trigger={errand.trigger_phrase!r}" if errand.trigger_phrase else ""
    print(
        f"{errand.errand_id}\t{errand.status.value}\t{errand.errand_type.value}\t"
        f"target={target}\texpires={errand.expires_at.isoformat()}\t{errand.message}{trigger}"
    )


def cmd_errands(args: Namespace) -> int:
    command = getattr(args, "errands_command", None) or "list"
    store = SocialErrandStore()
    if command in {"list", "ls"}:
        errands = store.list_errands(getattr(args, "status", None))
        if not errands:
            print("No social errands configured.")
            return 0
        for errand in errands:
            _print_errand(errand)
        return 0
    if command == "cancel":
        errand = store.cancel_errand(
            args.errand_id,
            actor=getattr(args, "actor", None) or "operator",
            note="cancelled from CLI",
        )
        print("Cancelled social errand:")
        _print_errand(errand)
        return 0
    print("Usage: hermes errands [list|cancel]")
    return 2
