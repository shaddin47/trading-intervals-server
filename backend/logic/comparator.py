"""
comparator.py — Conflict detection between trading intervals and messenger tasks.

Python port of the comparison logic in TradingIntervals.psm1 (lines 308–478).

Conflict rules (matching PS exactly):
  For each trading interval, find all messenger uptime intervals that overlap it.
  - No overlap found                           → CONFLICT  (red)
  - Overlap found AND (task_start > interval_start + 1s
                       OR interval_stop - task_stop > 60s) → PARTIAL  (amber)
  - Overlap found AND task fully covers interval             → OK       (green)

Fake-week normalisation:
  Both trading intervals and task run-times must be on the fake-week reference
  real current-week UTC datetimes. to_current_week() is applied to SP dates
  and task run-times before they reach this module.
"""
from __future__ import annotations
import re
import logging
from datetime import datetime, timedelta
from typing import Optional

from backend.logic.time_utils import (
    UTC_TZ, current_week_end, window_start
)
from backend.models.domain import (
    ConflictStatus,
    EvaluatedInterval,
    MarketGroupOverride,
    MarketGroupResult,
    MessengerCoverage,
    ScheduledTask,
    TaskSource,
    TaskType,
    TradingInterval,
    UptimeInterval,
)

logger = logging.getLogger(__name__)

# Tolerance thresholds (matching PowerShell logic exactly)
_START_TOLERANCE = timedelta(seconds=1)    # task may start up to 1s late
_STOP_TOLERANCE = timedelta(minutes=1)     # task may stop up to 1min early

# _END_OF_WEEK is computed per-call in _derive_uptime_intervals to stay current.


# ---------------------------------------------------------------------------
# Task name matching
# ---------------------------------------------------------------------------

def _tasks_match_market_group(
    task: ScheduledTask,
    mg: MarketGroupOverride,
) -> bool:
    """
    Return True if the task's name matches any of the market group's
    task name aliases. Matching is case-insensitive throughout.

    Windows task names:   "ICE Messenger Start" → strip " Messenger.*" → "ICE"
    Linux cron names:     "iceb_group cron_start" → strip "_group.*" → "iceb"
    Both compared case-insensitively against task_name_list aliases.
    """
    normalised = task.name
    normalised = re.sub(r" messenger.*", "", normalised, flags=re.IGNORECASE)
    normalised = re.sub(r"_group.*",    "", normalised, flags=re.IGNORECASE)
    normalised = normalised.strip().lower()

    return normalised in mg.task_name_list  # task_name_list is always lowercase


# ---------------------------------------------------------------------------
# Uptime interval derivation
# ---------------------------------------------------------------------------

def _derive_uptime_intervals(
    tasks: list[ScheduledTask],
    computer_name: str,
    market_group_name: str,
) -> list[UptimeInterval]:
    """
    Pair Start/Stop run-times into uptime intervals for one gateway box.

    Pre-window start handling:
      Tasks are fetched back to Saturday to capture starts that fired
      before the display window (Sunday 00:00 UTC) but whose stop falls
      within the window.  If the first event inside the window is a Stop
      with no preceding Start, the messenger was already running — we
      open a synthetic interval from window_start() to that Stop.

      Pre-window starts (before window_start()) are tracked separately:
      if the last pre-window event is a Start, the messenger is considered
      running at window open.

    Un-paired trailing Start → interval extends to current_week_end().
    """
    win_start = window_start()

    # Flatten all run-times for this box
    events: list[tuple[datetime, bool, str]] = []
    for task in tasks:
        if task.computer_name != computer_name:
            continue
        is_start = task.task_type == TaskType.START
        for rt in task.weekly_run_times:
            events.append((rt, is_start, task.name))

    events.sort(key=lambda e: e[0])

    # Split into pre-window and in-window events
    pre_window  = [(t, s, n) for t, s, n in events if t < win_start]
    in_window   = [(t, s, n) for t, s, n in events if t >= win_start]

    # Determine if messenger is already running at window open by
    # replaying pre-window events: the last state change is what matters.
    running_at_open = False
    running_task    = "Running at window start"
    pre_state = False  # False = stopped
    pre_task  = ""
    for _, is_start, task_name in pre_window:
        pre_state = is_start
        pre_task  = task_name
    if pre_window:
        running_at_open = pre_state
        running_task    = pre_task

    intervals: list[UptimeInterval] = []
    pending_start: Optional[datetime] = None
    pending_start_task: Optional[str] = None

    # If already running at window open, treat window_start as a synthetic start
    if running_at_open:
        pending_start      = win_start
        pending_start_task = running_task

    for event_time, is_start, task_name in in_window:
        if not is_start:
            if pending_start is not None:
                # Close the open interval
                intervals.append(UptimeInterval(
                    from_utc=pending_start,
                    to_utc=event_time,
                    start_task=pending_start_task,
                    stop_task=task_name,
                ))
                pending_start = pending_start_task = None
            # else: orphan stop with no matching start — skip

        else:  # is_start
            if pending_start is None:
                pending_start      = event_time
                pending_start_task = task_name
            # else: consecutive start with no stop between — skip

    # Un-paired trailing start → runs to end of window
    if pending_start is not None:
        intervals.append(UptimeInterval(
            from_utc=pending_start,
            to_utc=current_week_end(),
            start_task=pending_start_task,
            stop_task="No matching stop task exists!",
        ))

    return intervals

