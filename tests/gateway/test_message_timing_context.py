"""Tests for gateway message timing context injection."""
from datetime import UTC, datetime, timezone, timedelta

from gateway.run import _prepend_message_timing_context


def test_prepends_trigger_and_host_timestamps_to_user_message():
    sent_at = datetime(2026, 6, 19, 21, 42, 3, tzinfo=UTC)
    handled_at = datetime(2026, 6, 19, 21, 42, 8, tzinfo=timezone(timedelta(hours=-6)))

    result = _prepend_message_timing_context(
        "How are you, Winston?",
        sent_at=sent_at,
        handled_at=handled_at,
    )

    assert result.startswith("[Message timing]")
    assert "Triggering message sent at: 2026-06-19T21:42:03+00:00" in result
    assert "Host time now: 2026-06-19T21:42:08-06:00" in result
    assert result.endswith("\n\nHow are you, Winston?")


def test_timing_context_preserves_empty_message_body():
    sent_at = datetime(2026, 6, 19, 21, 42, 3, tzinfo=UTC)
    handled_at = datetime(2026, 6, 19, 21, 42, 8, tzinfo=UTC)

    result = _prepend_message_timing_context("", sent_at=sent_at, handled_at=handled_at)

    assert "Triggering message sent at: 2026-06-19T21:42:03+00:00" in result
    assert result.endswith("\n\n")
