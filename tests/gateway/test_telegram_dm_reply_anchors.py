"""Telegram DM reply-anchor policy tests."""

from gateway.config import Platform
from gateway.platforms.base import (
    MessageEvent,
    MessageType,
    _reply_anchor_for_event,
    _thread_metadata_for_source,
)
from gateway.session import SessionSource


def _telegram_dm_source(*, thread_id: str | None = "42") -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="12345",
        chat_type="dm",
        user_id="u1",
        user_name="Josh",
        thread_id=thread_id,
        message_id="source-msg",
    )


def test_telegram_dm_normal_message_has_no_reply_anchor() -> None:
    event = MessageEvent(
        text="normal DM",
        message_type=MessageType.TEXT,
        source=_telegram_dm_source(),
        message_id="trigger-msg",
    )

    assert _reply_anchor_for_event(event) is None


def test_telegram_dm_preserves_user_selected_reply_target() -> None:
    event = MessageEvent(
        text="what, when did I say that?",
        message_type=MessageType.TEXT,
        source=_telegram_dm_source(),
        message_id="trigger-msg",
        reply_to_message_id="quoted-msg",
    )

    assert _reply_anchor_for_event(event) == "quoted-msg"


def test_telegram_dm_topic_metadata_does_not_fall_back_to_trigger_message() -> None:
    metadata = _thread_metadata_for_source(_telegram_dm_source(), reply_to_message_id=None)

    assert metadata == {
        "thread_id": "42",
        "telegram_dm_topic_reply_fallback": True,
        "direct_messages_topic_id": "42",
    }


def test_telegram_dm_topic_metadata_keeps_explicit_reply_target() -> None:
    metadata = _thread_metadata_for_source(_telegram_dm_source(), reply_to_message_id="quoted-msg")

    assert metadata == {
        "thread_id": "42",
        "telegram_dm_topic_reply_fallback": True,
        "direct_messages_topic_id": "42",
        "telegram_reply_to_message_id": "quoted-msg",
    }


def test_telegram_group_keeps_normal_reply_anchor_policy() -> None:
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-1001",
        chat_type="group",
        user_id="u1",
        thread_id=None,
    )
    event = MessageEvent(
        text="group mention",
        message_type=MessageType.TEXT,
        source=source,
        message_id="group-msg",
    )

    assert _reply_anchor_for_event(event) == "group-msg"
