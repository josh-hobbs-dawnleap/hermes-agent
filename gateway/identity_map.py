"""Durable identity mapping store for gateway users.

The store is deliberately standalone: it provides persistence and trust checks
without integrating with any platform adapter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from utils import atomic_json_write


class UntrustedIdentityError(PermissionError):
    """Raised when untrusted content attempts to create or confirm identity."""


class IdentityMapStoreError(RuntimeError):
    """Raised when the identity map store cannot be safely read."""


class IdentityConfidence(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    TENTATIVE = "tentative"


@dataclass(frozen=True)
class IdentityMapping:
    canonical_person: str
    platform: str
    platform_user_id: str
    visible_name: str | None
    username: str | None
    confidence: IdentityConfidence
    approved_by: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class IdentityMapStore:
    """JSON-backed identity mapping store.

    Trusted interactive contexts may establish or confirm mappings. Untrusted
    content is rejected because message text alone cannot safely prove identity.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else get_hermes_home() / "identity_map.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add_mapping(
        self,
        *,
        canonical_person: str,
        platform: str,
        platform_user_id: str,
        visible_name: str | None = None,
        username: str | None = None,
        confidence: IdentityConfidence | str = IdentityConfidence.TENTATIVE,
        approved_by: str,
        trusted_interactive: bool,
    ) -> IdentityMapping:
        if not trusted_interactive:
            raise UntrustedIdentityError("untrusted content cannot establish identity")
        now = datetime.now(UTC)
        mapping = IdentityMapping(
            canonical_person=canonical_person,
            platform=platform,
            platform_user_id=platform_user_id,
            visible_name=visible_name,
            username=username,
            confidence=IdentityConfidence(confidence),
            approved_by=approved_by,
            created_at=now,
            updated_at=now,
            created_by=approved_by,
            updated_by=approved_by,
        )
        mappings = [
            item
            for item in self.list_mappings()
            if not (item.platform == platform and item.platform_user_id == platform_user_id)
        ]
        mappings.append(mapping)
        self._save(mappings)
        return mapping

    def confirm_mapping(
        self,
        *,
        platform: str,
        platform_user_id: str,
        approved_by: str,
        trusted_interactive: bool,
    ) -> IdentityMapping:
        if not trusted_interactive:
            raise UntrustedIdentityError("untrusted content cannot confirm identity")
        mappings = self.list_mappings()
        for index, item in enumerate(mappings):
            if item.platform == platform and item.platform_user_id == platform_user_id:
                updated = IdentityMapping(
                    canonical_person=item.canonical_person,
                    platform=item.platform,
                    platform_user_id=item.platform_user_id,
                    visible_name=item.visible_name,
                    username=item.username,
                    confidence=IdentityConfidence.EXPLICIT,
                    approved_by=item.approved_by,
                    created_at=item.created_at,
                    updated_at=datetime.now(UTC),
                    created_by=item.created_by,
                    updated_by=approved_by,
                )
                mappings[index] = updated
                self._save(mappings)
                return updated
        raise KeyError(f"no identity mapping for {platform}:{platform_user_id}")

    def get_mapping(self, platform: str, platform_user_id: str) -> IdentityMapping | None:
        for item in self.list_mappings():
            if item.platform == platform and item.platform_user_id == platform_user_id:
                return item
        return None

    def list_mappings(self, canonical_person: str | None = None) -> list[IdentityMapping]:
        mappings = self._load()
        if canonical_person is not None:
            mappings = [item for item in mappings if item.canonical_person == canonical_person]
        return mappings

    def _load(self) -> list[IdentityMapping]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise IdentityMapStoreError(f"failed to read identity map store: {self.path}") from exc
        if not isinstance(raw, list):
            raise IdentityMapStoreError(f"identity map store must contain a JSON list: {self.path}")
        mappings: list[IdentityMapping] = []
        for item in raw:
            if isinstance(item, dict):
                mappings.append(self._mapping_from_dict(item))
        return mappings

    def _save(self, mappings: list[IdentityMapping]) -> None:
        atomic_json_write(
            self.path,
            [self._mapping_to_dict(item) for item in mappings],
            indent=2,
            sort_keys=True,
        )

    @staticmethod
    def _mapping_to_dict(mapping: IdentityMapping) -> dict[str, Any]:
        data = asdict(mapping)
        data["confidence"] = mapping.confidence.value
        data["created_at"] = mapping.created_at.isoformat()
        data["updated_at"] = mapping.updated_at.isoformat()
        return data

    @staticmethod
    def _mapping_from_dict(data: dict[str, Any]) -> IdentityMapping:
        return IdentityMapping(
            canonical_person=str(data["canonical_person"]),
            platform=str(data["platform"]),
            platform_user_id=str(data["platform_user_id"]),
            visible_name=data.get("visible_name"),
            username=data.get("username"),
            confidence=IdentityConfidence(data.get("confidence", "tentative")),
            approved_by=str(data.get("approved_by") or data.get("created_by") or "unknown"),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            updated_at=datetime.fromisoformat(str(data["updated_at"])),
            created_by=data.get("created_by"),
            updated_by=data.get("updated_by"),
        )
