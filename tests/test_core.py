"""
Tests for time_utils.py and comparator.py.

Run with: pytest tests/ -v
"""

from __future__ import annotations
from datetime import datetime, timedelta
import pytest
import pytz

# We test without DB/network — patch settings before import
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")

from backend.logic.time_utils import (
    CHICAGO_TZ, UTC_TZ,
    to_utc, to_chicago, to_fake_week, dst_correction,
    spans_end_of_week, fake_week_end_of_week,
)
from backend.logic.comparator import compare, _derive_uptime_intervals
from backend.models.domain import (
    ConflictStatus, MarketGroupOverride, ScheduledTask,
    TaskSource, TaskType, TradingInterval,
)


# ---------------------------------------------------------------------------
# time_utils tests
# ---------------------------------------------------------------------------

class TestToFakeWeek:
    """
    Verify fake-week normalisation maps to correct 1900-04-xx dates.
    Reference: Sunday=Apr1, Mon=Apr2 … Sat=Apr7
    """

    def _utc(self, y, mo, d, h, mi=0, s=0):
        return datetime(y, mo, d, h, mi, s, tzinfo=UTC_TZ)

    def test_sunday_maps_to_apr1(self):
        # 2024-01-07 is a Sunday
        dt = self._utc(2024, 1, 7, 17, 30, 0)
        result = to_fake_week(dt)
        assert result.month == 4
        assert result.day == 1
        assert result.hour == 17
        assert result.minute == 30

    def test_monday_maps_to_apr2(self):
        dt = self._utc(2024, 1, 8, 9, 0, 0)   # Monday
        result = to_fake_week(dt)
        assert result.day == 2

    def test_saturday_maps_to_apr7(self):
        dt = self._utc(2024, 1, 13, 23, 59, 0)  # Saturday
        result = to_fake_week(dt)
        assert result.day == 7
        assert result.hour == 23
        assert result.minute == 59

    def test_result_is_utc(self):
        dt = self._utc(2024, 3, 20, 12, 0, 0)
        result = to_fake_week(dt)
        assert result.tzinfo == UTC_TZ

    def test_year_is_1900(self):
        dt = self._utc(2024, 6, 15, 8, 0, 0)
        result = to_fake_week(dt)
        assert result.year == 1900


class TestDstCorrection:
    """Verify the PS-equivalent DST correction logic."""

    def _chicago(self, *args):
        return CHICAGO_TZ.localize(datetime(*args))

    def test_no_correction_when_both_standard(self):
        # January — both standard time
        now = self._chicago(2024, 1, 15, 12, 0)
        dt = self._chicago(2024, 1, 10, 9, 0)
        result = dst_correction(dt, reference_now=now)
        assert result == dt

    def test_no_correction_when_both_dst(self):
        # July — both DST
        now = self._chicago(2024, 7, 15, 12, 0)
        dt = self._chicago(2024, 7, 10, 9, 0)
        result = dst_correction(dt, reference_now=now)
        assert result == dt

    def test_subtract_hour_when_now_standard_dt_dst(self):
        # now is January (standard), dt is in July (DST)
        now = self._chicago(2024, 1, 15, 12, 0)
        dt = self._chicago(2024, 7, 10, 9, 0)
        result = dst_correction(dt, reference_now=now)
        assert result == dt - timedelta(hours=1)

    def test_add_hour_when_now_dst_dt_standard(self):
        # now is July (DST), dt is in January (standard)
        now = self._chicago(2024, 7, 15, 12, 0)
        dt = self._chicago(2024, 1, 10, 9, 0)
        result = dst_correction(dt, reference_now=now)
        assert result == dt + timedelta(hours=1)


class TestSpansEndOfWeek:
    def _dt(self, day, hour):
        """Helper: fake-week datetime (1900-04-dd)."""
        return datetime(1900, 4, day, hour, 0, 0, tzinfo=UTC_TZ)

    def test_normal_week_no_span(self):
        # Start Sunday 17:00, Stop Friday 16:00 → last start < last stop
        starts = [self._dt(1, 17), self._dt(2, 17)]
        stops = [self._dt(2, 16), self._dt(5, 16)]
        assert not spans_end_of_week(starts, stops)

    def test_spans_eow(self):
        # Start Friday 17:00, Stop Monday 16:00 (last start > last stop)
        starts = [self._dt(1, 17), self._dt(6, 17)]   # Sun + Fri
        stops = [self._dt(2, 16)]                       # Mon only
        assert spans_end_of_week(starts, stops)

    def test_empty_start(self):
        assert not spans_end_of_week([], [self._dt(1, 16)])

    def test_empty_stop(self):
        assert not spans_end_of_week([self._dt(1, 17)], [])


# ---------------------------------------------------------------------------
# comparator tests
# ---------------------------------------------------------------------------

def _fake_dt(day: int, hour: int, minute: int = 0) -> datetime:
    """Build a fake-week UTC datetime."""
    return datetime(1900, 4, day, hour, minute, 0, tzinfo=UTC_TZ)


