"""
db/config_db.py — SQLite config store.

Stores ONLY what operators edit via the UI:
  - market_group_config : per-env display row overrides (task aliases,
                          exchange key filters, ignore flag, comment)

Database credentials and all other app settings live in .env / config.py.

Schema
------
market_group_config
  env                              TEXT     'prod' | 'stage'
  route_group_id                   INTEGER
  name                             TEXT     display row label
  task_name                        TEXT     semicolon-separated task aliases (nullable)
  exchange_keys_csv                TEXT     comma-separated exchange keys (nullable)
  exchange_keys_from_viable_routes INTEGER  0 | 1
  ignore                           INTEGER  0 | 1
  comment                          TEXT     tooltip comment (nullable)
  PRIMARY KEY (env, route_group_id, name)
"""

from __future__ import annotations
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from backend.config import settings

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_group_config (
    env                              TEXT    NOT NULL,
    route_group_id                   INTEGER NOT NULL,
    name                             TEXT    NOT NULL,
    task_name                        TEXT,
    exchange_keys_csv                TEXT,
    exchange_keys_from_viable_routes INTEGER NOT NULL DEFAULT 0,
    ignore                           INTEGER NOT NULL DEFAULT 0,
    comment                          TEXT,
    PRIMARY KEY (env, route_group_id, name)
);
"""


@contextmanager
def _conn():
    db_path = settings.sqlite_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    """Create tables if they don't exist. Called once at app startup."""
    with _conn() as con:
        con.executescript(_SCHEMA)
    logger.info("Config DB ready at %s", settings.sqlite_path)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_all_overrides(env: str) -> list[dict]:
    """All override rows for the given environment, ordered by route_group_id, name."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM market_group_config WHERE env=? ORDER BY route_group_id, name",
            (env,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_overrides_for_group(env: str, route_group_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM market_group_config WHERE env=? AND route_group_id=?",
            (env, route_group_id),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def upsert_override(
    env: str,
    route_group_id: int,
    name: str,
    *,
    task_name: Optional[str] = None,
    exchange_keys_csv: Optional[str] = None,
    exchange_keys_from_viable_routes: bool = False,
    ignore: bool = False,
    comment: Optional[str] = None,
) -> None:
    """Insert or fully replace a market group override row."""
    with _conn() as con:
        con.execute(
            """INSERT INTO market_group_config
               (env, route_group_id, name, task_name, exchange_keys_csv,
                exchange_keys_from_viable_routes, ignore, comment)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(env, route_group_id, name) DO UPDATE SET
                 task_name=excluded.task_name,
                 exchange_keys_csv=excluded.exchange_keys_csv,
                 exchange_keys_from_viable_routes=excluded.exchange_keys_from_viable_routes,
                 ignore=excluded.ignore,
                 comment=excluded.comment""",
            (
                env, route_group_id, name, task_name, exchange_keys_csv,
                int(exchange_keys_from_viable_routes), int(ignore), comment,
            ),
        )


def rename_override(env: str, route_group_id: int, old_name: str, new_name: str) -> None:
    """
    Rename a config row. Since `name` is part of the PK we use an atomic
    UPDATE — SQLite allows updating PK columns directly.
    """
    with _conn() as con:
        con.execute(
            "UPDATE market_group_config SET name=? "
            "WHERE env=? AND route_group_id=? AND name=?",
            (new_name, env, route_group_id, old_name),
        )


def patch_override(env: str, route_group_id: int, name: str, new_name: Optional[str] = None, **kwargs) -> None:
    """
    Partial update — only fields present in kwargs are written.
    Valid fields: task_name, exchange_keys_csv,
                  exchange_keys_from_viable_routes, ignore, comment.
    Pass new_name to rename the row (name is part of the PK).
    """
    if new_name and new_name != name:
        rename_override(env, route_group_id, name, new_name)
        name = new_name

    allowed = {
        "task_name", "exchange_keys_csv",
        "exchange_keys_from_viable_routes", "ignore", "comment",
    }
    # Keep None values — they write NULL to clear a field.
    # Only exclude keys not in the allowed set.
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    for bool_col in ("ignore", "exchange_keys_from_viable_routes"):
        if bool_col in updates and updates[bool_col] is not None:
            updates[bool_col] = int(updates[bool_col])
    cols = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [env, route_group_id, name]
    with _conn() as con:
        con.execute(
            f"UPDATE market_group_config SET {cols} "
            f"WHERE env=? AND route_group_id=? AND name=?",
            vals,
        )


def delete_override(env: str, route_group_id: int, name: str) -> None:
    with _conn() as con:
        con.execute(
            "DELETE FROM market_group_config WHERE env=? AND route_group_id=? AND name=?",
            (env, route_group_id, name),
        )


# ---------------------------------------------------------------------------
# One-time YAML migration helper
# ---------------------------------------------------------------------------

def seed_missing_groups(rows: list[tuple[str, int, str]]) -> None:
    """
    Insert (env, route_group_id, name) rows that don't yet exist in SQLite.
    All other columns are left as their DEFAULT values (nulls / 0).
    Uses INSERT OR IGNORE so existing rows are never modified.

    rows: list of (env, route_group_id, name)
    """
    with _conn() as con:
        con.executemany(
            """INSERT OR IGNORE INTO market_group_config
               (env, route_group_id, name)
               VALUES (?, ?, ?)""",
            rows,
        )


def bulk_seed_from_yaml(yaml_path: str, env: str = "prod") -> int:
    """
    Seed the DB from the legacy market_groups.yaml.
    Safe to run multiple times — uses INSERT OR IGNORE so existing rows
    are silently skipped without raising IntegrityError.
    Returns the count of rows newly inserted.
    """
    import yaml

    path = Path(yaml_path)
    if not path.exists():
        logger.warning("YAML not found at %s", path)
        return 0

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    # Build all rows first, then insert in a single transaction.
    # INSERT OR IGNORE handles duplicates atomically — no TOCTOU race.
    rows = []
    for block in data.get("overrides", []):
        rgid = int(block["route_group_id"])
        for entry in block.get("entries", []):
            rows.append((
                env, rgid, entry.get("name"),
                entry.get("task_name"),
                entry.get("exchange_keys_csv"),
                int(entry.get("exchange_keys_from_viable_routes", False)),
                int(entry.get("ignore", False)),
                entry.get("comment"),
            ))

    if not rows:
        logger.warning("No override entries found in %s", path)
        return 0

    with _conn() as con:
        result = con.executemany(
            """INSERT OR IGNORE INTO market_group_config
               (env, route_group_id, name, task_name, exchange_keys_csv,
                exchange_keys_from_viable_routes, ignore, comment)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
        inserted = result.rowcount

    logger.info("Migrated %d/%d rows from %s → env=%s", inserted, len(rows), yaml_path, env)
    return inserted
