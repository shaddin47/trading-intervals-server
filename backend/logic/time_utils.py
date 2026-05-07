"""
time_utils.py — Timezone conversion and schedule-window normalisation.

Display window
--------------
Previous/current Sunday 00:00 UTC through Monday two weeks later (15 days).
All schedule times (SP fake-week dates, Windows task triggers, Linux crons)
are mapped into this window.

Fake-week → real date mapping
------------------------------
The SQL SP and Windows task XML store times as fake-week dates
(1900-04-01 = Sunday … 1900-04-07 = Saturday).  We extract the
day-of-week and time-of-day, then place them on the corresponding
day of the current real week anchored to this Sunday.

For start/stop pairs, always convert as a pair using
interval_to_current_week() — converting independently can invert an
interval that spans midnight (e.g. Sunday 23:30 start → Monday 20:30 stop).
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
import pytz

CHICAGO_TZ = pytz.timezone("America/Chicago")
UTC_TZ     = pytz.utc

# Python weekday() → days-since-Sunday (Sun=0, Mon=1 … Sat=6)
_PY_TO_DAYS_FROM_SUN: dict[int, int] = {
    6: 0,  # Sunday
    0: 1,  # Monday
    1: 2,  # Tuesday
    2: 3,  # Wednesday
    3: 4,  # Thursday
    4: 5,  # Friday
    5: 6,  # Saturday
}


def _this_week_sunday_utc(reference: datetime | None = None) -> datetime:
    """
    Return this week's Sunday 00:00:00 UTC — the anchor of the display window.
    'This week' means the most-recent Sunday on or before `reference`.
    """
    ref = to_utc(reference or datetime.now(UTC_TZ))
    days_since_sun = _PY_TO_DAYS_FROM_SUN[ref.weekday()]
    sunday = ref.replace(hour=0, minute=0, second=0, microsecond=0) \
             - timedelta(days=days_since_sun)
    return sunday


def window_start(reference: datetime | None = None) -> datetime:
    """Sunday 00:00 UTC — left edge of the 15-day display window."""
    return _this_week_sunday_utc(reference)


def window_end(reference: datetime | None = None) -> datetime:
    """Monday 00:00 UTC two weeks after this Sunday — right edge."""
    return _this_week_sunday_utc(reference) + timedelta(days=15)


def to_utc(dt: datetime) -> datetime:
    """Ensure dt is UTC-aware. Naive datetimes are assumed UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(UTC_TZ)



def to_current_week(dt: datetime, reference: datetime | None = None) -> datetime:
    """
    Map a fake-week datetime (or any datetime) into the current 15-day window.

    Extracts day-of-week and time-of-day from dt (in UTC), then places
    it on the matching real calendar day in the current window, anchored
    to this week's Sunday.

    If the result falls outside the 15-day window (e.g. the day-of-week
    is in next week and the anchor is this Sunday), it is placed in
    next week naturally — both occurrences appear in the 15-day span.

    Do NOT call this independently for start and stop of the same interval.
    Use interval_to_current_week() instead to preserve the pair relationship.
    """
    dt_utc = to_utc(dt)
    sunday  = _this_week_sunday_utc(reference)
    days_from_sun = _PY_TO_DAYS_FROM_SUN[dt_utc.weekday()]

    return sunday.replace(
        hour=dt_utc.hour,
        minute=dt_utc.minute,
        second=dt_utc.second,
        microsecond=0,
    ) + timedelta(days=days_from_sun)


# Alias retained for callers that haven't been updated
def interval_to_current_week(
    start: datetime,
    stop: datetime,
    reference: datetime | None = None,
) -> tuple[datetime, datetime]:
    """
    Convert a start/stop pair into the current window, preserving duration.

    Converting each time independently can invert the interval when start
    and stop are on different days (e.g. Sunday start → Monday stop).
    This function converts start first, then sets stop = start + duration.
    """
    duration   = to_utc(stop) - to_utc(start)
    real_start = to_current_week(start, reference)
    real_stop  = real_start + duration
    return real_start, real_stop


def clone_to_week2(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """
    Clone a list of (start, stop) pairs to the following week,
    adjusting for DST changes between the two weeks.

    The 15-day display window spans this Sunday through Monday +2 weeks.
    The SP and task XMLs only contain one week of schedule data.
    This function produces the second week's occurrences.

    DST adjustment:
      Each time is re-expressed in Chicago local time and then
      re-converted to UTC for the following week's date.  This correctly
      handles the case where DST changes between week 1 and week 2
      (e.g. clocks spring forward on Sunday — the Chicago wall-clock
      time stays the same but the UTC offset changes by 1 hour).
    """
    result: list[tuple[datetime, datetime]] = []
    for start_utc, stop_utc in intervals:
        duration = stop_utc - start_utc

        # Re-express start in Chicago, advance to next week's same local time
        start_chi = start_utc.astimezone(CHICAGO_TZ)
        next_week_naive = start_chi.replace(tzinfo=None) + timedelta(weeks=1)
        # Re-localise to pick up any DST change that occurs in the intervening week
        next_start_chi = CHICAGO_TZ.normalize(CHICAGO_TZ.localize(next_week_naive))
        next_start_utc = next_start_chi.astimezone(UTC_TZ)
        next_stop_utc  = next_start_utc + duration

        result.append((next_start_utc, next_stop_utc))
    return result


def current_week_end(reference: datetime | None = None) -> datetime:
    """End-of-window sentinel: Monday 00:00 UTC two weeks after this Sunday."""
    return window_end(reference)



