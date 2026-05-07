"""
config.py — Application settings loaded exclusively from .env / environment variables.

Nothing operator-editable (market group overrides, comments) lives here.
Those are stored in SQLite and managed via the UI.

Cross-platform notes
--------------------
TASK_ARCHIVE_PATH
  Linux:   /mnt/smb/dgwnas/archive/stasks_xml        (CIFS mount)
  Windows: \\\\dgwnas.cqginc.com\\Archive\\stasks_xml  (UNC path or mapped drive)

DB_DRIVER
  Linux:   ODBC Driver 18 for SQL Server   (msodbcsql18 package)
  Windows: ODBC Driver 18 for SQL Server   (same name after MSI install)
           SQL Server                      (inbox driver, older fallback)

All path handling in the app uses pathlib.Path so separators are automatic.
"""

from __future__ import annotations
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_archive_path() -> str:
    """Platform-appropriate default for the task XML archive path."""
    if sys.platform == "win32":
        return r"\\dgwnas.cqginc.com\Archive\stasks_xml"
    return "/mnt/smb/dgwnas/archive/stasks_xml"


def _default_db_driver() -> str:
    """
    On Windows the ODBC Driver 18 MSI registers under the same name as Linux.
    Fall back to the inbox 'SQL Server' driver only if 18 is not installed
    (detected at runtime in connection_string_for if needed).
    """
    return "ODBC Driver 18 for SQL Server"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Production database ──────────────────────────────────────────────────
    db_host: str
    db_name: str
    db_user: str
    db_password: str
    db_port: int = 1433
    db_driver: str = _default_db_driver()

    # ── Stage database ───────────────────────────────────────────────────────
    # Leave any field blank to inherit the prod value.
    stage_db_host: str = ""
    stage_db_name: str = ""
    stage_db_user: str = ""
    stage_db_password: str = ""
    stage_db_port: int = 0          # 0 = inherit prod port
    stage_db_driver: str = ""

    # ── Task XML archive ─────────────────────────────────────────────────────
    # Linux:   /mnt/smb/dgwnas/archive/stasks_xml
    # Windows: \\dgwnas.cqginc.com\Archive\stasks_xml  (or mapped drive, e.g. Z:\stasks_xml)
    task_archive_path: str = _default_archive_path()

    # ── GitLab ───────────────────────────────────────────────────────────────
    gitlab_url: str = "https://git.at.cqg"
    gitlab_token: str = ""
    gitlab_project: str = "inventory/gateway"
    gitlab_ref: str = "master"

    # ── Cache / SQLite ───────────────────────────────────────────────────────
    cache_dir: str = "./cache"
    refresh_interval_secs: int = 7200

    # ── Application ──────────────────────────────────────────────────────────
    app_env: str = "prod"
    log_level: str = "INFO"    # DEBUG | INFO | WARNING | ERROR

    # ── Helpers ─────────────────────────────────────────────────────────────

    def connection_string_for(self, env: str) -> str:
        """Return the pyodbc connection string for 'prod' or 'stage'."""
        if env == "stage":
            host   = self.stage_db_host     or self.db_host
            name   = self.stage_db_name     or self.db_name
            user   = self.stage_db_user     or self.db_user
            pwd    = self.stage_db_password or self.db_password
            port   = self.stage_db_port     or self.db_port
            driver = self.stage_db_driver   or self.db_driver
        else:
            host, name, user, pwd, port, driver = (
                self.db_host, self.db_name, self.db_user,
                self.db_password, self.db_port, self.db_driver,
            )
        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={host},{port};"
            f"DATABASE={name};"
            f"UID={user};"
            f"PWD={pwd};"
            "TrustServerCertificate=yes;"
            "Encrypt=yes;"
        )

    @property
    def task_archive_path_obj(self) -> Path:
        """task_archive_path as a pathlib.Path (handles both UNC and POSIX)."""
        return Path(self.task_archive_path)

    @property
    def cache_path(self) -> Path:
        return Path(self.cache_dir)

    @property
    def sqlite_path(self) -> Path:
        return self.cache_path / "config.db"

    @property
    def is_windows(self) -> bool:
        return sys.platform == "win32"

    @property
    def is_prod(self) -> bool:
        return self.app_env.casefold() == "prod"


settings = Settings()