def _real_dt(weekday_offset: int, hour: int) -> datetime:
    """Build a real UTC datetime for use in TradingInterval (comparator converts it)."""
    # Use 2024-04-07 (Sunday) as base
    base = datetime(2024, 4, 7, tzinfo=UTC_TZ)
    return base + timedelta(days=weekday_offset, hours=hour)


def _make_task(
    name: str,
    t_type: TaskType,
    run_times: list[datetime],
    computer: str = "box1",
) -> ScheduledTask:
    return ScheduledTask(
        computer_name=computer,
        name=name,
        directory="/",
        weekly_run_times=run_times,
        messenger_name="test_msgr",
        task_type=t_type,
        enabled=True,
        source=TaskSource.WINDOWS,
    )


def _make_mg(task_name: str = "ICE") -> MarketGroupOverride:
    return MarketGroupOverride(
        name="ICE UK",
        route_group_id=5,
        task_name=task_name,
    )


class TestDeriveUptimeIntervals:
    def test_simple_pair(self):
        start_task = _make_task(
            "ICE messenger start", TaskType.START,
            [_fake_dt(1, 17)],  # Sunday 17:00
        )
        stop_task = _make_task(
            "ICE messenger stop", TaskType.STOP,
            [_fake_dt(6, 16)],  # Friday 16:00
        )
        intervals = _derive_uptime_intervals(
            [start_task, stop_task], "box1", "ICE UK"
        )
        assert len(intervals) == 1
        assert intervals[0].from_utc == _fake_dt(1, 17)
        assert intervals[0].to_utc == _fake_dt(6, 16)

    def test_unpaired_start_runs_to_eow(self):
        start_task = _make_task(
            "ICE messenger start", TaskType.START,
            [_fake_dt(1, 17)],
        )
        intervals = _derive_uptime_intervals([start_task], "box1", "ICE UK")
        assert len(intervals) == 1
        assert intervals[0].to_utc == fake_week_end_of_week()
        assert "No matching stop" in intervals[0].stop_task

    def test_multiple_pairs(self):
        starts = [_fake_dt(1, 17), _fake_dt(3, 17)]  # Sun + Tue
        stops = [_fake_dt(2, 16), _fake_dt(5, 16)]   # Mon + Thu
        start_task = _make_task("ICE messenger start", TaskType.START, starts)
        stop_task = _make_task("ICE messenger stop", TaskType.STOP, stops)
        intervals = _derive_uptime_intervals(
            [start_task, stop_task], "box1", "ICE UK"
        )
        assert len(intervals) == 2


class TestCompare:
    """Integration-style tests for the full compare() function."""

    def _trading_interval(self, start_day, start_hour, stop_day, stop_hour):
        # TradingIntervals use real UTC datetimes; comparator calls to_fake_week()
        base = datetime(2024, 4, 7, tzinfo=UTC_TZ)  # Sunday
        return TradingInterval(
            start_utc=base + timedelta(days=start_day - 1, hours=start_hour),
            stop_utc=base + timedelta(days=stop_day - 1, hours=stop_hour),
        )

    def test_ok_when_fully_covered(self):
        # Trading: Sun 17:00 → Mon 16:00
        # Task: Sun 16:55 → Mon 16:05
        mg = _make_mg("ICE messenger")
        interval = self._trading_interval(1, 17, 2, 16)
        start_task = _make_task("ICE messenger start", TaskType.START, [_fake_dt(1, 16, 55)])
        stop_task = _make_task("ICE messenger stop", TaskType.STOP, [_fake_dt(2, 16, 5)])

        result = compare(mg, [interval], [start_task, stop_task])
        assert result.trading_intervals[0].status == ConflictStatus.OK

    def test_partial_when_task_starts_late(self):
        # Trading: Sun 17:00 → Mon 16:00
        # Task: Sun 17:05 → Mon 16:05 (starts 5 min late — exceeds 1s tolerance)
        mg = _make_mg("ICE messenger")
        interval = self._trading_interval(1, 17, 2, 16)
        start_task = _make_task("ICE messenger start", TaskType.START, [_fake_dt(1, 17, 5)])
        stop_task = _make_task("ICE messenger stop", TaskType.STOP, [_fake_dt(2, 16, 5)])

        result = compare(mg, [interval], [start_task, stop_task])
        assert result.trading_intervals[0].status == ConflictStatus.PARTIAL

    def test_conflict_when_no_tasks(self):
        mg = _make_mg("ICE messenger")
        interval = self._trading_interval(1, 17, 2, 16)
        result = compare(mg, [interval], [])
        assert result.trading_intervals[0].status == ConflictStatus.CONFLICT

    def test_ignored_flag_propagated(self):
        mg = MarketGroupOverride(name="ICE UK", route_group_id=5, ignore=True)
        result = compare(mg, [], [])
        assert result.ignored is True

    def test_comment_propagated(self):
        mg = MarketGroupOverride(
            name="ICE UK", route_group_id=5, comment="Test comment"
        )
        result = compare(mg, [], [])
        assert result.comment == "Test comment"
