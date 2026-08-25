#!/usr/bin/env python3
"""Review-time gate for Hermes cross-agent domain ownership.

Usage examples:
  HERMES_AGENT_DOMAIN_OWNER=Fitz scripts/check_domain_ownership.py --changed
  scripts/check_domain_ownership.py --actor Atlas gateway/run.py --approval Fitz
  git diff --name-only | scripts/check_domain_ownership.py --actor Sage --stdin
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.domain_ownership import approvals_from_text, check_paths  # noqa: E402


def _git_changed() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "git diff failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="paths to check")
    parser.add_argument("--actor", default=os.getenv("HERMES_AGENT_DOMAIN_OWNER", ""), help="agent/profile making the change")
    parser.add_argument("--approval", action="append", default=[], help="owner approval name, repeatable")
    parser.add_argument("--approval-text", default="", help="text containing Owner-Approval markers")
    parser.add_argument("--changed", action="store_true", help="check git diff --name-only HEAD")
    parser.add_argument("--stdin", action="store_true", help="read paths from stdin")
    parser.add_argument("--policy", default=str(ROOT / "docs" / "domain-ownership.yaml"))
    args = parser.parse_args(argv)

    actor = args.actor.strip()
    if not actor:
        print("domain ownership check requires --actor or HERMES_AGENT_DOMAIN_OWNER", file=sys.stderr)
        return 2

    paths = list(args.paths)
    if args.changed:
        paths.extend(_git_changed())
    if args.stdin:
        paths.extend(line.strip() for line in sys.stdin if line.strip())
    paths = sorted(dict.fromkeys(paths))
    if not paths:
        print("domain ownership check: no paths to check")
        return 0

    approvals = set(args.approval or []) | approvals_from_text(args.approval_text)
    result = check_paths(paths, actor=actor, approvals=approvals, policy_path=args.policy)
    if result.allowed:
        print(f"domain ownership check: ok for {actor} ({len(paths)} path(s))")
        return 0

    print(f"domain ownership check: blocked for {actor}", file=sys.stderr)
    for violation in result.violations:
        print(
            f"  {violation.path}: {violation.domain} is owned by {violation.required_owner} "
            f"(add Owner-Approval: {violation.required_owner} after review)",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
