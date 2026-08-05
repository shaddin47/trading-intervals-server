"""
linux_crons.py — Parse Linux messenger cron schedules from GitLab YAML inventory.

Directly incorporates the logic from GetLinuxMsgrCronInfo.py, removing the
PowerShell subprocess call and integrating it as a native Python module.

GitLab inventory files:
  prod_ch2l_msg.yml, prod_ch3l_msg.yml, prod_ch3l_simmsg.yml, ...
  stage_ch3l_msg.yml, stage_ch5l_msg.yml, ...

YAML structure:
  vars:
    gw_messengers:
      <msgr_type>:
        cron_groups:
          <group_name>:
            cron_tz: "America/Chicago"   # optional, defaults to Chicago
            cron_start:
              cron_tz: ...              # optional override
              expression:
                - "0 17 * * 0"
            cron_stop:
              expression:
                - "30 16 * * 5"
"""

from __future__ import annotations
import logging
import ssl
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

import pytz
import yaml
from croniter import croniter_range

try:
    import gitlab
    _GITLAB_AVAILABLE = True
except ImportError:
    _GITLAB_AVAILABLE = False

from backend.config import settings
from backend.logic.time_utils import (
    CHICAGO_TZ, UTC_TZ,
    window_start, window_end,
)
from backend.models.domain import ScheduledTask, TaskSource, TaskType

logger = logging.getLogger(__name__)

_DEFAULT_TZ = "America/Chicago"
# EOW sentinel removed — crons are now evaluated over the full 15-day window directly.


# ---------------------------------------------------------------------------
# YAML !vault tag handler (stub — matches existing behaviour)
# ---------------------------------------------------------------------------

def _vault_constructor(loader, node):
    """
    Stub vault decryptor — Ansible Vault encryption is not supported.
    Returns an empty string and logs a warning so operators know the value
    was not decrypted rather than silently returning garbage data.
    """
    logger.warning(
        "Ansible Vault-encrypted value encountered in YAML inventory — "
        "decryption is not supported. The field will be empty. "
        "Ensure vault-encrypted fields are not required for cron schedule parsing."
    )
    return ""


yaml.SafeLoader.add_constructor("!vault", _vault_constructor)


# ---------------------------------------------------------------------------
# GitLab inventory file discovery
# ---------------------------------------------------------------------------

def _discover_inventory_urls(env: str) -> list[str]:
    """
    Use the GitLab API to discover all *l_msg.yml / *l_simmsg.yml files for
    the given environment.  Falls back to a hardcoded list if unavailable.
    """
    urls: list[str] = []

    if _GITLAB_AVAILABLE and settings.gitlab_token:
        try:
            gl = gitlab.Gitlab(
                settings.gitlab_url,
                private_token=settings.gitlab_token,
                ssl_verify=False,
            )
            project = gl.projects.get(settings.gitlab_project)
            items = project.repository_tree(
                ref=settings.gitlab_ref, all=True, recursive=False
            )
            urls = [
                f"{settings.gitlab_url}/{settings.gitlab_project}/-/raw/{settings.gitlab_ref}/{f['path']}"
                for f in items
                if f.get("path", "").casefold().startswith(env)
                and f.get("path", "").casefold().endswith(("l_msg.yml", "l_simmsg.yml","l_msg2.yml"))
            ]
        except Exception:
            logger.exception("GitLab API unavailable; using fallback URL list")

    if not urls:
        logger.warning("Using hardcoded fallback inventory URLs for env=%s", env)
        if env == "prod":
            urls = [
                f"{settings.gitlab_url}/inventory/gateway/-/raw/master/prod_ch2l_msg.yml",
                f"{settings.gitlab_url}/inventory/gateway/-/raw/master/prod_ch3l_msg.yml",
                f"{settings.gitlab_url}/inventory/gateway/-/raw/master/prod_ch3l_msg2.yml",
                f"{settings.gitlab_url}/inventory/gateway/-/raw/master/prod_ch3l_simmsg.yml",
                f"{settings.gitlab_url}/inventory/gateway/-/raw/master/prod_ch4l_msg.yml",
                f"{settings.gitlab_url}/inventory/gateway/-/raw/master/prod_lo2l_msg.yml",
                f"{settings.gitlab_url}/inventory/gateway/-/raw/master/prod_fr2l_msg.yml",
                f"{settings.gitlab_url}/inventory/gateway/-/raw/master/prod_sg2l_msg.yml",
            ]
        else:
            urls = [
                f"{settings.gitlab_url}/inventory/gateway/-/raw/master/stage_ch3l_msg.yml",
                f"{settings.gitlab_url}/inventory/gateway/-/raw/master/stage_ch5l_msg.yml",
            ]

    return urls


# ---------------------------------------------------------------------------
# YAML fetch and parse
# ---------------------------------------------------------------------------

