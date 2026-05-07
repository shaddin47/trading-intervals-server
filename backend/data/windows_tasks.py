"""
windows_tasks.py — Parse Windows Scheduled Task XML from the archive.

Archive structure (corrected):
  /mnt/smb/dgwnas/archive/stasks_xml/
      2026_04_19_03_09_54/          ← timestamp dirs, pick most-recent by LastWriteTime
          CH2WGP-PMSG1/             ← one subdir per gateway box
              Messengers/           ← only XMLs inside Messengers/ subfolder needed
                  ICE Messenger Start.xml
                  ICE Messenger Stop.xml

Messenger task identification (matches PS exactly):
  taskName matches r'Messenger.*(Start|Stop)\\s*$'  (case-sensitive in PS, we use IGNORECASE)
  taskType  = last word of task name → 'Start' or 'Stop'
  MessengerName = taskName with r'\\s+Messenger.*' stripped

Day numbering (from PS Get-WeeklyScheduledTasksFromArchive):
  WeekBegin = 1900-03-31 (Saturday)
  DayNumber:  Sunday=1, Monday=2 ... Saturday=7
              mapped to real current-week dates via to_current_week()

  XML ScheduleByWeek uses child element names: Sunday, Monday, … Saturday
  XML ScheduleByDay (DaysInterval=1) → all days 1..7

Repetition:
  Triggers may have Repetition.Interval + Repetition.Duration.
  Additional run-times are generated at Interval offsets up to Duration.

DST flag:
  If task name contains '_DST ' extract it from 'Messenger <DST> (Start|Stop)' pattern.

Enabled:
  settings.enabled == 'true'  OR  settings.enabled tag is absent (None).
  Trigger-level: Enabled tag absent OR == 'true'.
"""

from __future__ import annotations
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from dateutil import parser as dateutil_parser

from backend.config import settings
from backend.logic.time_utils import CHICAGO_TZ, UTC_TZ, to_current_week, clone_to_week2
from backend.models.domain import ScheduledTask, TaskSource, TaskType

logger = logging.getLogger(__name__)

# Namespace map for Windows Task Scheduler XML
_NS = {"ts": "http://schemas.microsoft.com/windows/2004/02/mit/task"}

# Week begin is computed dynamically each refresh as the current Sunday 00:00 UTC.
# See time_utils._this_week_sunday_utc()

# XML day-element name → day offset from WeekBegin (1-7)
# Maps XML day-element name → days from Sunday (Sun=0, Mon=1 … Sat=6)
# Used to offset from the current week's Sunday 00:00 UTC.
_XML_DAY_OFFSET = {
    "Sunday":    0,
    "Monday":    1,
    "Tuesday":   2,
    "Wednesday": 3,
    "Thursday":  4,
    "Friday":    5,
    "Saturday":  6,
}

