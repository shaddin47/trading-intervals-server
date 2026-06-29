"""
Domain models for the Trading Intervals Monitor.

All datetimes in this layer are stored as UTC-aware datetime objects.
All datetimes use real current-week UTC dates, mapped by time_utils.to_current_week().
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TaskSource(str, Enum):
    WINDOWS = "windows"
    LINUX = "linux"


class TaskType(str, Enum):
    START = "Start"
    STOP = "Stop"


class ConflictStatus(str, Enum):
    OK = "OK"           # Messenger schedule fully covers the trading interval
    PARTIAL = "PARTIAL" # Schedule overlaps but starts >1 s late or stops >1 min early
    CONFLICT = "CONFLICT"  # No messenger schedule covers this interval at all


# ---------------------------------------------------------------------------
# Market Group configuration (from YAML overrides + SQL base list)
# ---------------------------------------------------------------------------

class MarketGroupOverride(BaseModel):
    """
    Single display row within a RouteGroupID.
    One RouteGroupID can produce multiple display rows (e.g. ICE UK, ICE ENDEX,
    ICE US all share RouteGroupID=5 but differ by ExchangeKeysCSV).
    """
    name: str
    route_group_id: int
    exchange_keys_csv: Optional[str] = None          # e.g. "27,509"
    exchange_keys_from_viable_routes: bool = False
    task_name: Optional[str] = None                  # semicolon-separated aliases
    ignore: bool = False
    comment: Optional[str] = None                    # shown in tooltip

    @property
    def task_name_list(self) -> list[str]:
        """
        Split semicolon-delimited TaskName into individual alias tokens.
        Returns lowercase strings — comparisons against task names are
        always case-insensitive (task XML and cron names vary in casing).
        Falls back to the market group name (also lowercased) if no
        task_name override is configured.
        """
        if not self.task_name:
            return [self.name.lower()]
        return [t.strip().lower() for t in self.task_name.split(";") if t.strip()]


# ---------------------------------------------------------------------------
# Trading intervals (from SQL SP)
# ---------------------------------------------------------------------------

class TradingInterval(BaseModel):
    """
    A single start/stop window as returned by RPT_OPS_RouteGroupTradingTimes.
    Times are UTC-aware.
    """
    start_utc: datetime
    stop_utc: datetime
    start_xbit: Optional[str] = None
    stop_xbit: Optional[str] = None
    all_xbit: Optional[str] = None


# ---------------------------------------------------------------------------
# Scheduled tasks (Windows XML + Linux cron — unified schema)
# ---------------------------------------------------------------------------

class ScheduledTask(BaseModel):
    """
    A messenger task from either a Windows Task Scheduler XML archive or a
    Linux cron YAML inventory.  WeeklyRunTimes are normalised to fake-week
    UTC datetimes before being stored here.
    """
    computer_name: str                # box name, e.g. "prod_ch2l_msg"
    name: str                         # task name
    directory: str                    # subfolder path or YAML filename
    weekly_run_times: list[datetime]  # sorted fake-week UTC datetimes
    messenger_name: str               # derived from task name
    task_type: TaskType
    enabled: bool
    source: TaskSource
    dst_flag: str = ""                # DST annotation from original PS logic
    xml_path: Optional[str] = None   # Windows only — source file for debugging


# ---------------------------------------------------------------------------
# Comparator output
# ---------------------------------------------------------------------------

class UptimeInterval(BaseModel):
    """
    A resolved uptime window for one messenger box, derived by pairing
    consecutive Start/Stop tasks from WeeklyRunTimes.

    status reflects how well this uptime covers its overlapping trading intervals:
      OK      — fully covers every trading interval it overlaps
      PARTIAL — covers at least one but with late start or early stop
      CONFLICT — does not overlap any trading interval
    Set by comparator.compare() after uptime derivation.
    """
    from_utc: datetime
    to_utc: datetime
    start_task: str
    stop_task: str
    status: ConflictStatus = ConflictStatus.OK


class MessengerCoverage(BaseModel):
    """All uptime intervals for a single gateway box."""
    computer_name: str
    uptime_intervals: list[UptimeInterval]


class EvaluatedInterval(BaseModel):
    """
    A trading interval after conflict analysis.
    from_utc / to_utc are fake-week UTC datetimes.
    """
    from_utc: datetime
    to_utc: datetime
    status: ConflictStatus
    coverage: ConflictStatus = ConflictStatus.OK
    start_xbit: Optional[str] = None
    stop_xbit: Optional[str] = None
    all_xbit: Optional[str] = None
    start_task: Optional[str] = None
    stop_task: Optional[str] = None
    computer_name: Optional[str] = None
    source: Optional[TaskSource] = None


class MarketGroupResult(BaseModel):
    """
    Final output for one display row (market group + optional exchange filter).
    Contains both the evaluated trading intervals and per-box task rows.
    """
    market_group: str
    route_group_id: int
    ignored: bool
    comment: Optional[str]
    # Trading interval row
    trading_intervals: list[EvaluatedInterval]
    # One entry per messenger box (computer_name)
    messenger_coverages: list[MessengerCoverage]
