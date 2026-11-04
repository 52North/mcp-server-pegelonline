"""Unit tests of the time window checks, without upstream or MCP client."""

from datetime import UTC, datetime, timedelta, timezone

from pegelonline_mcp import windows

CEST = timezone(timedelta(hours=2))


def test_window_start_defaults_to_the_last_day():
    assert windows.window_start(None, None, None) == timedelta(hours=24)


def test_window_start_of_hours():
    assert windows.window_start(168, None, None) == timedelta(hours=168)


def test_window_start_accepts_start_just_within_the_kept_history():
    start = datetime.now(UTC) - windows.MAX_WINDOW + timedelta(minutes=1)

    assert windows.window_start(None, start, None) == start


def test_absolute_window_of_hours_ends_now_in_utc():
    before = datetime.now(UTC).replace(microsecond=0)
    start, end = windows.absolute_window(6, None, None)

    assert end.tzinfo == UTC
    assert end.microsecond == 0
    assert before <= end <= datetime.now(UTC)
    assert end - start == timedelta(hours=6)


def test_absolute_window_converts_start_and_end_to_utc():
    start = datetime.now(CEST).replace(microsecond=0) - timedelta(days=2)
    end = start + timedelta(hours=12)

    window = windows.absolute_window(None, start, end)

    assert window == (start, end)
    assert all(t.tzinfo == UTC for t in window)
