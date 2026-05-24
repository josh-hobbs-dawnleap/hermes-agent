from types import SimpleNamespace

from gateway.ambient import classify_ambient_message
from gateway.config import AmbientConfig


class _ChoiceMessage:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _ChoiceMessage(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


def test_classifier_calls_auxiliary_llm_with_no_tools_json_prompt(monkeypatch):
    calls = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        return _Response('{"respond": true, "confidence": 0.8}')

    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    decision = classify_ambient_message(
        message_text="can someone help me pick a laptop?",
        recent_context=["[Alice|1] I like ThinkPads"],
        sender_person="Alice",
        identity_summary="Alice is telegram user 1 (explicit).",
        config=AmbientConfig(enabled=True, provider="openai", model="gpt-test"),
    )

    assert decision.respond is True
    assert calls
    assert calls[0]["task"] == "ambient"
    assert calls[0]["provider"] == "openai"
    assert calls[0]["model"] == "gpt-test"
    assert calls[0]["tools"] == []
    assert "JSON object only" in calls[0]["messages"][0]["content"]
    assert "observed chat content" in calls[0]["messages"][1]["content"]


def test_classifier_defaults_to_silence_when_disabled_or_llm_fails(monkeypatch):
    called = False

    def fake_call_llm(**kwargs):
        nonlocal called
        called = True
        raise RuntimeError("network would have happened")

    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    disabled = classify_ambient_message(
        message_text="hello",
        recent_context=[],
        sender_person="Alice",
        identity_summary="Alice known",
        config=AmbientConfig(enabled=False),
    )
    assert disabled.respond is False
    assert called is False

    failed = classify_ambient_message(
        message_text="hello",
        recent_context=[],
        sender_person="Alice",
        identity_summary="Alice known",
        config=AmbientConfig(enabled=True),
    )
    assert failed.respond is False
    assert failed.memory_candidate is False
    assert failed.social_errand is None


def test_classifier_honors_disabled_memory_and_social_errand_flags(monkeypatch):
    def fake_call_llm(**kwargs):
        return _Response(
            """
            {
              "respond": false,
              "memory_candidate": true,
              "memory": {"person": "Alice", "fact": "likes tea", "confidence": 0.95, "sensitivity": "low"},
              "social_errand": {"action": "immediate_relay", "recipient_person": "Bob", "message": "hello"},
              "confidence": 0.9
            }
            """
        )

    monkeypatch.setattr("agent.auxiliary_client.call_llm", fake_call_llm)

    decision = classify_ambient_message(
        message_text="hello",
        recent_context=[],
        sender_person=None,
        identity_summary=None,
        config=AmbientConfig(enabled=True, memory_enabled=False, social_errands_enabled=False),
    )

    assert decision.respond is False
    assert decision.memory_candidate is False
    assert decision.memory is None
    assert decision.social_errand is None