def _evaluate_uptime_statuses(
    uptimes: list[UptimeInterval],
    trading_intervals: list[TradingInterval],
) -> list[UptimeInterval]:
    """
    Set the status on each uptime interval based on how well it covers
    all trading intervals it overlaps. Worst-case across all overlapping
    trading intervals:
      - No overlap with any trading interval → OK (uptime is fine, just not needed)
      - Overlaps at least one, all fully covered → OK
      - Overlaps at least one, any partially covered → PARTIAL
      - (CONFLICT is not assigned here; a non-overlapping uptime is just OK)

    Note: CONFLICT on a trading interval means NO uptime covers it at all —
    that's evaluated in _evaluate_interval. An uptime that doesn't overlap
    any trading interval is not itself in conflict.
    """
    result = []
    for u in uptimes:
        worst = ConflictStatus.OK
        for ti in trading_intervals:
            t_from = ti.start_utc
            t_to   = ti.stop_utc
            # Does this uptime overlap this trading interval?
            if u.from_utc < t_to and u.to_utc > t_from:
                start_late = (u.from_utc - t_from) > _START_TOLERANCE
                stop_early = (t_to - u.to_utc)     > _STOP_TOLERANCE
                if start_late or stop_early:
                    worst = ConflictStatus.PARTIAL
                    # Can't get worse than PARTIAL per uptime, so break early
                    break
                # else OK — don't downgrade
        result.append(UptimeInterval(
            from_utc=u.from_utc,
            to_utc=u.to_utc,
            start_task=u.start_task,
            stop_task=u.stop_task,
            status=worst,
        ))
    return result

# ---------------------------------------------------------------------------
# Interval evaluation
# ---------------------------------------------------------------------------

def _evaluate_interval(
    trading: TradingInterval,
    coverages: list[MessengerCoverage],
    source_map: dict[str, str],
) -> EvaluatedInterval:
    t_from = trading.start_utc
    t_to   = trading.stop_utc

    best_start_task: Optional[str] = None
    best_stop_task: Optional[str] = None
    best_computer: Optional[str] = None
    worst_coverage = ConflictStatus.OK

    for coverage in coverages:
        for uptime in coverage.uptime_intervals:
            if t_from < uptime.to_utc and t_to > uptime.from_utc:
                if best_computer is None:
                    best_start_task = uptime.start_task
                    best_stop_task  = uptime.stop_task
                    best_computer   = coverage.computer_name
                # Accumulate worst coverage across all overlapping uptimes
                if uptime.status == ConflictStatus.PARTIAL:
                    worst_coverage = ConflictStatus.PARTIAL

    status = ConflictStatus.OK if best_computer is not None else ConflictStatus.CONFLICT

    return EvaluatedInterval(
        from_utc=t_from,
        to_utc=t_to,
        status=status,
        coverage=worst_coverage if status == ConflictStatus.OK else ConflictStatus.CONFLICT,
        start_xbit=trading.start_xbit,
        stop_xbit=trading.stop_xbit,
        all_xbit=trading.all_xbit,
        start_task=best_start_task,
        stop_task=best_stop_task,
        computer_name=best_computer,
        source=TaskSource(source_map[best_computer]) if best_computer and best_computer in source_map else None,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare(
    market_group: MarketGroupOverride,
    trading_intervals: list[TradingInterval],
    all_tasks: list[ScheduledTask],
) -> MarketGroupResult:
    """
    Compare trading intervals against messenger tasks for one market group.

    Steps:
      1. Filter all_tasks to those matching this market group's task name aliases.
      2. Group matching tasks by computer_name.
      3. For each box, derive uptime intervals from Start/Stop pairs.
      4. For each trading interval, evaluate conflict status.

    Parameters
    ----------
    market_group:
        The market group configuration (name, aliases, etc.)
    trading_intervals:
        Raw intervals from the SQL SP (real UTC datetimes).
    all_tasks:
        All messenger tasks (Windows + Linux combined).

    Returns
    -------
    MarketGroupResult with evaluated intervals and per-box coverage.
    """
    # Step 1: Filter tasks
    matching_tasks = [
        t for t in all_tasks
        if t.enabled and _tasks_match_market_group(t, market_group)
    ]

    # Step 2: Group by computer
    boxes: dict[str, list[ScheduledTask]] = {}
    for task in matching_tasks:
        boxes.setdefault(task.computer_name, []).append(task)

    # Step 3: Derive uptime intervals per box, then evaluate their status
    coverages: list[MessengerCoverage] = []
    for computer_name, box_tasks in boxes.items():
        uptime_intervals = _derive_uptime_intervals(
            box_tasks, computer_name, market_group.name
        )
        # NEW: evaluate uptime status against trading intervals (worst-case)
        uptime_intervals = _evaluate_uptime_statuses(uptime_intervals, trading_intervals)
        if uptime_intervals:
            coverages.append(
                MessengerCoverage(
                    computer_name=computer_name,
                    uptime_intervals=uptime_intervals,
                )
            )

    # Build source_map once: {computer_name: TaskSource} from matching tasks
    # Used by _evaluate_interval for O(1) source lookup instead of O(tasks) scan
    source_map: dict[str, str] = {
        task.computer_name: task.source.value
        for task in matching_tasks
    }

    # Step 4: Evaluate each trading interval
    evaluated: list[EvaluatedInterval] = []
    for ti in trading_intervals:
        ev = _evaluate_interval(ti, coverages, source_map)
        evaluated.append(ev)

    if not evaluated:
        logger.warning(
            "No trading intervals for market group: %s", market_group.name
        )

    return MarketGroupResult(
        market_group=market_group.name,
        route_group_id=market_group.route_group_id,
        ignored=market_group.ignore,
        comment=market_group.comment,
        trading_intervals=evaluated,
        messenger_coverages=coverages,
    )
