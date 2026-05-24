"""CLI helpers for inspecting and editing gateway identity mappings."""

from __future__ import annotations

from argparse import Namespace
from argparse import _SubParsersAction

from gateway.identity_map import IdentityMapStore


def register_identity_subparser(subparsers: _SubParsersAction):
    parser = subparsers.add_parser(
        "identity",
        help="Inspect and edit gateway identity mappings",
        description="Manage person-to-platform identity mappings used by ambient social errands.",
    )
    identity_subparsers = parser.add_subparsers(dest="identity_command")
    list_parser = identity_subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="List identity mappings",
    )
    list_parser.add_argument("--person", default=None, help="Filter by canonical person name")
    add_parser = identity_subparsers.add_parser(
        "add",
        help="Add or replace a trusted interactive identity mapping",
    )
    add_parser.add_argument("platform", help="Platform name, e.g. telegram")
    add_parser.add_argument("user_id", help="Platform user ID")
    add_parser.add_argument("person", help="Canonical person name, e.g. Julia Hobbs")
    add_parser.add_argument("--visible-name", default=None, help="Visible display name")
    add_parser.add_argument("--username", default=None, help="Platform username")
    add_parser.add_argument(
        "--confidence",
        choices=["explicit", "inferred", "tentative"],
        default="explicit",
        help="Identity confidence level",
    )
    add_parser.add_argument("--approved-by", default="operator", help="Who approved this mapping")
    parser.set_defaults(func=cmd_identity)
    return parser


def _print_mapping(mapping) -> None:
    name = mapping.visible_name or ""
    username = f" @{mapping.username}" if mapping.username else ""
    print(
        f"{mapping.canonical_person}\t{mapping.platform}:{mapping.platform_user_id}\t"
        f"{mapping.confidence.value}\t{name}{username}".rstrip()
    )


def cmd_identity(args: Namespace) -> int:
    command = getattr(args, "identity_command", None) or "list"
    store = IdentityMapStore()
    if command in {"list", "ls"}:
        mappings = store.list_mappings(getattr(args, "person", None))
        if not mappings:
            print("No identity mappings configured.")
            return 0
        for mapping in mappings:
            _print_mapping(mapping)
        return 0
    if command == "add":
        mapping = store.add_mapping(
            canonical_person=args.person,
            platform=args.platform,
            platform_user_id=args.user_id,
            visible_name=getattr(args, "visible_name", None),
            username=getattr(args, "username", None),
            confidence=getattr(args, "confidence", "explicit"),
            approved_by=getattr(args, "approved_by", None) or "operator",
            trusted_interactive=True,
        )
        print("Added identity mapping:")
        _print_mapping(mapping)
        return 0
    print("Usage: hermes identity [list|add]")
    return 2
