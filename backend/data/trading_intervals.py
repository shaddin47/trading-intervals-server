"""
data/trading_intervals.py — Fetch trading intervals from SQL Server.

Calls dbo.RPT_OPS_RouteGroupTradingTimes per MarketGroup.

SP signature:
  @RouteGroupID                INT
  @ExchangeKeysCSV             VARCHAR(100) = NULL
  @ExchangeKeysTable           IntTableType READONLY   ← TVP, cannot use via pyodbc
  @ExchangeKeysFromViableRoutes BIT         = 0

pyodbc cannot pass TVPs. @ExchangeKeysTable is omitted entirely from
EXEC calls — passing it as NULL triggers a permission check on the
IntTableType UDTT even though the type is never used. Omitting it lets
the parameter default to NULL inside the SP with no permission check.
Priority follows SP logic: CSV > ViableRoutes > neither (all intervals).

Output columns: StartTime, StopTime, StartXbit, StopXbit, AllXbit
  StartTime / StopTime are DATETIME2(6) stored as UTC.
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional

import pyodbc

from backend.config import settings
from backend.logic.time_utils import to_utc, interval_to_current_week, clone_to_week2
from backend.models.domain import MarketGroupOverride, TradingInterval

logger = logging.getLogger(__name__)

SP_NAME = "dbo.RPT_OPS_RouteGroupTradingTimes"


def _build_exec(mg: MarketGroupOverride) -> tuple[str, list]:
    """
    Build the EXEC statement for RPT_OPS_RouteGroupTradingTimes.

    @ExchangeKeysTable (IntTableType TVP) is intentionally omitted from
    every call.  pyodbc cannot pass TVPs, but more importantly explicitly
    passing NULL forces SQL Server to validate EXECUTE permission on the
    user-defined table type at parse time — even though the type is never
    actually used.  Omitting the parameter entirely lets it default to
    NULL inside the SP without triggering the permission check.
    """
    params: list = [mg.route_group_id]
    if mg.exchange_keys_csv:
        sql = (
            f"EXEC {SP_NAME} @RouteGroupID=?, @ExchangeKeysCSV=?,"
            f" @ExchangeKeysFromViableRoutes=0"
        )
        params.append(mg.exchange_keys_csv)
    elif mg.exchange_keys_from_viable_routes:
        sql = (
            f"EXEC {SP_NAME} @RouteGroupID=?, @ExchangeKeysCSV=NULL,"
            f" @ExchangeKeysFromViableRoutes=1"
        )
    else:
        sql = (
            f"EXEC {SP_NAME} @RouteGroupID=?, @ExchangeKeysCSV=NULL,"
            f" @ExchangeKeysFromViableRoutes=0"
        )
    return sql, params


def _truncate_xbit(value, max_items: int = 10) -> Optional[str]:
    """
    Truncate a comma-separated xbit string to at most max_items values.
    Appends ',...' if truncated so the tooltip shows the list is incomplete.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    parts = [p.strip() for p in s.split(',') if p.strip()]
    if len(parts) <= max_items:
        return ','.join(parts)
    return ','.join(parts[:max_items]) + ',...'


def _row_to_interval(row) -> Optional[TradingInterval]:
    """
    Convert one SP result row to a TradingInterval.

    StartTime / StopTime are DATETIME2(6) fake-week dates stored in the DB
    (e.g. 1900-04-01 17:00:00 = Sunday 17:00 UTC).  We treat them as UTC
    and map them onto the current real-world week via to_current_week().
    """
    try:
        def _as_dt(v) -> datetime:
            return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))

        # SP stores fake-week dates (e.g. 1900-04-01 = Sunday).
        # Convert as a PAIR to preserve the start→stop relationship.
        # Converting independently can invert the interval when start and
        # stop fall on different sides of the current week boundary.
        start_fake = to_utc(_as_dt(row.StartTime))
        stop_fake  = to_utc(_as_dt(row.StopTime))
        start_real, stop_real = interval_to_current_week(start_fake, stop_fake)

        return TradingInterval(
            start_utc=start_real,
            stop_utc=stop_real,
            start_xbit=_truncate_xbit(row.StartXbit),
            stop_xbit=_truncate_xbit(row.StopXbit),
            all_xbit=_truncate_xbit(row.AllXbit),
        )
    except Exception as exc:
        logger.warning("Row conversion failed: %s", exc)
        return None


def fetch_trading_intervals(
    market_group: MarketGroupOverride,
    env: str = "prod",
) -> list[TradingInterval]:
    """
    Fetch intervals for one MarketGroup from the correct env DB.

    The SP returns one week of schedule data (fake-week dates).
    We clone each interval to the following week (with DST correction)
    to fill the 15-day display window (this Sunday → Monday +2 weeks).
    """
    sql, params = _build_exec(market_group)
    try:
        conn_str = settings.connection_string_for(env)
        with pyodbc.connect(conn_str, timeout=15) as conn:
            rows = conn.cursor().execute(sql, params).fetchall()
    except pyodbc.Error as exc:
        logger.error("DB error fetching intervals for %s (env=%s): %s", market_group.name, env, exc)
        raise

    week1 = [i for r in rows if (i := _row_to_interval(r)) is not None]

    # Clone week1 to week2 with DST adjustment
    week2_pairs = clone_to_week2([(i.start_utc, i.stop_utc) for i in week1])
    week2 = [
        TradingInterval(
            start_utc=s,
            stop_utc=e,
            start_xbit=week1[idx].start_xbit,
            stop_xbit=week1[idx].stop_xbit,
            all_xbit=week1[idx].all_xbit,
        )
        for idx, (s, e) in enumerate(week2_pairs)
    ]

    return week1 + week2


def fetch_all_trading_intervals(
    market_groups: list[MarketGroupOverride],
    env: str = "prod",
    skip_ignored: bool = True,
    max_workers: int = 10,
) -> dict[str, list[TradingInterval]]:
    """
    Fetch trading intervals for all market groups in parallel.

    Uses a ThreadPoolExecutor so 130+ market groups don't require 130
    sequential SQL round-trips. Each worker opens its own pyodbc connection
    (pyodbc connections are not thread-safe to share).

    max_workers=10 is a safe default — most SQL Server deployments handle
    10 concurrent connections from a single app without contention.
    Adjust via the caller if the DB has connection limits.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Partition into ignored (skip) and active (fetch)
    to_fetch = [mg for mg in market_groups if not (skip_ignored and mg.ignore)]
    results: dict[str, list[TradingInterval]] = {
        mg.name: [] for mg in market_groups if skip_ignored and mg.ignore
    }

    if not to_fetch:
        return results

    def _fetch(mg: MarketGroupOverride):
        try:
            return mg.name, fetch_trading_intervals(mg, env)
        except Exception as exc:
            logger.exception("Failed fetching intervals for %s", mg.name)
            return mg.name, []

    workers = min(max_workers, len(to_fetch))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sp-fetch") as ex:
        futures = {ex.submit(_fetch, mg): mg for mg in to_fetch}
        for future in as_completed(futures):
            name, intervals = future.result()
            results[name] = intervals

    return results
