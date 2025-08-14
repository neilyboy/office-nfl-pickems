from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import get_settings
from app.services import backup as backup_service
from app.db.session import session_scope
from app.models.game import Game, GameStatus
from app.services.nfl.live import bulk_fetch_live_events
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

logger = logging.getLogger("app.services.scheduler")

_scheduler: Optional[BackgroundScheduler] = None


def _get_tz():
    settings = get_settings()
    if settings.TIMEZONE and settings.TIMEZONE.lower() != "local" and ZoneInfo is not None:
        try:
            return ZoneInfo(settings.TIMEZONE)
        except Exception:
            logger.warning("Invalid TIMEZONE '%s', falling back to system local.", settings.TIMEZONE)
    return None  # system local


def _ensure_jobs(sched: BackgroundScheduler) -> None:
    # Weekly backup: early Tuesday 03:30 local time, after MNF completes
    job_id = "weekly_backup"
    existing = sched.get_job(job_id)
    tz = _get_tz()
    trigger = CronTrigger(day_of_week="tue", hour=3, minute=30, timezone=tz)

    def run_weekly_backup() -> None:
        backup_service.create_backup()
        backup_service.prune_backups()

    if existing is None:
        sched.add_job(run_weekly_backup, trigger=trigger, id=job_id, replace_existing=True)
        logger.info("Scheduled weekly backup: %s", trigger)
    else:
        # Update trigger if needed
        existing.reschedule(trigger=trigger)
        logger.info("Rescheduled weekly backup: %s", trigger)

    # Live scoreboard updater: every 60 seconds
    live_job_id = "live_scoreboard"
    live_existing = sched.get_job(live_job_id)
    live_trigger = IntervalTrigger(seconds=60)

    def run_live_scoreboard() -> None:
        try:
            now = datetime.now(timezone.utc)
            start_window = now - timedelta(hours=6)
            end_window = now + timedelta(hours=10)
            with session_scope() as db:
                games: list[Game] = (
                    db.query(Game)
                    .filter(
                        Game.provider_game_id.isnot(None),
                        Game.start_time >= start_window,
                        Game.start_time <= end_window,
                        Game.status != GameStatus.FINAL,
                    )
                    .all()
                )
                event_ids = [g.provider_game_id for g in games if g.provider_game_id]
                if not event_ids:
                    return
                live = bulk_fetch_live_events(event_ids)

                for g in games:
                    lg = live.get(g.provider_game_id or "")
                    if not lg:
                        continue
                    # Map ESPN states to GameStatus
                    if lg.state == "in":
                        g.status = GameStatus.IN_PROGRESS
                    elif lg.state == "post":
                        g.status = GameStatus.FINAL
                    else:
                        g.status = GameStatus.SCHEDULED
                    if lg.home_score is not None:
                        g.home_score = lg.home_score
                    if lg.away_score is not None:
                        g.away_score = lg.away_score
                # session_scope commits on exit
        except Exception:
            logger.debug("Live scoreboard update failed", exc_info=True)

    if live_existing is None:
        sched.add_job(run_live_scoreboard, trigger=live_trigger, id=live_job_id, replace_existing=True)
        logger.info("Scheduled live scoreboard updater: %s", live_trigger)
    else:
        live_existing.reschedule(trigger=live_trigger)
        logger.info("Rescheduled live scoreboard updater: %s", live_trigger)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _ensure_jobs(_scheduler)
    _scheduler.start()
    logger.info("Background scheduler started")


def shutdown_scheduler(wait: bool = True) -> None:
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=wait)
        logger.info("Background scheduler stopped")
    finally:
        _scheduler = None
