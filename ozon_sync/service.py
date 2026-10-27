import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from ozon_sync import alerts, db, runner
from ozon_sync.config import Settings
from ozon_sync.loaders import Context, registry
from ozon_sync.ozon.client import OzonClient

log = structlog.get_logger()


def run_cycle(
    settings: Settings,
    selected: list[str] | None = None,
    client: OzonClient | None = None,
    telegram: alerts.Telegram | None = None,
) -> bool:
    loaders = registry()
    full = not selected
    selected = selected or list(loaders)
    telegram = telegram or alerts.Telegram(settings)
    own_client = client is None
    client = client or OzonClient(settings)
    env = settings.ozon_env
    try:
        with db.connect(settings) as conn:
            ctx = Context(client, conn, settings.ozon_method_overrides)
            results = runner.run(ctx, runner.order(loaders, selected))

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
                telegram.send(alerts.summary_message(env, results))
            return not failed
    except Exception as e:
        log.exception("cycle_failed")
        telegram.send(f"🔥 Ozon sync ({env}): цикл упал целиком: {type(e).__name__}: {e}")
        return False
    finally:
        if own_client:
            client.close()


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
