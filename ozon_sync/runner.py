import uuid
from dataclasses import dataclass

import psycopg
import structlog

from ozon_sync import db
from ozon_sync.loaders import Context, Loader

log = structlog.get_logger()


class EmptyResponse(Exception):
    pass


@dataclass
class TableResult:
    table: str
    status: str
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    error: str | None = None


def order(loaders: dict[str, Loader], selected: list[str]) -> list[Loader]:
    result: list[Loader] = []
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if any(ld.table == name for ld in result):
            return
        if name in visiting:
            raise ValueError(f"цикл зависимостей на {name}")
        visiting.add(name)
        for dep in loaders[name].depends:
            if dep in selected:
                visit(dep)
        result.append(loaders[name])

    for name in selected:
        visit(name)
    return result


def run(ctx: Context, loaders: list[Loader], run_id: uuid.UUID | None = None) -> list[TableResult]:
    run_id = run_id or uuid.uuid4()
    structlog.contextvars.bind_contextvars(run_id=str(run_id))
    results = []
    try:
        for ld in loaders:
            results.append(run_table(ctx, ld, run_id))
    finally:
        structlog.contextvars.unbind_contextvars("run_id")
    return results


def run_table(ctx: Context, ld: Loader, run_id: uuid.UUID) -> TableResult:
    conn = ctx.conn
    log_id = db.log_start(conn, run_id, ld.table)
    log.info("table_started", table=ld.table)
    try:
        rows = list(ld.fetch(ctx))
        if not rows and not ld.allow_empty and db.has_active_rows(conn, ld.table):
            raise EmptyResponse(f"API вернул 0 записей, а в {ld.table} есть активные: данные не тронуты")
        inserted, updated, deleted = db.sync_table(conn, ld.table, ld.key, ld.columns, rows)
    except Exception as e:
        if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            conn.rollback()
        error = f"{type(e).__name__}: {e}"
        db.log_finish(conn, log_id, status="error", error=error[:4000])
        log.error("table_failed", table=ld.table, error=error)
        return TableResult(ld.table, "error", error=error)
    db.log_finish(conn, log_id, status="ok", inserted=inserted, updated=updated, deleted=deleted)
    log.info("table_ok", table=ld.table, fetched=len(rows), inserted=inserted, updated=updated, deleted=deleted)
    return TableResult(ld.table, "ok", inserted, updated, deleted)
