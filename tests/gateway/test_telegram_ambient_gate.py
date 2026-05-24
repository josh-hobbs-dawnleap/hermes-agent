from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from gateway.config import AmbientConfig, GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageType
from gateway.platforms.telegram import TelegramAdapter


class _Store:
    def __init__(self):
        self.entries = []

    def get_or_create_session(self, source):
        return SimpleNamespace(session_id="session-1")

    def append_to_transcript(self, session_id, entry):
        self.entries.append((session_id, entry))


def _adapter(extra=None):
    adapter = object.__new__(TelegramAdapter)
    adapter.platform = Platform.TELEGRAM
    adapter.config = PlatformConfig(enabled=True, token="***", extra=extra or {})
    adapter._bot = SimpleNamespace(id=999, username="hermes_bot")
    adapter._mention_patterns = []
    adapter._session_store = _Store()
    adapter._ambient_last_response_monotonic = {}
    adapter._gateway_config = GatewayConfig(ambient=AmbientConfig(enabled=True, response_cooldown_seconds=60))
    return adapter


def _message(text="ordinary chat", chat_id=-100, user_id=1, thread_id=None):
    return SimpleNamespace(
        text=text,
        caption=None,
        entities=[],
        caption_entities=[],
        message_thread_id=thread_id,
        message_id=55,
        chat=SimpleNamespace(id=chat_id, type="group", title="Group"),
        from_user=SimpleNamespace(id=user_id, username="alice", full_name="Alice"),
        reply_to_message=None,
        date=datetime.now(UTC),
    )


def test_ambient_gate_silences_store_only_message(monkeypatch):
    adapter = _adapter(
        {
            "require_mention": True,
            "observe_unmentioned_group_messages": True,
            "group_allowed_chats": ["-100"],
            "ambient_chats": ["-100"],
        }
    )
    monkeypatch.setattr(
        "gateway.platforms.telegram.classify_ambient_message",
        lambda **kwargs: SimpleNamespace(respond=False),
    )

    assert adapter._handle_ambient_unmentioned_group_message(_message(), MessageType.TEXT, update_id=1) is False
    assert adapter._session_store.entries[0][1]["observed"] is True


def test_ambient_gate_wakes_agent_and_skips_observed_store_when_responds(monkeypatch):
    adapter = _adapter(
        {
            "require_mention": True,
            "observe_unmentioned_group_messages": True,
            "group_allowed_chats": ["-100"],
            "ambient_chats": ["-100"],
        }
    )
    monkeypatch.setattr(
        "gateway.platforms.telegram.classify_ambient_message",
        lambda **kwargs: SimpleNamespace(respond=True, respond_reason="asked group for help"),
    )

    event = adapter._ambient_event_for_unmentioned_group_message(_message(), MessageType.TEXT, update_id=1)

    assert event is not None
    assert event.enabled_toolsets == []
    assert "Ambient wake" in event.channel_prompt
    assert "Do not use tools" in event.channel_prompt
    assert "observed Telegram group context" in event.channel_prompt
    assert adapter._session_store.entries == []


def test_ambient_gate_respects_cooldown(monkeypatch):
    adapter = _adapter(
        {
            "require_mention": True,
            "observe_unmentioned_group_messages": True,
            "group_allowed_chats": ["-100"],
            "ambient_chats": ["-100"],
        }
    )
    adapter._ambient_last_response_monotonic["-100:None"] = 100.0
    monkeypatch.setattr("time.monotonic", lambda: 120.0)
    monkeypatch.setattr(
        "gateway.platforms.telegram.classify_ambient_message",
        lambda **kwargs: SimpleNamespace(respond=True),
    )

    assert adapter._ambient_event_for_unmentioned_group_message(_message(), MessageType.TEXT, update_id=1) is None


def test_ambient_gate_off_by_default_for_non_ambient_chat(monkeypatch):
    adapter = _adapter(
        {
            "require_mention": True,
            "observe_unmentioned_group_messages": True,
            "group_allowed_chats": ["-100"],
            "ambient_chats": ["-200"],
        }
    )
    called = False

    def fake_classifier(**kwargs):
        nonlocal called
        called = True
        return SimpleNamespace(respond=True)

    monkeypatch.setattr("gateway.platforms.telegram.classify_ambient_message", fake_classifier)

    assert adapter._ambient_event_for_unmentioned_group_message(_message(), MessageType.TEXT, update_id=1) is None
    assert called is False


def test_ambient_gate_supports_chat_topic_allowlist(monkeypatch):
    adapter = _adapter(
        {
            "require_mention": True,
            "observe_unmentioned_group_messages": True,
            "group_allowed_chats": ["-100"],
            "ambient_chats": ["-100:77"],
        }
    )
    monkeypatch.setattr(
        "gateway.platforms.telegram.classify_ambient_message",
        lambda **kwargs: SimpleNamespace(respond=True),
    )

    assert adapter._ambient_event_for_unmentioned_group_message(
        _message(chat_id=-100, thread_id=12), MessageType.TEXT, update_id=1
    ) is None
    assert adapter._ambient_event_for_unmentioned_group_message(
        _message(chat_id=-100, thread_id=77), MessageType.TEXT, update_id=1
    ) is not None


@pytest.mark.asyncio
async def test_async_ambient_gate_runs_classifier_off_event_loop(monkeypatch):
    adapter = _adapter(
        {
            "require_mention": True,
            "observe_unmentioned_group_messages": True,
            "group_allowed_chats": ["-100"],
            "ambient_chats": ["-100"],
        }
    )
    to_thread_calls = []

    async def fake_to_thread(func, /, *args, **kwargs):
        to_thread_calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr(
        "gateway.platforms.telegram.classify_ambient_message",
        lambda **kwargs: SimpleNamespace(respond=True),
    )

    event = await adapter._ambient_event_for_unmentioned_group_message_async(
        _message(), MessageType.TEXT, update_id=1
    )

    assert event is not None
    assert to_thread_calls
