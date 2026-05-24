from datetime import UTC, datetime

import pytest

from gateway.identity_map import (
    IdentityConfidence,
    IdentityMapStore,
    IdentityMapStoreError,
    UntrustedIdentityError,
)


def test_trusted_interactive_chat_can_create_and_get_mapping(tmp_path):
    store = IdentityMapStore(path=tmp_path / "identity_map.json")

    mapping = store.add_mapping(
        canonical_person="Alice Example",
        platform="telegram",
        platform_user_id="123",
        visible_name="Alice E.",
        username="alice",
        confidence=IdentityConfidence.EXPLICIT,
        approved_by="owner",
        trusted_interactive=True,
    )

    assert mapping.canonical_person == "Alice Example"
    assert mapping.platform == "telegram"
    assert mapping.platform_user_id == "123"
    assert mapping.created_at <= datetime.now(UTC)
    assert store.get_mapping("telegram", "123") == mapping


def test_untrusted_content_cannot_establish_identity(tmp_path):
    store = IdentityMapStore(path=tmp_path / "identity_map.json")

    with pytest.raises(UntrustedIdentityError):
        store.add_mapping(
            canonical_person="Mallory",
            platform="telegram",
            platform_user_id="999",
            visible_name="Mallory says she is Alice",
            confidence="inferred",
            approved_by="message-content",
            trusted_interactive=False,
        )

    assert store.list_mappings() == []


def test_mapping_persists_and_can_be_listed_by_person(tmp_path):
    path = tmp_path / "identity_map.json"
    first = IdentityMapStore(path=path)
    first.add_mapping(
        canonical_person="Bob",
        platform="slack",
        platform_user_id="U42",
        visible_name="Bobby",
        username=None,
        confidence="tentative",
        approved_by="Alice",
        trusted_interactive=True,
    )

    second = IdentityMapStore(path=path)
    assert len(second.list_mappings()) == 1
    assert second.list_mappings(canonical_person="Bob")[0].platform_user_id == "U42"
    assert second.get_mapping("slack", "missing") is None


def test_confirm_mapping_upgrades_confidence_and_audit_fields(tmp_path):
    store = IdentityMapStore(path=tmp_path / "identity_map.json")
    store.add_mapping(
        canonical_person="Cara",
        platform="discord",
        platform_user_id="D1",
        visible_name="cara",
        confidence="tentative",
        approved_by="owner",
        trusted_interactive=True,
    )

    confirmed = store.confirm_mapping(
        platform="discord",
        platform_user_id="D1",
        approved_by="Cara",
        trusted_interactive=True,
    )

    assert confirmed.confidence == IdentityConfidence.EXPLICIT
    assert confirmed.updated_by == "Cara"
    assert confirmed.updated_at >= confirmed.created_at


def test_corrupt_identity_store_is_not_silently_treated_as_empty(tmp_path):
    path = tmp_path / "identity_map.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = IdentityMapStore(path=path)

    with pytest.raises(IdentityMapStoreError):
        store.list_mappings()