def _fetch_yaml(url: str) -> Optional[dict]:
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(url, context=ctx) as resp:
            data = resp.read()
        return yaml.safe_load(data)
    except Exception as exc:
        logger.error("Failed to fetch/parse YAML from %s: %s", url, exc)
        return None


# _convert_to_current_week removed: cron jobs now evaluate over the full
# 15-day window directly so no week-mapping is needed.


def _parse_inventory_yaml(
    url: str,
    yaml_data: dict,
) -> list[ScheduledTask]:
    """
    Parse one Ansible inventory YAML file into ScheduledTask objects.

    Each cron expression is evaluated over the full 15-day display window
    (this Sunday 00:00 UTC → Monday +2 weeks) directly in the cron's own
    timezone via croniter_range.  This means:

    - All occurrences across both weeks are calculated from the expression
      rather than by cloning week1 — fully DST-aware at the source.
    - No _convert_to_current_week / fake-week mapping needed.
    - No EOW sentinel logic needed (we have real dates over 15 days).
    - Each returned datetime is a real UTC-aware datetime in the window.
    """
    inventory_file = url.split("/")[-1]
    computer_name = inventory_file.replace(".yml", "")
    tasks: list[ScheduledTask] = []

    # 15-day window boundaries in UTC
    win_start_utc = window_start()   # this Sunday 00:00 UTC
    win_end_utc   = window_end()     # Monday +2 weeks 00:00 UTC

    for msgr_type, msgr_config in yaml_data.get("vars", {}).get("gw_messengers", {}).items():
        cron_groups = msgr_config.get("cron_groups", {})

        for group_name, group_config in cron_groups.items():
            group_tz_str = group_config.get("cron_tz", _DEFAULT_TZ)

            for start_stop in ("cron_start", "cron_stop"):
                # Resolve the timezone for this cron direction
                cron_tz_str = group_config.get(start_stop, {}).get("cron_tz", group_tz_str)
                cron_tz = pytz.timezone(cron_tz_str)

                # Find this Sunday 00:00 in the CRON'S OWN TIMEZONE.
                # We cannot simply convert win_start_utc (Sunday 00:00 UTC)
                # to local time — in UTC+ zones that becomes Saturday evening.
                # Instead: find what day-of-week it is locally right now,
                # back up to local Sunday midnight, then advance 15 days.
                now_local    = datetime.now(cron_tz)
                local_dow    = now_local.weekday()              # Mon=0…Sun=6
                days_to_sun  = (local_dow + 1) % 7             # 0 if already Sunday
                local_sunday = (now_local - timedelta(days=days_to_sun)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                # Re-normalise through pytz to resolve any DST fold at midnight
                local_sunday = cron_tz.normalize(
                    cron_tz.localize(local_sunday.replace(tzinfo=None))
                )

                # Extend window back 1 day (to Saturday 00:00 local) so that
                # any start event that fired before Sunday but whose corresponding
                # stop falls within the 15-day window is captured.
                # The comparator will treat pre-window starts as "already running
                # at window open" and create a synthetic interval from window_start.
                win_start_local = local_sunday - timedelta(days=1)
                win_end_local   = local_sunday + timedelta(days=15)

                run_times: list[datetime] = []
                for expr in group_config.get(start_stop, {}).get("expression", []):
                    for dt in croniter_range(win_start_local, win_end_local, expr):
                        # Convert each occurrence to UTC for storage
                        run_times.append(dt.astimezone(UTC_TZ))

                run_times.sort()

                t_type = TaskType.START if "start" in start_stop else TaskType.STOP
                task_name = f"{group_name} {start_stop}"
                messenger_name = "_".join(group_name.split("_")[:-1])

                tasks.append(
                    ScheduledTask(
                        computer_name=computer_name,
                        name=task_name,
                        directory=inventory_file,
                        weekly_run_times=run_times,
                        messenger_name=messenger_name,
                        task_type=t_type,
                        enabled=True,
                        source=TaskSource.LINUX,
                    )
                )

    return tasks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_linux_cron_tasks(is_stage: bool = False) -> list[ScheduledTask]:
    """
    Fetch and parse all Linux messenger cron schedules from GitLab inventory.

    Parameters
    ----------
    is_stage:
        If True, fetches stage inventory files; otherwise prod.

    Returns
    -------
    List of ScheduledTask objects with source=TaskSource.LINUX.
    """
    env = "stage" if is_stage else "prod"
    urls = _discover_inventory_urls(env)

    all_tasks: list[ScheduledTask] = []
    for url in urls:
        yaml_data = _fetch_yaml(url)
        if yaml_data is None:
            continue
        try:
            tasks = _parse_inventory_yaml(url, yaml_data)
            all_tasks.extend(tasks)
            logger.info("Parsed %d tasks from %s", len(tasks), url.split("/")[-1])
        except Exception:
            logger.exception("Error parsing inventory file: %s", url)

    logger.info("Total Linux cron tasks loaded: %d", len(all_tasks))
    return all_tasks
