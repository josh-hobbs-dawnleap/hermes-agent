"""Conservative helpers for ambient memory candidates."""

from __future__ import annotations

from dataclasses import dataclass

from gateway.ambient import MemoryCandidate
from gateway.identity_map import IdentityConfidence, IdentityMapStore


@dataclass(frozen=True)
class MemoryEntryResult:
    ok: bool
    entry: str | None = None
    error: str | None = None


def build_named_person_memory_entry(
    candidate: MemoryCandidate,
    *,
    platform: str,
    identity_store: IdentityMapStore,
    trusted_source: bool,
    confirmation: bool = False,
) -> MemoryEntryResult:
    """Convert a safe known-person memory candidate into tool-ready text.

    The gateway does not call memory tools here. It only prepares text after
    conservative checks: trusted source, known explicit/inferred identity, and
    low sensitivity unless the user has explicitly confirmed.
    """

    if not trusted_source:
        return MemoryEntryResult(ok=False, error="untrusted source cannot create memory")

    person = (candidate.person or "").strip()
    fact = (candidate.fact or "").strip()
    if not person or not fact:
        return MemoryEntryResult(ok=False, error="memory candidate requires person and fact")

    mappings = identity_store.list_mappings(person)
    known = any(
        mapping.platform == platform
        and mapping.confidence in {IdentityConfidence.EXPLICIT, IdentityConfidence.INFERRED}
        for mapping in mappings
    )
    if not known:
        return MemoryEntryResult(ok=False, error="unknown identity cannot create memory")

    sensitivity = (candidate.sensitivity or "unknown").strip().lower()
    if sensitivity != "low" and not confirmation:
        return MemoryEntryResult(ok=False, error="memory candidate requires confirmation for sensitivity")

    return MemoryEntryResult(ok=True, entry=f"Named person memory: {person} {fact}.")
