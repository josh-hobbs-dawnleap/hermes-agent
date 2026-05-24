"""Durable social errands store for ambient gateway workflows.

The module stores relay and pending-cue errands without platform routing
integration.  Helpers make relay attribution explicit and default errands to
one-shot behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from gateway.ambient import SocialErrandCandidate
from gateway.identity_map import IdentityConfidence, IdentityMapStore
from hermes_constants import get_hermes_home
from utils import atomic_json_write


class SocialErrandStoreError(RuntimeError):
    """Raised when the social errands store cannot be safely read."""


class ErrandStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ErrandType(StrEnum):
    IMMEDIATE_RELAY = "immediate_relay"
    PENDING_CUE = "pending_cue"


@dataclass(frozen=True)
class ResolvedSocialErrandDelivery:
    ok: bool
    target_user_id: str | None = None
    target_person: str | None = None
    attributed_message: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class AuditEvent:
    at: datetime
    actor: str
    action: str
    note: str | None = None


@dataclass(frozen=True)
class SocialErrand:
    errand_id: str
    errand_type: ErrandType
    created_by_person: str
    created_by_platform: str
    source: str
    message: str
    expires_at: datetime
    target_person: str | None = None
    target_chat: str | None = None
    trigger_phrase: str | None = None
    trigger_chat: str | None = None
    max_uses: int = 1
    uses: int = 0
    status: ErrandStatus = ErrandStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    audit: list[AuditEvent] = field(default_factory=list)

    def attributed_message(self) -> str:
        """Return a relay-safe message that attributes rather than impersonates."""
        return f'{self.created_by_person} asked me to relay: "{self.message}"'

    @property
    def is_deliverable(self) -> bool:
        return self.status == ErrandStatus.PENDING and self.uses < self.max_uses


def resolve_social_errand_delivery(
    candidate: SocialErrandCandidate,
    *,
    created_by_person: str | None,
    platform: str,
    identity_store: IdentityMapStore,
) -> ResolvedSocialErrandDelivery:
    """Resolve a candidate target person into a platform user and message.

    This is a pure resolver; it does not send messages. Unknown targets return
    an error so an adapter/tool can ask the operator to establish a mapping.
    """

    sender = (created_by_person or "").strip()
    if not sender:
        return ResolvedSocialErrandDelivery(ok=False, error="social errand requires known sender identity")
    target_person = (candidate.recipient_person or "").strip()
    message = (candidate.message or "").strip()
    if not target_person:
        return ResolvedSocialErrandDelivery(ok=False, error="social errand requires target person")
    if not message:
        return ResolvedSocialErrandDelivery(ok=False, error="social errand requires message")

    mapping = next(
        (
            item
            for item in identity_store.list_mappings(target_person)
            if item.platform == platform
            and item.confidence in {IdentityConfidence.EXPLICIT, IdentityConfidence.INFERRED}
        ),
        None,
    )
    if mapping is None:
        return ResolvedSocialErrandDelivery(
            ok=False,
            target_person=target_person,
            error=f"no mapping for {target_person} on {platform}",
        )

    return ResolvedSocialErrandDelivery(
        ok=True,
        target_user_id=mapping.platform_user_id,
        target_person=target_person,
        attributed_message=f'{sender} asked me to relay: "{message}"',
    )


class SocialErrandStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else get_hermes_home() / "social_errands.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def create_immediate_relay(
        self,
        *,
        created_by_person: str,
        created_by_platform: str,
        source: str,
        message: str,
        target_person: str | None = None,
        target_chat: str | None = None,
        expires_in_hours: float = 24,
        expires_at: datetime | None = None,
        max_uses: int = 1,
    ) -> SocialErrand:
        return self._create(
            errand_type=ErrandType.IMMEDIATE_RELAY,
            created_by_person=created_by_person,
            created_by_platform=created_by_platform,
            source=source,
            message=message,
            target_person=target_person,
            target_chat=target_chat,
            expires_in_hours=expires_in_hours,
            expires_at=expires_at,
            max_uses=max_uses,
        )

    def create_pending_cue(
        self,
        *,
        created_by_person: str,
        created_by_platform: str,
        source: str,
        message: str,
        target_person: str | None = None,
        target_chat: str | None = None,
        trigger_phrase: str | None = None,
        trigger_chat: str | None = None,
        expires_in_hours: float = 24,
        expires_at: datetime | None = None,
        max_uses: int = 1,
    ) -> SocialErrand:
        return self._create(
            errand_type=ErrandType.PENDING_CUE,
            created_by_person=created_by_person,
            created_by_platform=created_by_platform,
            source=source,
            message=message,
            target_person=target_person,
            target_chat=target_chat,
            trigger_phrase=trigger_phrase,
            trigger_chat=trigger_chat,
            expires_in_hours=expires_in_hours,
            expires_at=expires_at,
            max_uses=max_uses,
        )

    def _create(
        self,
        *,
        errand_type: ErrandType,
        created_by_person: str,
        created_by_platform: str,
        source: str,
        message: str,
        target_person: str | None = None,
        target_chat: str | None = None,
        trigger_phrase: str | None = None,
        trigger_chat: str | None = None,
        expires_in_hours: float = 24,
        expires_at: datetime | None = None,
        max_uses: int = 1,
    ) -> SocialErrand:
        if not target_person and not target_chat:
            raise ValueError("social errand requires target_person or target_chat")
        now = datetime.now(UTC)
        expiry = expires_at or now + timedelta(hours=expires_in_hours)
        errand = SocialErrand(
            errand_id=uuid4().hex,
            errand_type=errand_type,
            created_by_person=created_by_person,
            created_by_platform=created_by_platform,
            source=source,
            message=message,
            target_person=target_person,
            target_chat=target_chat,
            trigger_phrase=trigger_phrase,
            trigger_chat=trigger_chat,
            expires_at=expiry,
            max_uses=max_uses,
            created_at=now,
            audit=[AuditEvent(at=now, actor=created_by_person, action="created", note=errand_type.value)],
        )
        errands = self.list_errands()
        errands.append(errand)
        self._save(errands)
        return errand

    def get_errand(self, errand_id: str) -> SocialErrand | None:
        for errand in self.list_errands():
            if errand.errand_id == errand_id:
                return errand
        return None

    def get_deliverable(self, errand_id: str, *, now: datetime | None = None) -> SocialErrand | None:
        self.expire_due(now=now)
        errand = self.get_errand(errand_id)
        if errand is None or not errand.is_deliverable:
            return None
        return errand

    def deliver_immediate_relay(
        self,
        errand_id: str,
        *,
        platform: str,
        identity_store: IdentityMapStore,
        deliver: Callable[[str, str], Any],
    ) -> SocialErrand:
        errand = self.get_deliverable(errand_id)
        if errand is None:
            raise ValueError(f"errand is not deliverable: {errand_id}")
        if errand.errand_type != ErrandType.IMMEDIATE_RELAY:
            raise ValueError(f"errand is not an immediate relay: {errand_id}")
        resolved = resolve_social_errand_delivery(
            SocialErrandCandidate(
                action=ErrandType.IMMEDIATE_RELAY.value,
                recipient_person=errand.target_person,
                message=errand.message,
            ),
            created_by_person=errand.created_by_person,
            platform=platform,
            identity_store=identity_store,
        )
        if not resolved.ok or not resolved.target_user_id or not resolved.attributed_message:
            raise ValueError(resolved.error or f"errand target is not deliverable: {errand_id}")
        result = deliver(f"{platform}:{resolved.target_user_id}", resolved.attributed_message)
        note = str(result) if result is not None else "delivered"
        return self.mark_used(errand_id, actor="gateway", note=note)

    def list_errands(self, status: ErrandStatus | str | None = None) -> list[SocialErrand]:
        errands = self._load()
        if status is not None:
            wanted = ErrandStatus(status)
            errands = [errand for errand in errands if errand.status == wanted]
        return errands

    def mark_used(self, errand_id: str, *, actor: str, note: str | None = None) -> SocialErrand:
        errand = self.get_deliverable(errand_id)
        if errand is None:
            raise ValueError(f"errand is not deliverable: {errand_id}")
        uses = errand.uses + 1
        status = ErrandStatus.COMPLETED if uses >= errand.max_uses else errand.status
        action = "completed" if status == ErrandStatus.COMPLETED else "used"
        return self._replace_errand(
            errand,
            uses=uses,
            status=status,
            audit=errand.audit + [AuditEvent(at=datetime.now(UTC), actor=actor, action=action, note=note)],
        )

    def cancel_errand(self, errand_id: str, *, actor: str, note: str | None = None) -> SocialErrand:
        errand = self.get_errand(errand_id)
        if errand is None:
            raise KeyError(errand_id)
        return self._replace_errand(
            errand,
            status=ErrandStatus.CANCELLED,
            audit=errand.audit + [AuditEvent(at=datetime.now(UTC), actor=actor, action="cancelled", note=note)],
        )

    def expire_due(self, *, now: datetime | None = None) -> list[SocialErrand]:
        current = now or datetime.now(UTC)
        expired: list[SocialErrand] = []
        errands = self.list_errands()
        new_errands: list[SocialErrand] = []
        for errand in errands:
            if errand.status == ErrandStatus.PENDING and errand.expires_at <= current:
                updated = self._copy_errand(
                    errand,
                    status=ErrandStatus.EXPIRED,
                    audit=errand.audit + [AuditEvent(at=current, actor="system", action="expired")],
                )
                expired.append(updated)
                new_errands.append(updated)
            else:
                new_errands.append(errand)
        if expired:
            self._save(new_errands)
        return expired

    def _replace_errand(self, errand: SocialErrand, **changes: Any) -> SocialErrand:
        updated = self._copy_errand(errand, **changes)
        errands = [updated if item.errand_id == errand.errand_id else item for item in self.list_errands()]
        self._save(errands)
        return updated

    @staticmethod
    def _copy_errand(errand: SocialErrand, **changes: Any) -> SocialErrand:
        data = asdict(errand)
        data.update(changes)
        data["errand_type"] = ErrandType(data["errand_type"])
        data["status"] = ErrandStatus(data["status"])
        return SocialErrand(**data)

    def _load(self) -> list[SocialErrand]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise SocialErrandStoreError(f"failed to read social errands store: {self.path}") from exc
        if not isinstance(raw, list):
            raise SocialErrandStoreError(f"social errands store must contain a JSON list: {self.path}")
        return [self._errand_from_dict(item) for item in raw if isinstance(item, dict)]

    def _save(self, errands: list[SocialErrand]) -> None:
        atomic_json_write(
            self.path,
            [self._errand_to_dict(errand) for errand in errands],
            indent=2,
            sort_keys=True,
        )

    @staticmethod
    def _errand_to_dict(errand: SocialErrand) -> dict[str, Any]:
        data = asdict(errand)
        data["errand_type"] = errand.errand_type.value
        data["status"] = errand.status.value
        data["created_at"] = errand.created_at.isoformat()
        data["expires_at"] = errand.expires_at.isoformat()
        data["audit"] = [
            {"at": event.at.isoformat(), "actor": event.actor, "action": event.action, "note": event.note}
            for event in errand.audit
        ]
        return data

    @staticmethod
    def _errand_from_dict(data: dict[str, Any]) -> SocialErrand:
        audit = [
            AuditEvent(
                at=datetime.fromisoformat(str(item["at"])),
                actor=str(item["actor"]),
                action=str(item["action"]),
                note=item.get("note"),
            )
            for item in data.get("audit", [])
            if isinstance(item, dict)
        ]
        return SocialErrand(
            errand_id=str(data["errand_id"]),
            errand_type=ErrandType(data["errand_type"]),
            created_by_person=str(data["created_by_person"]),
            created_by_platform=str(data["created_by_platform"]),
            source=str(data["source"]),
            message=str(data["message"]),
            expires_at=datetime.fromisoformat(str(data["expires_at"])),
            target_person=data.get("target_person"),
            target_chat=data.get("target_chat"),
            trigger_phrase=data.get("trigger_phrase"),
            trigger_chat=data.get("trigger_chat"),
            max_uses=int(data.get("max_uses", 1)),
            uses=int(data.get("uses", 0)),
            status=ErrandStatus(data.get("status", "pending")),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            audit=audit,
        )
