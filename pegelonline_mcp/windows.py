"""The time window of the history and chart tools: hours back from now, or start and end."""

from datetime import UTC, datetime, timedelta

from pegelonline_mcp.client import HISTORY_MINUTES
from pegelonline_mcp.errors import caller_error

# Time span of the history and the chart without hours or start
DEFAULT_HOURS = 24
# How far back a time window may start and how long it may be, like hours
MAX_WINDOW = timedelta(minutes=HISTORY_MINUTES)


def window_start(
    hours: float | None, start: datetime | None, end: datetime | None
) -> datetime | timedelta:
    """Start of the time window to fetch: start itself, or hours back from now.

    Rejects a window that mixes hours and start or that the API cannot serve.
    """
    if hours is not None and start is not None:
        raise caller_error("Pass either hours or start, not both.")
    if start is None:
        if end is not None:
            raise caller_error(
                "end needs start; for the last N hours, pass hours alone."
            )
        return timedelta(hours=hours or DEFAULT_HOURS)
    now = datetime.now(UTC)
    end = end or now
    if start >= end:
        raise caller_error("start must lie before end (default: now).")
    if start < now - MAX_WINDOW:
        raise caller_error(
            f"start lies more than {MAX_WINDOW.days} days back; the official API "
            "keeps measurements for a little over 31 days."
        )
    if end - start > MAX_WINDOW:
        raise caller_error(
            f"start and end may lie at most {HISTORY_MINUTES // 60} hours apart."
        )
    return start


def absolute_window(
    hours: float | None, start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    """Start and end of the window that window_start checks, both in UTC.

    The chart UI fetches its values for these ends later, so they match the
    summary instead of moving with the clock.
    """
    since = window_start(hours, start, end)
    now = datetime.now(UTC).replace(microsecond=0)
    if isinstance(since, timedelta):
        return now - since, now
    return since.astimezone(UTC), (end or now).astimezone(UTC)
