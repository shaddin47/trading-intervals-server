"""
API response schemas (Pydantic models serialised to JSON for the React frontend).

All times are ISO 8601 UTC strings.  The frontend does TZ conversion.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_serializer
from backend.models.domain import ConflictStatus, TaskSource


class IntervalOut(BaseModel):
    from_utc: datetime
    to_utc: datetime
    status: ConflictStatus
    start_xbit: Optional[str] = None
    stop_xbit: Optional[str] = None
    all_xbit: Optional[str] = None
    start_task: Optional[str] = None
    stop_task: Optional[str] = None
    computer_name: Optional[str] = None
    source: Optional[TaskSource] = None

    @field_serializer("from_utc", "to_utc")
    def serialize_dt(self, dt: datetime, _info) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class UptimeIntervalOut(BaseModel):
    from_utc: datetime
    to_utc: datetime
    start_task: str
    stop_task: str

    @field_serializer("from_utc", "to_utc")
    def serialize_dt(self, dt: datetime, _info) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class MessengerCoverageOut(BaseModel):
    computer_name: str
    uptime_intervals: list[UptimeIntervalOut]


class MarketGroupOut(BaseModel):
    market_group: str
    route_group_id: int
    ignored: bool
    comment: Optional[str]
    trading_intervals: list[IntervalOut]
    messenger_coverages: list[MessengerCoverageOut]


class StatusOut(BaseModel):
    last_updated_utc: Optional[str]
    is_stale: bool                    # True if cache is older than 3 hours
    environment: str                  # prod | stage
    task_archive_path: str
    windows_task_count: int
    linux_task_count: int
    market_group_count: int


class RefreshOut(BaseModel):
    started: bool
    message: str


class CommentIn(BaseModel):
    comment: str


class CommentOut(BaseModel):
    route_group_id: int
    market_group: str
    comment: Optional[str]


class MarketGroupConfigOut(BaseModel):
    route_group_id: int
    name: str
    task_name: Optional[str]
    exchange_keys_csv: Optional[str]
    ignore: bool
    comment: Optional[str]


class IgnoreToggleIn(BaseModel):
    ignore: bool