# Messenger task pattern (mirrors PS:  'Messenger.*(Start|Stop)\s*$')
_MSGR_PATTERN = re.compile(r"Messenger.*(Start|Stop)\s*$", re.IGNORECASE)
_DST_MSGR_PATTERN = re.compile(r"Messenger\s+(.+?)\s+(Start|Stop)\s*$", re.IGNORECASE)
_MSGR_NAME_STRIP = re.compile(r"\s+Messenger.*", re.IGNORECASE)
# Stage boxes are identified by "WGS-" in the hostname (e.g. CH3WGS-vmsgo1).
# The original PS used "...WGS-" as a wildcard match; in Python regex we
# match the literal substring anywhere in the name — no anchoring needed.
_STAGE_BOX_RE = re.compile(r"WGS-", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Archive helpers
# ---------------------------------------------------------------------------

# Module-level cache: resolved once per refresh cycle.
# clear_snapshot_cache() is called at the start of each scheduler run.
_snapshot_cache: dict[str, Path] = {}


def _find_latest_snapshot_dir(archive_root: str | Path) -> Path:
    """
    Return the most-recently written snapshot directory, efficiently.

    The archive root contains ~100 timestamp-named subdirectories
    (e.g. 2026_04_19_03_09_54) alongside ~38,000 .zip files.

    Using glob('[0-9]*') restricts the SMB QueryDirectory request to
    names that start with a digit.  This pattern is evaluated server-side
    (both by the Windows SMB server over CIFS and by pathlib on a local
    path), so the .zip files — which all contain a dot and start with
    digits but are *files* not directories — are filtered by the
    subsequent .is_dir() check on the small result set (~100 entries).

    The key win: only ~100 directory names cross the network instead of
    38,000 zip filenames.  No stat() calls are made.

    Timestamp names are zero-padded so lexicographic max == most recent.

    Result is cached for the lifetime of one refresh cycle.
    Call clear_snapshot_cache() at the start of each refresh.
    """
    cache_key = str(archive_root)
    cached = _snapshot_cache.get(cache_key)
    if cached is not None and cached.is_dir():
        return cached

    root = Path(archive_root)
    if not root.is_dir():
        raise FileNotFoundError(f"Archive root not accessible: {root}")

    matches = [p for p in root.glob("[0-9]*") if p.is_dir()]
    if not matches:
        raise FileNotFoundError(f"No snapshot directories found in {root}")

    latest = max(matches, key=lambda p: p.name)
    logger.info("Resolved snapshot directory: %s", latest)
    _snapshot_cache[cache_key] = latest
    return latest


def clear_snapshot_cache() -> None:
    """Clear the cached snapshot path. Call at the start of each refresh cycle."""
    _snapshot_cache.clear()


# ---------------------------------------------------------------------------
# ISO 8601 duration parser (PT1H30M etc.) → timedelta
# Matches SchedulerIntervalToTimeSpan in PS (month≈30d, year≈365d)
# ---------------------------------------------------------------------------

def _iso_duration_to_timedelta(duration: Optional[str]) -> Optional[timedelta]:
    if not duration or not duration.startswith("P"):
        return None
    s = duration[1:]
    date_part, _, time_part = s.partition("T")

    def _extract(text: str, letter: str) -> float:
        m = re.search(r"([\d.]+)" + letter, text)
        return float(m.group(1)) if m else 0.0

    days = _extract(date_part, "D")
    days += _extract(date_part, "M") * 30
    days += _extract(date_part, "Y") * 365
    hours = _extract(time_part, "H")
    minutes = _extract(time_part, "M")
    seconds = _extract(time_part, "S")
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _text(el: ET.Element, tag: str) -> Optional[str]:
    node = el.find(tag, _NS)
    return node.text if node is not None else None


def _task_enabled(task_xml: ET.Element) -> bool:
    """
    Task-level enabled check.
    PS: ($xml.task.settings.enabled -eq 'true') OR enabled tag is absent/null.
    """
    val = _text(task_xml, "ts:Settings/ts:Enabled")
    if val is None:
        return True  # absent = enabled (Win2019 behaviour)
    return val.strip().lower() == "true"


def _trigger_enabled(trigger: ET.Element) -> bool:
    """
    Trigger-level enabled check.
    PS: (-not $curTrigger.Enabled) -and $curTrigger.Enabled -ne $null → skip
    i.e. if Enabled tag is present AND is not 'true' → disabled.
    """
    node = trigger.find("ts:Enabled", _NS)
    if node is None:
        return True  # absent = enabled
    return node.text.strip().lower() == "true"


def _parse_start_boundary(boundary: str) -> Optional[datetime]:
    """
    Parse StartBoundary (ISO 8601 local time, possibly with offset).
    If naive, assume Chicago local (matches where GW boxes run).
    """
    if not boundary:
        return None
    try:
        dt = dateutil_parser.parse(boundary)
        if dt.tzinfo is None:
            dt = CHICAGO_TZ.localize(dt)
        return dt
    except Exception as exc:
        logger.debug("Cannot parse StartBoundary '%s': %s", boundary, exc)
        return None


def _expand_trigger(
    trigger: ET.Element,
    now_chicago: datetime,
    now_utc: datetime,
) -> list[datetime]:
    """
    Expand one CalendarTrigger into fake-week Chicago datetimes.
    Handles ScheduleByWeek and ScheduleByDay (DaysInterval=1).
    Handles Repetition.
    Applies DST correction then converts to fake-week.

    Returns list of fake-week UTC datetimes.
    """
    if not _trigger_enabled(trigger):
        return []

    boundary_text = _text(trigger, "ts:StartBoundary")
    if not boundary_text:
        return []

    start_dt = _parse_start_boundary(boundary_text)
    if start_dt is None:
        return []

    # PS: skip trigger if EndBoundary < now
    end_text = _text(trigger, "ts:EndBoundary")
    if end_text:
        end_dt = _parse_start_boundary(end_text)
        if end_dt and end_dt < now_chicago:
            return []

    # PS: skip trigger if StartBoundary > 7 days from now
    if (start_dt - now_chicago).days > 7:
        return []

    # --- Determine day offsets ---
    day_offsets: list[int] = []

    schedule_week = trigger.find("ts:ScheduleByWeek", _NS)
    schedule_day = trigger.find("ts:ScheduleByDay", _NS)

    if schedule_week is not None:
        weeks_interval = _text(schedule_week, "ts:WeeksInterval")
        if weeks_interval and int(weeks_interval) > 1:
            return []  # PS: ignore non-weekly
        dow_node = schedule_week.find("ts:DaysOfWeek", _NS)
        if dow_node is not None:
            for day_name, offset in _XML_DAY_OFFSET.items():
                if dow_node.find(f"ts:{day_name}", _NS) is not None:
                    day_offsets.append(offset)

    elif schedule_day is not None:
        days_interval = _text(schedule_day, "ts:DaysInterval")
        if days_interval and int(days_interval) > 1:
            return []  # PS: ignore non-daily
        day_offsets = list(range(1, 8))  # all days

    else:
        return []  # not a calendar trigger we handle

    if not day_offsets:
        return []

    # --- Repetition ---
    repeat_count: Optional[int] = None
    interval_td: Optional[timedelta] = None
    rep_node = trigger.find("ts:Repetition", _NS)
    if rep_node is not None:
        interval_td = _iso_duration_to_timedelta(_text(rep_node, "ts:Interval"))
        duration_td = _iso_duration_to_timedelta(_text(rep_node, "ts:Duration"))
        if interval_td and duration_td and interval_td.total_seconds() > 0:
            repeat_count = int(duration_td.total_seconds() / interval_td.total_seconds())
            repeat_count = min(repeat_count, 100)  # PS safety cap

    # --- Build run times ---
    # The trigger StartBoundary is stored in CHICAGO LOCAL TIME.
    # We must build candidates in Chicago calendar space so that:
    #   1. The day-of-week matches the Chicago calendar (not UTC)
    #   2. DST transitions are applied correctly via pytz.normalize()
    #
    # BUG THAT WAS HERE: converting UTC-midnight Sunday to Chicago gives
    # Saturday 19:00 CDT (previous day!), so the baseline was wrong.
    # FIX: find this Sunday's DATE in the Chicago calendar, then build
    # Chicago midnight from that date — never cross through UTC midnight.

    time_of_day_chicago = start_dt.astimezone(CHICAGO_TZ)
    run_times: list[datetime] = []

    # Find this week's Saturday midnight in Chicago local time (1 day before Sunday).
    # We go back to Saturday so that tasks firing on Saturday before midnight
    # are included — their corresponding stop may fall within the display window.
    # The comparator treats any start before window_start() as "already running"
    # and opens a synthetic interval from window_start() to the first stop.
    chi_dow = now_chicago.weekday()                    # Mon=0…Sun=6
    days_since_chi_sun = (chi_dow + 1) % 7            # Sun=0, Mon=1…
    # Saturday = Sunday - 1 day
    chi_saturday_naive = (now_chicago - timedelta(days=days_since_chi_sun + 1)).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    week_saturday_chicago = CHICAGO_TZ.localize(chi_saturday_naive)
    # Keep week_sunday_chicago for reference (days_from_sun=0 means Sunday)
    chi_sunday_naive = (now_chicago - timedelta(days=days_since_chi_sun)).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    week_sunday_chicago = CHICAGO_TZ.localize(chi_sunday_naive)

    # day_offsets: days-from-Sunday (Sun=0 … Sat=6) from _XML_DAY_OFFSET
    #
    # Saturday (offset=6) needs special handling:
    #   We want the PRIOR Saturday (before this window's Sunday) so the comparator
    #   sees it as a pre-window start and correctly opens a synthetic interval from
    #   window_start(). We therefore do NOT call to_current_week() for Saturday —
    #   we use week_saturday_chicago directly and emit the raw UTC time.
    #
    # All other days: to_current_week() maps the candidate into the display window.

    from backend.logic.time_utils import window_start as _window_start
    win_start_utc = _window_start()

    for days_from_sun in day_offsets:
        if days_from_sun == 6:
            # Prior Saturday — place BEFORE the window so comparator treats it
            # as "already running at window open".
            candidate_naive = week_saturday_chicago.replace(tzinfo=None) + timedelta(
                hours=time_of_day_chicago.hour,
                minutes=time_of_day_chicago.minute,
                seconds=time_of_day_chicago.second,
            )
            candidate_chicago = CHICAGO_TZ.normalize(CHICAGO_TZ.localize(candidate_naive))
            candidate_utc = candidate_chicago.astimezone(UTC_TZ)
            # Emit as-is (pre-window) — do NOT remap via to_current_week()
            run_times.append(candidate_utc)
        else:
            candidate_naive = week_sunday_chicago.replace(tzinfo=None) + timedelta(
                days=days_from_sun,
                hours=time_of_day_chicago.hour,
                minutes=time_of_day_chicago.minute,
                seconds=time_of_day_chicago.second,
            )
            candidate_chicago = CHICAGO_TZ.normalize(CHICAGO_TZ.localize(candidate_naive))
            candidate_utc = candidate_chicago.astimezone(UTC_TZ)
            # Map into the display window (Sun=week1, Mon–Fri=week1, next Sat via clone)
            run_times.append(to_current_week(candidate_utc, reference=now_chicago))

        if repeat_count and interval_td:
            for i in range(1, repeat_count + 1):
                extra = candidate_utc + interval_td * i
                # Repetitions: keep relative to their base candidate
                if days_from_sun == 6:
                    run_times.append(extra)   # pre-window repetitions stay raw
                else:
                    run_times.append(to_current_week(extra, reference=now_chicago))

    return run_times


# ---------------------------------------------------------------------------
# Task classification
# ---------------------------------------------------------------------------

def _is_messenger_task(task_name: str) -> bool:
    return bool(_MSGR_PATTERN.search(task_name))


def _get_task_type(task_name: str) -> TaskType:
    """Last word of task name is 'Start' or 'Stop'."""
    last = task_name.strip().split()[-1].lower()
    return TaskType.START if last == "start" else TaskType.STOP


def _get_messenger_name(task_name: str) -> str:
    return _MSGR_NAME_STRIP.sub("", task_name).strip()


def _get_dst_flag(task_name: str) -> str:
    m = _DST_MSGR_PATTERN.search(task_name)
    if m and "_DST" in task_name:
        return m.group(1)
    return ""


def _box_included(
    box_name: str,
    exclude_patterns: list[re.Pattern],
    include_patterns: list[re.Pattern],
) -> bool:
    if include_patterns:
        return any(p.search(box_name) for p in include_patterns)
    if exclude_patterns:
        return not any(p.search(box_name) for p in exclude_patterns)
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Timeout (seconds) for each Samba network operation.
# Set WINDOWS_TASKS_TIMEOUT in .env to override.
import os as _os
_SMB_TIMEOUT = int(_os.environ.get("WINDOWS_TASKS_TIMEOUT", "60"))


def _list_box_dirs(snapshot_dir: Path) -> list[Path]:
    """List box subdirectories in the snapshot, filtering non-dirs immediately."""
    import os
    dirs = []
    logger.debug("Listing snapshot dir: %s", snapshot_dir)
    with os.scandir(snapshot_dir) as it:
        for entry in it:
            if entry.is_dir(follow_symlinks=False):
                dirs.append(Path(entry.path))
    logger.debug("Found %d box directories in snapshot", len(dirs))
    return sorted(dirs)


def load_messenger_tasks(
    archive_dir: Optional[Path] = None,
    is_stage: bool = False,
    timeout: int = _SMB_TIMEOUT,
) -> list[ScheduledTask]:
    """
    Walk the most-recent snapshot directory, find all
    [box]/Messengers/*.xml files, parse messenger tasks.

    Each Samba network operation is run with a timeout so a stalled
    share does not block the refresh indefinitely.

    Parameters
    ----------
    archive_dir : path to stasks_xml root (defaults to settings.task_archive_path)
    is_stage    : True → only stage boxes; False → exclude stage boxes
    timeout     : seconds to wait for each network operation (default 60)
    """
    if archive_dir is None:
        archive_dir = settings.task_archive_path_obj

    logger.debug("Finding latest snapshot in: %s", archive_dir)
    snapshot_dir = _find_latest_snapshot_dir(archive_dir)
    logger.info("Loading Windows tasks from snapshot: %s", snapshot_dir)

    now_chicago = datetime.now(CHICAGO_TZ)
    now_utc = datetime.now(UTC_TZ)

    exclude_patterns: list[re.Pattern] = []
    include_patterns: list[re.Pattern] = []
    if is_stage:
        include_patterns = [_STAGE_BOX_RE]
    else:
        exclude_patterns = [_STAGE_BOX_RE]

    tasks: list[ScheduledTask] = []

    # List box dirs with timeout — this is the first Samba round-trip
    logger.debug("Listing box directories (timeout=%ds)...", timeout)
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_list_box_dirs, snapshot_dir)
            box_dirs = future.result(timeout=timeout)
    except FutureTimeoutError:
        logger.error(
            "Timed out after %ds listing snapshot dir %s — "
            "check Samba connectivity. Set WINDOWS_TASKS_TIMEOUT in .env to increase.",
            timeout, snapshot_dir,
        )
        return []
    except Exception as exc:
        logger.error("Failed to list snapshot dir %s: %s", snapshot_dir, exc)
        return []

    logger.debug("Processing %d box directories", len(box_dirs))

    for box_dir in box_dirs:
        box_name = box_dir.name
        if not _box_included(box_name, exclude_patterns, include_patterns):
            continue

        # Only look inside the Messengers subfolder
        messengers_dir = box_dir / "Messengers"
        try:
            if not messengers_dir.is_dir():
                continue
        except OSError:
            logger.debug("Cannot access %s — skipping", messengers_dir)
            continue

        logger.debug("Scanning %s", messengers_dir)

        try:
            xml_files = list(messengers_dir.glob("*.xml"))
        except OSError as exc:
            logger.warning("Cannot list %s: %s", messengers_dir, exc)
            continue

        for xml_file in xml_files:
            task_name = xml_file.stem  # filename without .xml

            if not _is_messenger_task(task_name):
                continue

            try:
                tree = ET.parse(xml_file)
                root = tree.getroot()
            except ET.ParseError as exc:
                logger.warning("XML parse error in %s: %s", xml_file, exc)
                continue
            except OSError as exc:
                logger.warning("Cannot read %s: %s", xml_file, exc)
                continue

            if not _task_enabled(root):
                continue

            # Collect run times from all CalendarTriggers
            run_times: list[datetime] = []
            triggers_node = root.find("ts:Triggers", _NS)
            if triggers_node is not None:
                for trigger in triggers_node.findall("ts:CalendarTrigger", _NS):
                    run_times.extend(_expand_trigger(trigger, now_chicago, now_utc))

            if not run_times:
                logger.debug("No weekly run times in %s/%s", box_name, task_name)
                continue

            run_times.sort()

            # Clone run_times to week2 (with DST correction) for the 15-day window.
            # Each run_time is a single datetime (not a pair), so we treat each as
            # a zero-duration pair and take just the start of the cloned pair.
            week2_runs = [
                s for s, _ in clone_to_week2([(rt, rt) for rt in run_times])
            ]
            all_run_times = sorted(run_times + week2_runs)

            task_dir = "\\" + messengers_dir.relative_to(box_dir).as_posix()

            tasks.append(ScheduledTask(
                computer_name=box_name,
                name=task_name,
                directory=task_dir,
                weekly_run_times=all_run_times,
                messenger_name=_get_messenger_name(task_name),
                task_type=_get_task_type(task_name),
                enabled=True,
                source=TaskSource.WINDOWS,
                dst_flag=_get_dst_flag(task_name),
                xml_path=str(xml_file),
            ))

    logger.info(
        "Loaded %d messenger tasks from %d boxes in %s",
        len(tasks),
        len({t.computer_name for t in tasks}),
        snapshot_dir.name,
    )
    return tasks
