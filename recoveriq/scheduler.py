"""Planificateur intégré (APScheduler) : synchronisation quotidienne et rapport IA hebdomadaire.

Le rapport hebdomadaire est planifié par défaut le lundi à 07:30, après la
synchronisation de 06:30, pour analyser une semaine complète de données fraîches.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.cron import CronTrigger

from recoveriq.config import Settings
from recoveriq.db import repository as repo
from recoveriq.db.database import connect
from recoveriq.garmin.sync import SyncService

WEEKLY_JOB_ID = "weekly_ai_report"

log = logging.getLogger(__name__)


def build_scheduler(cfg: Settings, sync: SyncService) -> BackgroundScheduler:
    hour, minute = (int(x) for x in cfg.daily_sync_time.split(":"))
    scheduler = BackgroundScheduler()  # fuseau local de la machine par défaut
    scheduler.add_job(
        lambda: sync.request_incremental("scheduler"),
        CronTrigger(hour=hour, minute=minute),
        id="daily_sync",
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    return scheduler


def schedule_weekly_report(scheduler: BaseScheduler | None, ai: Any, weekly: dict[str, Any]) -> None:
    """(Re)planifie le rapport IA hebdomadaire selon les réglages ; le retire s'il est désactivé."""
    if scheduler is None:
        return
    if scheduler.get_job(WEEKLY_JOB_ID):
        scheduler.remove_job(WEEKLY_JOB_ID)
    if not weekly.get("enabled"):
        log.info("Rapport IA hebdomadaire désactivé")
        return
    hour, minute = (int(x) for x in weekly["time"].split(":"))
    period_days = int(weekly.get("period_days", 7))
    scheduler.add_job(
        lambda: ai.run_scheduled(period_days),
        CronTrigger(day_of_week=weekly["day"], hour=hour, minute=minute),
        id=WEEKLY_JOB_ID,
        coalesce=True,
        misfire_grace_time=6 * 3600,   # PC en veille à l'heure prévue : rattrapé dans les 6 h
        replace_existing=True,
    )
    log.info("Rapport IA hebdomadaire planifié : %s %s (%s j)", weekly["day"], weekly["time"], period_days)


def needs_catch_up() -> bool:
    """Vrai si aucune synchro incrémentale n'a réussi depuis plus de 24 h (PC éteint, appli fermée)."""
    with connect() as conn:
        last = repo.last_successful_run(conn, "incremental")
    if last is None or not last["ended_at"]:
        return True
    ended = datetime.fromisoformat(last["ended_at"])
    return datetime.now(timezone.utc) - ended > timedelta(hours=24)
