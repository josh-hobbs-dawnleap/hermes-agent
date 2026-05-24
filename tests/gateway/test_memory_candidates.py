from gateway.ambient import MemoryCandidate
from gateway.identity_map import IdentityMapStore
from gateway.memory_candidates import build_named_person_memory_entry


def test_builds_memory_tool_ready_entry_for_low_sensitivity_known_person(tmp_path):
    identities = IdentityMapStore(tmp_path / "identity.json")
    identities.add_mapping(
        canonical_person="Alice",
        platform="telegram",
        platform_user_id="1",
        visible_name="Alice A",
        approved_by="owner",
        trusted_interactive=True,
        confidence="explicit",
    )

    result = build_named_person_memory_entry(
        MemoryCandidate(person="Alice", fact="likes jasmine tea", confidence=0.9, sensitivity="low"),
        platform="telegram",
        identity_store=identities,
        trusted_source=True,
    )

    assert result.ok is True
    assert result.entry == "Named person memory: Alice likes jasmine tea."


def test_rejects_memory_for_unknown_medium_sensitive_or_untrusted_source(tmp_path):
    identities = IdentityMapStore(tmp_path / "identity.json")
    identities.add_mapping(
        canonical_person="Alice",
        platform="telegram",
        platform_user_id="1",
        approved_by="owner",
        trusted_interactive=True,
        confidence="explicit",
    )

    unknown = build_named_person_memory_entry(
        MemoryCandidate(person="Mallory", fact="likes tea", confidence=0.9, sensitivity="low"),
        platform="telegram",
        identity_store=identities,
        trusted_source=True,
    )
    assert unknown.ok is False
    assert "unknown identity" in unknown.error

    sensitive = build_named_person_memory_entry(
        MemoryCandidate(person="Alice", fact="has a diagnosis", confidence=0.9, sensitivity="medium"),
        platform="telegram",
        identity_store=identities,
        trusted_source=True,
    )
    assert sensitive.ok is False
    assert "confirmation" in sensitive.error

    confirmed = build_named_person_memory_entry(
        MemoryCandidate(person="Alice", fact="has a diagnosis", confidence=0.9, sensitivity="medium"),
        platform="telegram",
        identity_store=identities,
        trusted_source=True,
        confirmation=True,
    )
    assert confirmed.ok is True

    untrusted = build_named_person_memory_entry(
        MemoryCandidate(person="Alice", fact="likes tea", confidence=0.9, sensitivity="low"),
        platform="telegram",
        identity_store=identities,
        trusted_source=False,
    )
    assert untrusted.ok is False
    assert "untrusted" in untrusted.error
