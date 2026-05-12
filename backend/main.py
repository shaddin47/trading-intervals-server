"""
main.py — FastAPI application.

One app instance serves both prod and stage data.
All endpoints accept ?env=prod (default) or ?env=stage.

DB credentials come from .env only — never from SQLite.
SQLite stores only market group overrides and comments (operator-editable via UI).

Routes
------
Data
  GET  /api/intervals                     Gantt payload
  GET  /api/intervals/{route_group_id}    Single group

Config (SQLite — UI editable)
  GET    /api/config/market-groups            List override rows
  POST   /api/config/market-groups            Create / upsert a row
  PUT    /api/config/market-groups/{id}       Partial update (ignore, comment, etc.)
  DELETE /api/config/market-groups/{id}/{name}  Remove a row

Admin
  GET   /api/status          Cache freshness + stats
  POST  /api/admin/refresh   Force data refresh
  POST  /api/admin/migrate-yaml  One-time YAML → SQLite migration
"""

from __future__ import annotations
import logging
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import scheduler as sched
from backend.scheduler import is_refresh_running, last_refresh_error
from backend.config import settings
from backend.db import config_db

# Log level is read from settings (populated from .env LOG_LEVEL=DEBUG etc.)
_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
# Keep noisy third-party loggers at WARNING regardless of LOG_LEVEL
for _noisy in ("uvicorn.access", "apscheduler", "urllib3", "urllib"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

EnvLiteral = Literal["prod", "stage"]


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class IntervalOut(BaseModel):
    from_utc: str
    to_utc: str
    status: str
    start_xbit: Optional[str] = None
    stop_xbit: Optional[str] = None
    all_xbit: Optional[str] = None
    start_task: Optional[str] = None
    stop_task: Optional[str] = None
    computer_name: Optional[str] = None
    source: Optional[str] = None


class UptimeIntervalOut(BaseModel):
    from_utc: str
    to_utc: str
    start_task: str
    stop_task: str


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


class MarketGroupConfigOut(BaseModel):
    env: str
    route_group_id: int
    name: str
    task_name: Optional[str]
    exchange_keys_csv: Optional[str]
    exchange_keys_from_viable_routes: bool
    ignore: bool
    comment: Optional[str]


class MarketGroupUpsertIn(BaseModel):
    env: EnvLiteral
    route_group_id: int
    name: str
    task_name: Optional[str] = None
    exchange_keys_csv: Optional[str] = None
    exchange_keys_from_viable_routes: bool = False
    ignore: bool = False
    comment: Optional[str] = None


class MarketGroupPatchIn(BaseModel):
    name: Optional[str] = None
    task_name: Optional[str] = None
    exchange_keys_csv: Optional[str] = None
    exchange_keys_from_viable_routes: Optional[bool] = None
    ignore: Optional[bool] = None
    comment: Optional[str] = None


class StatusOut(BaseModel):
    env: str
    last_updated_utc: Optional[str]
    is_stale: bool
    task_archive_path: str
    windows_task_count: int
    linux_task_count: int
    market_group_count: int


class RefreshOut(BaseModel):
    started: bool
    env: str
    message: str

class RefreshStatusOut(BaseModel):
    env: str
    running: bool
    error: Optional[str]
    last_updated_utc: Optional[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(dt) -> str:
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(dt)


def _raw_to_out(raw: dict) -> MarketGroupOut:
    def _iv(i: dict) -> IntervalOut:
        return IntervalOut(
            from_utc=_fmt(i["from_utc"]), to_utc=_fmt(i["to_utc"]),
            status=i["status"],
            start_xbit=i.get("start_xbit"), stop_xbit=i.get("stop_xbit"),
            all_xbit=i.get("all_xbit"),
            start_task=i.get("start_task"), stop_task=i.get("stop_task"),
            computer_name=i.get("computer_name"), source=i.get("source"),
        )

    def _cv(c: dict) -> MessengerCoverageOut:
        return MessengerCoverageOut(
            computer_name=c["computer_name"],
            uptime_intervals=[
                UptimeIntervalOut(
                    from_utc=_fmt(u["from_utc"]), to_utc=_fmt(u["to_utc"]),
                    start_task=u["start_task"], stop_task=u["stop_task"],
                )
                for u in c.get("uptime_intervals", [])
            ],
        )

    return MarketGroupOut(
        market_group=raw["market_group"],
        route_group_id=raw["route_group_id"],
        ignored=raw.get("ignored", False),
        comment=raw.get("comment"),
        trading_intervals=[_iv(i) for i in raw.get("trading_intervals", [])],
        messenger_coverages=[_cv(c) for c in raw.get("messenger_coverages", [])],
    )


def _row_to_config(r: dict) -> MarketGroupConfigOut:
    return MarketGroupConfigOut(
        env=r["env"],
        route_group_id=r["route_group_id"],
        name=r["name"],
        task_name=r.get("task_name"),
        exchange_keys_csv=r.get("exchange_keys_csv"),
        exchange_keys_from_viable_routes=bool(r.get("exchange_keys_from_viable_routes", 0)),
        ignore=bool(r.get("ignore", 0)),
        comment=r.get("comment"),
    )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    config_db.init_db()
    sched.start_scheduler()
    yield
    sched.stop_scheduler()


app = FastAPI(
    title="Trading Intervals Monitor",
    version="2.0.0",
    description=(
        "Compares DB Order Routing Times against Windows/Linux messenger schedules. "
        "Supports prod and stage environments via ?env= query parameter."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # tighten to frontend origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Data endpoints
# ---------------------------------------------------------------------------

@app.get("/api/intervals", response_model=list[MarketGroupOut], tags=["Intervals"])
def get_intervals(
    env: EnvLiteral = Query("prod", description="Environment to query"),
    market_group: Optional[str] = Query(None, description="Partial name filter"),
    include_ignored: bool = Query(False, description="Include rows marked as ignored"),
):
    """Main Gantt payload — all market groups with evaluated intervals and coverage."""
    raw_list = sched.read_cache(env)
    results = []
    for raw in raw_list:
        if not include_ignored and raw.get("ignored"):
            continue
        if market_group and market_group.lower() not in raw["market_group"].lower():
            continue
        results.append(_raw_to_out(raw))
    return results


@app.get("/api/intervals/{route_group_id}", response_model=list[MarketGroupOut], tags=["Intervals"])
def get_intervals_by_id(
    route_group_id: int,
    env: EnvLiteral = Query("prod"),
):
    """All display rows for a specific RouteGroupID."""
    raw_list = sched.read_cache(env)
    results = [_raw_to_out(r) for r in raw_list if r["route_group_id"] == route_group_id]
    if not results:
        raise HTTPException(404, f"RouteGroupID {route_group_id} not found in env={env}")
    return results


# ---------------------------------------------------------------------------
# Config endpoints (SQLite — UI editable)
# ---------------------------------------------------------------------------

@app.get("/api/config/market-groups", response_model=list[MarketGroupConfigOut], tags=["Config"])
def list_configs(env: EnvLiteral = Query("prod")):
    """List all market group override rows for the given environment."""
    return [_row_to_config(r) for r in config_db.get_all_overrides(env)]


@app.post("/api/config/market-groups", response_model=MarketGroupConfigOut, tags=["Config"])
def upsert_config(body: MarketGroupUpsertIn):
    """Create or fully replace a market group override row."""
    config_db.upsert_override(
        env=body.env,
        route_group_id=body.route_group_id,
        name=body.name,
        task_name=body.task_name,
        exchange_keys_csv=body.exchange_keys_csv,
        exchange_keys_from_viable_routes=body.exchange_keys_from_viable_routes,
        ignore=body.ignore,
        comment=body.comment,
    )
    return MarketGroupConfigOut(**body.model_dump())


@app.put(
    "/api/config/market-groups/{route_group_id}",
    response_model=MarketGroupConfigOut,
    tags=["Config"],
)
def patch_config(
    route_group_id: int,
    name: str = Query(..., description="Display row name"),
    env: EnvLiteral = Query("prod"),
    body: MarketGroupPatchIn = ...,
):
    """
    Partial update — only supplied fields are changed.
    Typical uses: toggling ignore, updating a comment, changing task aliases.
    """
    # exclude_unset=True: only fields the client sent are included.
    # We keep None values so clearing a field (e.g. task_name="") writes NULL.
    updates = body.model_dump(exclude_unset=True)
    new_name = updates.pop("name", None)
    config_db.patch_override(env, route_group_id, name, new_name=new_name, **updates)
    effective_name = new_name if new_name else name
    rows = config_db.get_overrides_for_group(env, route_group_id)
    row = next((r for r in rows if r["name"] == effective_name), None)
    if not row:
        raise HTTPException(404, "Row not found after patch")
    return _row_to_config(row)


@app.delete(
    "/api/config/market-groups/{route_group_id}/{name}",
    tags=["Config"],
)
def delete_config(
    route_group_id: int,
    name: str,
    env: EnvLiteral = Query("prod"),
):
    """Remove an override row — the group reverts to its plain DB name with no customisation."""
    config_db.delete_override(env, route_group_id, name)
    return {"deleted": True, "route_group_id": route_group_id, "name": name, "env": env}


# ---------------------------------------------------------------------------
# Admin / status
# ---------------------------------------------------------------------------

@app.get("/api/status", response_model=list[StatusOut], tags=["Admin"])
def get_status(env: Optional[EnvLiteral] = Query(None, description="Omit for both envs")):
    """Cache freshness and data statistics. Returns one entry per environment."""
    envs: list[str] = [env] if env else ["prod", "stage"]
    result = []
    for e in envs:
        info = sched.read_data_info(e)
        result.append(StatusOut(
            env=e,
            last_updated_utc=info.get("time"),
            is_stale=sched.cache_is_stale(e),
            task_archive_path=settings.task_archive_path,
            windows_task_count=info.get("windows_task_count", 0),
            linux_task_count=info.get("linux_task_count", 0),
            market_group_count=info.get("market_group_count", 0),
        ))
    return result


@app.post("/api/admin/refresh", response_model=RefreshOut, tags=["Admin"])
def trigger_refresh(env: EnvLiteral = Query("prod")):
    """
    Trigger an immediate data refresh for the given environment.
    Returns immediately — poll GET /api/admin/refresh-status to check completion.

    _refresh_running is set to True here (in the request thread) BEFORE
    starting the background thread, so the status endpoint always returns
    running=True immediately after this call returns.
    """
    if is_refresh_running(env):
        return RefreshOut(
            started=False, env=env,
            message=f"Refresh already running for env={env}.",
        )

    # Mark running BEFORE thread starts — prevents a race where the first
    # poll fires before the thread executes its first line.
    sched.set_refresh_running(env, running=True)

    def _run():
        try:
            sched.run_refresh(env)
        except Exception as exc:
            # run_refresh logs and stores the error itself; we just
            # ensure the thread exits cleanly without an unhandled exception.
            logger.error("Refresh thread for env=%s exited with error: %s", env, exc)

    threading.Thread(target=_run, daemon=True, name=f"refresh-{env}").start()
    return RefreshOut(
        started=True, env=env,
        message=f"Refresh started for env={env}. Poll /api/admin/refresh-status?env={env}.",
    )


@app.get("/api/admin/refresh-status", response_model=RefreshStatusOut, tags=["Admin"])
def get_refresh_status(env: EnvLiteral = Query("prod")):
    """
    Poll this endpoint to check if a refresh is still running.
    running=false + no error means the refresh completed successfully.
    """
    info = sched.read_data_info(env)
    return RefreshStatusOut(
        env=env,
        running=is_refresh_running(env),
        error=last_refresh_error(env),
        last_updated_utc=info.get("time"),
    )


@app.post("/api/admin/migrate-yaml", tags=["Admin"])
def migrate_yaml(
    yaml_path: str = Query(default="./config/market_groups.yaml"),
    env: EnvLiteral = Query("prod"),
):
    """
    One-time migration from the legacy market_groups.yaml to SQLite.
    Safe to run multiple times — existing rows are skipped.
    """
    inserted = config_db.bulk_seed_from_yaml(yaml_path, env)
    return {"inserted": inserted, "yaml_path": yaml_path, "env": env}


# ── Serve built React frontend ───────────────────────────────────────────────
# Mount static files LAST so all /api/* routes take priority.
# Only activates when frontend/dist exists (i.e. after `npm run build`).
# In development, run `npm run dev` separately (Vite dev server on port 3000).
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="static")
    logger.info("Serving frontend from %s", _FRONTEND_DIST)
else:
    logger.info(
        "Frontend dist not found at %s — API-only mode. "
        "Run `cd frontend && npm run build` to enable the UI.",
        _FRONTEND_DIST,
    )
