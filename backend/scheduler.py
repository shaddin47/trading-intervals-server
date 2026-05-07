"""
scheduler.py — Background refresh + JSON cache management.

Each environment (prod/stage) has its own cache files:
  cache/prod/trading_intervals.json
  cache/prod/dataInfo.json
  cache/stage/trading_intervals.json
  cache/stage/dataInfo.json

Cross-platform note
-------------------
_write_atomic uses Path.replace() which is atomic on Linux/macOS.
On Windows, replace() raises PermissionError if the destination file
is open by another process (e.g. antivirus scan). The fallback writes
directly when replace() fails — acceptable since the scheduler runs
single-threaded per env (coalesce=True, max_instances=1).
"""

from __future__ import annotations
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backend.config import settings
from backend.data.linux_crons import load_linux_cron_tasks
from backend.data.market_groups import load_market_groups
from backend.data.trading_intervals import fetch_all_trading_intervals
from backend.data.windows_tasks import load_messenger_tasks, clear_snapshot_cache
from backend.logic.comparator import compare
from backend.models.domain import MarketGroupResult

logger = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {
    "prod": threading.Lock(),
    "stage": threading.Lock(),
}
_scheduler: Optional[BackgroundScheduler] = None

# Tracks whether a refresh is currently running per env
_refresh_running: dict[str, bool] = {}
_refresh_error: dict[str, str] = {}

INTERVALS_FILE = "trading_intervals.json"
DATA_INFO_FILE = "dataInfo.json"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_dir(env: str) -> Path:
    p = settings.cache_path / env
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_atomic(path: Path, content: str) -> None:
    """
    Write content to path as atomically as possible.
    On Linux/macOS: write to .tmp then rename (atomic).
    On Windows:     same approach; fall back to direct write if rename
                    fails due to a file lock (e.g. antivirus).
    """
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    try:
        tmp.replace(path)
    except PermissionError:
        # Windows fallback — direct overwrite
        logger.warning("Atomic replace failed for %s, writing directly", path)
        path.write_text(content, encoding="utf-8")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _serialise(results: list[MarketGroupResult]) -> str:
    def _default(obj):
        if isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%dT%H:%M:%SZ")
        raise TypeError(f"Not serialisable: {type(obj)}")
    return json.dumps(
        [r.model_dump(mode="json") for r in results],
        default=_default,
        indent=2,
    )


# ---------------------------------------------------------------------------
# Core refresh
# ---------------------------------------------------------------------------

def is_refresh_running(env: str) -> bool:
    return _refresh_running.get(env, False)


def set_refresh_running(env: str, running: bool) -> None:
    """
    Explicitly set the running flag for an env.
    Called by the request handler BEFORE starting the thread so the
    status endpoint reflects running=True immediately.
    """
    _refresh_running[env] = running


def last_refresh_error(env: str) -> str | None:
    return _refresh_error.get(env) or None


def run_refresh(env: Optional[str] = None) -> None:
    """Full data pipeline refresh for one environment."""
    if env is None:
        env = settings.app_env
    is_stage = env == "stage"

    # _refresh_running[env] is already True — set by the caller before
    # starting this thread to avoid a race with the status poll endpoint.
    # If called directly (e.g. from the scheduler), set it here.
    if not _refresh_running.get(env, False):
        _refresh_running[env] = True
    _refresh_error.pop(env, None)
    logger.info("Starting refresh for env=%s", env)
    started_at = datetime.now(timezone.utc)

    try:
        clear_snapshot_cache()  # ensure next run re-resolves the latest snapshot dir
        market_groups = load_market_groups(env)
        windows_tasks = load_messenger_tasks(is_stage=is_stage)
        linux_tasks   = load_linux_cron_tasks(is_stage=is_stage)
        all_tasks     = windows_tasks + linux_tasks

        intervals_map = fetch_all_trading_intervals(market_groups, env=env)

        results: list[MarketGroupResult] = []
        for mg in market_groups:
            if mg.ignore:
                # Skip compare entirely — no intervals were fetched for this group.
                # Still include it in the cache so the UI can show it as ignored.
                results.append(MarketGroupResult(
                    market_group=mg.name,
                    route_group_id=mg.route_group_id,
                    ignored=True,
                    comment=mg.comment,
                    trading_intervals=[],
                    messenger_coverages=[],
                ))
                continue
            result = compare(mg, intervals_map.get(mg.name, []), all_tasks)
            results.append(result)

        with _env_lock(env):
            cache = _cache_dir(env)
            _write_atomic(cache / INTERVALS_FILE, _serialise(results))
            _write_atomic(cache / DATA_INFO_FILE, json.dumps({
                "time": started_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "environment": env,
                "market_group_count": len(results),
                "windows_task_count": len(windows_tasks),
                "linux_task_count": len(linux_tasks),
            }, indent=2))

        completed_at = datetime.now(timezone.utc)
        elapsed = (completed_at - started_at).total_seconds()
        logger.info("Refresh for env=%s complete in %.1fs", env, elapsed)

        # Overwrite dataInfo with the completion timestamp (not start time)
        with _env_lock(env):
            _write_atomic(cache / DATA_INFO_FILE, json.dumps({
                "time": completed_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "environment": env,
                "market_group_count": len(results),
                "windows_task_count": len(windows_tasks),
                "linux_task_count": len(linux_tasks),
            }, indent=2))

    except Exception as exc:
        _refresh_error[env] = str(exc)
        logger.exception("Refresh failed for env=%s", env)
    finally:
        _refresh_running[env] = False


# ---------------------------------------------------------------------------
# Cache readers
# ---------------------------------------------------------------------------

def _env_lock(env: str) -> threading.Lock:
    """Always return the same lock for a given env — never create a throwaway."""
    return _locks.setdefault(env, threading.Lock())


def read_cache(env: str) -> list[dict]:
    f = _cache_dir(env) / INTERVALS_FILE
    with _env_lock(env):
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


def read_data_info(env: str) -> dict:
    f = _cache_dir(env) / DATA_INFO_FILE
    with _env_lock(env):
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def cache_is_stale(env: str) -> bool:
    f = _cache_dir(env) / DATA_INFO_FILE
    if not f.exists():
        return True
    age = (
        datetime.now(timezone.utc)
        - datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
    ).total_seconds()
    return age > settings.refresh_interval_secs * 3


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def start_scheduler() -> None:
    global _scheduler
    from backend.db.config_db import init_db
    init_db()

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_refresh,
        trigger=IntervalTrigger(seconds=settings.refresh_interval_secs),
        id="data_refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Scheduler started — refresh every %ds", settings.refresh_interval_secs)

    if cache_is_stale(settings.app_env):
        logger.info("Cache stale — running initial refresh for env=%s", settings.app_env)
        threading.Thread(
            target=run_refresh, args=(settings.app_env,), daemon=True
        ).start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
