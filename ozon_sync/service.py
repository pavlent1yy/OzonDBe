import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ozon_sync import alerts, db, runner, sheets
from ozon_sync.config import Settings
from ozon_sync.loaders import Context, Loader, registry
from ozon_sync.ozon.client import OzonClient

log = structlog.get_logger()

SHEET_LOG_NAME = "gsheet"


def run_cycle(
    settings: Settings,
    selected: list[str] | None = None,
    client: OzonClient | None = None,
    telegram: alerts.Telegram | None = None,
) -> bool:
    loaders = available_loaders(settings)
    full = not selected
    skipped = [t for t in selected or [] if t not in loaders]
    if skipped:
        log.warning("tables_skipped_in_sandbox", tables=skipped)
    selected = [t for t in selected if t in loaders] if selected else list(loaders)
    telegram = telegram or alerts.Telegram(settings)
    own_client = client is None
    client = client or OzonClient(settings)
    env = settings.ozon_env
    started = time.monotonic()
    try:
        with db.connect(settings) as conn:
            ctx = Context(client, conn, settings.ozon_method_overrides)
            run_id = uuid.uuid4()
            results = runner.run(ctx, runner.order(loaders, selected), run_id)
            if settings.gsheet_id:
                results.append(export_sheet(conn, settings, run_id))

            failed = [r for r in results if r.status != "ok"]
            if failed:
                telegram.send(alerts.failure_message(env, failed))
            failed_names = {r.table for r in failed}
            stale = [
                t for t in alerts.stale_tables(conn, list(loaders), settings.stale_after_hours)
                if t not in failed_names
            ] if full else []
            if stale:
                telegram.send(alerts.stale_message(env, stale, settings.stale_after_hours))
            if settings.telegram_summary:
                finished_at = datetime.now(ZoneInfo(settings.sync_timezone))
                telegram.send(alerts.summary_message(env, results, finished_at, time.monotonic() - started))
            return not failed
    except Exception as e:
        log.exception("cycle_failed")
        telegram.send(alerts.cycle_failed_message(env, f"{type(e).__name__}: {e}"))
        return False
    finally:
        if own_client:
            client.close()


def available_loaders(settings: Settings) -> dict[str, Loader]:
    loaders = registry()
    if settings.ozon_env != "sandbox":
        return loaders
    return {name: ld for name, ld in loaders.items() if ld.sandbox}


def export_sheet(conn, settings: Settings, run_id: uuid.UUID) -> runner.TableResult:
    log_id = db.log_start(conn, run_id, SHEET_LOG_NAME)
    try:
        written = sheets.export(conn, settings.gsheet_id, settings.google_credentials_file, settings.sync_timezone)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        db.log_finish(conn, log_id, status="error", error=error[:4000])
        log.error("gsheet_failed", error=error)
        return runner.TableResult(SHEET_LOG_NAME, "error", error=error)
    db.log_finish(conn, log_id, status="ok", updated=written)
    log.info("gsheet_ok", rows=written)
    return runner.TableResult(SHEET_LOG_NAME, "ok", updated=written)


def build_scheduler(settings: Settings) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=settings.sync_timezone)
    for hour, minute in settings.schedule_times:
        scheduler.add_job(
            run_cycle,
            CronTrigger(hour=hour, minute=minute, timezone=settings.sync_timezone),
            args=[settings],
            id=f"sync_{hour:02d}{minute:02d}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
    return scheduler


def schedule(settings: Settings) -> None:
    scheduler = build_scheduler(settings)
    for job in scheduler.get_jobs():
        log.info("job_scheduled", job=job.id, trigger=str(job.trigger))
    scheduler.start()
