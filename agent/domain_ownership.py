"""Cross-agent domain ownership policy helpers.

This is a soft, review-time gate: it gives agents and scripts a durable way to
ask "am I crossing another profile's lane?" without hard-coding personality
rules into the runtime. Enforcement stays conservative and approval-based.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_POLICY = _REPO_ROOT / "docs" / "domain-ownership.yaml"


@dataclass(frozen=True)
class OwnershipViolation:
    path: str
    domain: str
    required_owner: str
    actor: str


@dataclass(frozen=True)
class OwnershipCheckResult:
    allowed: bool
    actor: str
    approvals: set[str] = field(default_factory=set)
    violations: list[OwnershipViolation] = field(default_factory=list)


def _norm_name(value: str | None) -> str:
    return str(value or "").strip().lower()


def _norm_path(path: str | Path) -> str:
    text = str(path).replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def load_policy(path: str | Path | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path is not None else _DEFAULT_POLICY
    data = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"domain ownership policy must be a mapping: {policy_path}")
    return data


def _path_matches(pattern: str, path: str) -> bool:
    pattern = _norm_path(pattern)
    if pattern.endswith("/**"):
        base = pattern[:-3].rstrip("/")
        return path == base or path.startswith(base + "/")
    return fnmatch(path, pattern)


def domain_for_path(path: str | Path, policy: dict[str, Any] | None = None) -> tuple[str, str] | None:
    data = policy or load_policy()
    owners = data.get("owners") or {}
    domains = data.get("domains") or {}
    rel = _norm_path(path)
    for domain, spec in domains.items():
        if not isinstance(spec, dict):
            continue
        owner = str(spec.get("owner") or owners.get(domain) or "").strip()
        for pattern in spec.get("paths") or []:
            if _path_matches(str(pattern), rel):
                return str(domain), owner
    return None


def approvals_from_text(text: str, policy: dict[str, Any] | None = None) -> set[str]:
    data = policy or load_policy()
    marker = str((data.get("rules") or {}).get("approval_marker") or "Owner-Approval: <OwnerName>")
    prefix = marker.split("<", 1)[0].strip()
    approvals: set[str] = set()
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix.lower()):
            approvals.add(stripped[len(prefix):].strip())
    return {a for a in approvals if a}


def check_paths(
    paths: Iterable[str | Path],
    *,
    actor: str,
    approvals: Iterable[str] | None = None,
    policy_path: str | Path | None = None,
) -> OwnershipCheckResult:
    data = load_policy(policy_path)
    actor_name = str(actor or "").strip()
    actor_norm = _norm_name(actor_name)
    approval_set = {str(a).strip() for a in (approvals or []) if str(a).strip()}
    approval_norm = {_norm_name(a) for a in approval_set}
    violations: list[OwnershipViolation] = []

    for raw_path in paths:
        rel = _norm_path(raw_path)
        match = domain_for_path(rel, data)
        if match is None:
            continue
        domain, required_owner = match
        required_norm = _norm_name(required_owner)
        if not required_owner or actor_norm == required_norm or required_norm in approval_norm:
            continue
        violations.append(OwnershipViolation(
            path=rel,
            domain=domain,
            required_owner=required_owner,
            actor=actor_name,
        ))

    return OwnershipCheckResult(
        allowed=not violations,
        actor=actor_name,
        approvals=approval_set,
        violations=violations,
    )


__all__ = [
    "OwnershipCheckResult",
    "OwnershipViolation",
    "approvals_from_text",
    "check_paths",
    "domain_for_path",
    "load_policy",
]
