from datetime import UTC, datetime, timedelta

import pytest

from gateway.identity_map import IdentityConfidence, IdentityMapStore
from gateway.social_errands import (
    ErrandStatus,
    SocialErrandCandidate,
    SocialErrandStore,
    SocialErrandStoreError,
    resolve_social_errand_delivery,
)


def test_create_immediate_relay_defaults_to_one_shot_and_attributes_message(tmp_path):
    store = SocialErrandStore(path=tmp_path / "social_errands.json")

    errand = store.create_immediate_relay(
        created_by_person="Alice",
        created_by_platform="telegram",
        source="chat-1",
        target_person="Bob",
        message="Bring the charger",
        expires_in_hours=2,
    )

    assert errand.max_uses == 1
    assert errand.status == ErrandStatus.PENDING
    assert errand.target_person == "Bob"
    assert "Alice asked me to relay" in errand.attributed_message()
    assert "Bring the charger" in errand.attributed_message()
    assert errand.expires_at > datetime.now(UTC)


def test_create_pending_cue_with_trigger_phrase_and_persistence(tmp_path):
    path = tmp_path / "social_errands.json"
    first = SocialErrandStore(path=path)
    created = first.create_pending_cue(
        created_by_person="Alice",
        created_by_platform="telegram",
        source="chat-1",
        target_chat="family",
        message="Tell Bob dinner is ready",
        trigger_phrase="when Bob appears",
        expires_in_hours=24,
    )

    second = SocialErrandStore(path=path)
    loaded = second.get_errand(created.errand_id)
    assert loaded == created
    assert loaded.trigger_phrase == "when Bob appears"
    assert second.list_errands(status=ErrandStatus.PENDING)[0].errand_id == created.errand_id


def test_complete_errand_is_audited_and_one_shot(tmp_path):
    store = SocialErrandStore(path=tmp_path / "social_errands.json")
    errand = store.create_immediate_relay(
        created_by_person="Alice",
        created_by_platform="telegram",
        source="chat-1",
        target_person="Bob",
        message="Ping me",
    )

    completed = store.mark_used(errand.errand_id, actor="gateway", note="delivered")

    assert completed.status == ErrandStatus.COMPLETED
    assert completed.uses == 1
    assert completed.audit[-1].action == "completed"
    assert store.get_deliverable(errand.errand_id) is None


def test_deliver_immediate_relay_records_success_with_delivery_callback(tmp_path):
    identity = IdentityMapStore(tmp_path / "identity.json")
    identity.add_mapping(
        canonical_person="Julia Hobbs",
        platform="telegram",
        platform_user_id="123",
        visible_name="Julia",
        confidence=IdentityConfidence.EXPLICIT,
        approved_by="Josh Hobbs",
        trusted_interactive=True,
    )
    store = SocialErrandStore(tmp_path / "errands.json")
    errand = store.create_immediate_relay(
        created_by_person="Josh Hobbs",
        created_by_platform="telegram",
        source="telegram:456",
        message="you are beautiful",
        target_person="Julia Hobbs",
    )
    deliveries = []

    def deliver(target, message):
        deliveries.append((target, message))
        return "ok-1"

    delivered = store.deliver_immediate_relay(
        errand.errand_id,
        platform="telegram",
        identity_store=identity,
        deliver=deliver,
    )

    assert deliveries == [("telegram:123", 'Josh Hobbs asked me to relay: "you are beautiful"')]
    assert delivered.status == ErrandStatus.COMPLETED
    assert delivered.uses == 1
    assert delivered.audit[-1].action == "completed"
    assert delivered.audit[-1].note == "ok-1"


def test_expire_tasks_marks_expired_and_filters_deliverable(tmp_path):
    store = SocialErrandStore(path=tmp_path / "social_errands.json")
    errand = store.create_immediate_relay(
        created_by_person="Alice",
        created_by_platform="telegram",
        source="chat-1",
        target_person="Bob",
        message="Old news",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    expired = store.expire_due(now=datetime.now(UTC))

    assert [item.errand_id for item in expired] == [errand.errand_id]
    assert store.get_errand(errand.errand_id).status == ErrandStatus.EXPIRED
    assert store.get_deliverable(errand.errand_id) is None


def test_cancel_errand_is_audited(tmp_path):
    store = SocialErrandStore(path=tmp_path / "social_errands.json")
    errand = store.create_pending_cue(
        created_by_person="Alice",
        created_by_platform="telegram",
        source="chat-1",
        target_chat="family",
        message="Never mind",
        trigger_chat="family",
    )

    cancelled = store.cancel_errand(errand.errand_id, actor="Alice", note="rescinded")

    assert cancelled.status == ErrandStatus.CANCELLED
    assert cancelled.audit[-1].actor == "Alice"
    assert cancelled.audit[-1].action == "cancelled"


def test_mark_used_rejects_cancelled_and_expired_errands(tmp_path):
    store = SocialErrandStore(path=tmp_path / "social_errands.json")
    cancelled = store.create_pending_cue(
        created_by_person="Alice",
        created_by_platform="telegram",
        source="chat-1",
        target_chat="family",
        message="Never mind",
    )
    store.cancel_errand(cancelled.errand_id, actor="Alice")

    with pytest.raises(ValueError, match="not deliverable"):
        store.mark_used(cancelled.errand_id, actor="gateway")

    expired = store.create_immediate_relay(
        created_by_person="Alice",
        created_by_platform="telegram",
        source="chat-1",
        target_person="Bob",
        message="Old news",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    with pytest.raises(ValueError, match="not deliverable"):
        store.mark_used(expired.errand_id, actor="gateway")


def test_corrupt_social_errand_store_is_not_silently_treated_as_empty(tmp_path):
    path = tmp_path / "social_errands.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = SocialErrandStore(path=path)

    with pytest.raises(SocialErrandStoreError):
        store.list_errands()


def test_resolve_social_errand_delivery_maps_person_to_platform_and_attributes(tmp_path):
    identities = IdentityMapStore(tmp_path / "identity.json")
    identities.add_mapping(
        canonical_person="Bob",
        platform="telegram",
        platform_user_id="42",
        visible_name="Bobby",
        approved_by="owner",
        trusted_interactive=True,
        confidence="explicit",
    )

    result = resolve_social_errand_delivery(
        SocialErrandCandidate(
            action="immediate_relay",
            recipient_person="Bob",
            message="Bring the charger",
            expires_hours=2,
        ),
        created_by_person="Alice",
        platform="telegram",
        identity_store=identities,
    )

    assert result.ok is True
    assert result.target_user_id == "42"
    assert result.attributed_message == 'Alice asked me to relay: "Bring the charger"'


def test_resolve_social_errand_delivery_rejects_unknown_or_untrusted_sender(tmp_path):
    identities = IdentityMapStore(tmp_path / "identity.json")

    unknown = resolve_social_errand_delivery(
        SocialErrandCandidate(action="immediate_relay", recipient_person="Bob", message="Ping me"),
        created_by_person="Alice",
        platform="telegram",
        identity_store=identities,
    )
    assert unknown.ok is False
    assert "mapping" in unknown.error

    untrusted = resolve_social_errand_delivery(
        SocialErrandCandidate(action="immediate_relay", recipient_person="Bob", message="Ping me"),
        created_by_person=None,
        platform="telegram",
        identity_store=identities,
    )
    assert untrusted.ok is False
    assert "known sender" in untrusted.error
