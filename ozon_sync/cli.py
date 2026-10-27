import argparse

import structlog

from ozon_sync import db, runner
from ozon_sync.config import Settings
from ozon_sync.loaders import Context, registry
from ozon_sync.logging import setup_logging
from ozon_sync.ozon.client import OzonClient

log = structlog.get_logger()


def main(argv: list[str] | None = None) -> int:
    loaders = registry()
    parser = argparse.ArgumentParser(prog="ozon-sync")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping", help="проверить доступ к Ozon API")
    sync = sub.add_parser("sync", help="синхронизировать таблицы")
    target = sync.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true")
    target.add_argument("--table", action="append", choices=sorted(loaders))
    args = parser.parse_args(argv)

    settings = Settings()
    setup_logging(settings.log_level)
    client = OzonClient(settings)
    try:
        if args.cmd == "ping":
            resp = client.post("/v1/warehouse/list")
            log.info("ping_ok", env=settings.ozon_env, warehouses=len(resp.get("result", [])))
            return 0

        selected = list(loaders) if args.all else args.table
        with db.connect(settings) as conn:
            ctx = Context(client, conn, settings.ozon_method_overrides)
            results = runner.run(ctx, runner.order(loaders, selected))
        return 0 if all(r.status == "ok" for r in results) else 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
