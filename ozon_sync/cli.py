import argparse

import structlog

from ozon_sync import service
from ozon_sync.config import Settings
from ozon_sync.loaders import registry
from ozon_sync.logging import setup_logging
from ozon_sync.ozon.client import OzonClient

log = structlog.get_logger()


def main(argv: list[str] | None = None) -> int:
    loaders = registry()
    parser = argparse.ArgumentParser(prog="ozon-sync")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping", help="проверить доступ к Ozon API")
    sub.add_parser("schedule", help="запускать sync --all по расписанию")
    sub.add_parser("ro-role", help="создать или обновить роль analytics_ro из ANALYTICS_RO_PASSWORD")
    sync = sub.add_parser("sync", help="синхронизировать таблицы")
    target = sync.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true")
    target.add_argument("--table", action="append", choices=sorted(loaders))
    args = parser.parse_args(argv)

    settings = Settings()
    setup_logging(settings.log_level)

    if args.cmd == "ping":
        client = OzonClient(settings)
        try:
            resp = client.post("/v1/warehouse/list")
        finally:
            client.close()
        log.info("ping_ok", env=settings.ozon_env, warehouses=len(resp.get("result", [])))
        return 0

    if args.cmd == "ro-role":
        password = settings.analytics_ro_password.get_secret_value()
        if not password:
            log.info("ro_role_skipped", reason="ANALYTICS_RO_PASSWORD не задан")
            return 0
        with service.db.connect(settings) as conn:
            service.db.ensure_ro_role(conn, password)
        log.info("ro_role_ready", role="analytics_ro")
        return 0

    if args.cmd == "schedule":
        service.schedule(settings)
        return 0

    selected = None if args.all else args.table
    return 0 if service.run_cycle(settings, selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
