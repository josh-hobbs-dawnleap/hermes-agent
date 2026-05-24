import pytest

from gateway.ambient import (
    AmbientDecision,
    AmbientDecisionValidationError,
    parse_ambient_decision,
)


def test_parse_valid_decision_clamps_confidence_and_builds_models():
    decision = parse_ambient_decision(
        '{"respond": true, "respond_reason": "asked Hermes", "response_style": "brief", "memory_candidate": false, "confidence": 1.5}'
    )

    assert isinstance(decision, AmbientDecision)
    assert decision.respond is True
    assert decision.respond_reason == "asked Hermes"
    assert decision.response_style == "brief"
    assert decision.confidence == 1.0
    assert decision.memory is None
    assert decision.social_errand is None


def test_rejects_non_json_classifier_output():
    with pytest.raises(AmbientDecisionValidationError, match="valid JSON"):
        parse_ambient_decision("respond maybe")


def test_rejects_memory_candidate_below_threshold():
    payload = {
        "respond": False,
        "memory_candidate": True,
        "memory": {
            "person": "Alice",
            "fact": "likes jasmine tea",
            "confidence": 0.49,
            "sensitivity": "low",
        },
        "confidence": 0.8,
    }

    with pytest.raises(AmbientDecisionValidationError, match="memory candidate"):
        parse_ambient_decision(payload, memory_threshold=0.5)


def test_social_errand_requires_known_sender_identity():
    payload = {
        "respond": False,
        "memory_candidate": False,
        "social_errand": {
            "action": "immediate_relay",
            "recipient_person": "Bob",
            "target_chat_hint": "family chat",
            "message": "Please bring the charger",
            "trigger_phrase": None,
            "expires_hours": 2,
        },
        "confidence": 0.7,
    }

    with pytest.raises(AmbientDecisionValidationError, match="sender identity"):
        parse_ambient_decision(payload, sender_person=None)


def test_sensitive_social_errand_requires_explicit_confirmation():
    payload = {
        "respond": False,
        "memory_candidate": False,
        "social_errand": {
            "action": "deliver_sensitive",
            "recipient_person": "Doctor",
            "target_chat_hint": None,
            "message": "My lab result is positive",
            "trigger_phrase": None,
            "expires_hours": 1,
        },
        "confidence": 0.9,
    }

    with pytest.raises(AmbientDecisionValidationError, match="sensitive"):
        parse_ambient_decision(payload, sender_person="Alice")

    decision = parse_ambient_decision(
        payload, sender_person="Alice", sensitive_delivery_confirmed=True
    )
    assert decision.social_errand.action == "deliver_sensitive"


def test_rejects_non_finite_confidence_values():
    with pytest.raises(AmbientDecisionValidationError, match="valid JSON"):
        parse_ambient_decision('{"respond": false, "confidence": NaN}')

    with pytest.raises(AmbientDecisionValidationError, match="finite"):
        parse_ambient_decision({"respond": False, "confidence": float("nan")})


def test_rejects_string_booleans_in_classifier_output():
    with pytest.raises(AmbientDecisionValidationError, match="respond must be a boolean"):
        parse_ambient_decision({"respond": "false"})

    with pytest.raises(AmbientDecisionValidationError, match="memory_candidate must be a boolean"):
        parse_ambient_decision({"respond": False, "memory_candidate": "false"})
