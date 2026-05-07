"""
data/market_groups.py — Build the MarketGroupOverride list.

Two sources merged:
  1. SQL Server RouteGroup table  → authoritative ID + Name list (per env DB)
  2. SQLite market_group_config   → operator overrides: task aliases, exchange
                                    key filters, ignore flag, comment

If a RouteGroupID has SQLite overrides, those rows are used (one display row
per override entry — supports multiple rows per RouteGroupID, e.g. ICE UK /
ICE ENDEX / ICE US all sharing RouteGroupID 5).

If a RouteGroupID has no override at all, a single default row is created
from the DB name with no customisation.
"""

from __future__ import annotations
import logging
from typing import Optional

import pyodbc

from backend.config import settings
from backend.db import config_db
from backend.models.domain import MarketGroupOverride

logger = logging.getLogger(__name__)


def _fetch_route_groups(env: str) -> dict[int, str]:
    """Return {route_group_id: name} from SQL Server for the given environment."""
    conn_str = settings.connection_string_for(env)
    try:
        with pyodbc.connect(conn_str, timeout=10) as conn:
            rows = conn.cursor().execute(
                "SELECT ID, RTRIM(Name) AS Name FROM RouteGroup "
            "WHERE Name NOT LIKE 'UNUSED%' "
            "AND NOT (ExecSysType IN (999, 0) AND FixCarryFirmRequired = 1) "
            "ORDER BY ID"
            ).fetchall()
            return {int(r.ID): r.Name for r in rows}
    except Exception:
        logger.exception("Failed to fetch RouteGroup list (env=%s)", env)
        raise


def load_market_groups(env: Optional[str] = None) -> list[MarketGroupOverride]:
    """
    Return the full display-row list for the given environment.
    env defaults to settings.app_env.
    """
    if env is None:
        env = settings.app_env

    db_groups = _fetch_route_groups(env)
    overrides = config_db.get_all_overrides(env)

    # Index SQLite overrides by route_group_id
    by_id: dict[int, list[dict]] = {}
    for row in overrides:
        by_id.setdefault(row["route_group_id"], []).append(row)

    result: list[MarketGroupOverride] = []
    for rgid, db_name in db_groups.items():
        entries = by_id.get(rgid)
        if entries:
            for e in entries:
                result.append(MarketGroupOverride(
                    name=e["name"],
                    route_group_id=rgid,
                    exchange_keys_csv=e.get("exchange_keys_csv"),
                    exchange_keys_from_viable_routes=bool(e.get("exchange_keys_from_viable_routes", 0)),
                    task_name=e.get("task_name"),
                    ignore=bool(e.get("ignore", 0)),
                    comment=e.get("comment"),
                ))
        else:
            result.append(MarketGroupOverride(name=db_name, route_group_id=rgid))

    logger.info("Loaded %d market group rows for env=%s", len(result), env)
    return result
