import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from ozon_sync.config import Settings


def connect(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(settings.database_url, autocommit=True, connect_timeout=10)


def close_interrupted(conn: psycopg.Connection, older_than_hours: int = 6) -> int:
    return conn.execute(
        """UPDATE sync_log SET status = 'error', finished_at = now(),
           error = 'запуск прерван: процесс остановился до завершения'
           WHERE status = 'running' AND started_at < now() - make_interval(hours => %s)""",
        (older_than_hours,),
    ).rowcount


def log_start(conn: psycopg.Connection, run_id: uuid.UUID, table_name: str) -> int:
    row = conn.execute(
        "INSERT INTO sync_log (run_id, table_name, started_at, status) VALUES (%s, %s, %s, 'running') RETURNING id",
        (run_id, table_name, datetime.now(UTC)),
    ).fetchone()
    return row[0]


def log_finish(
    conn: psycopg.Connection,
    log_id: int,
    *,
    status: str,
    inserted: int = 0,
    updated: int = 0,
    deleted: int = 0,
    error: str | None = None,
) -> None:
    conn.execute(
        """UPDATE sync_log SET finished_at = %s, status = %s,
           rows_inserted = %s, rows_updated = %s, rows_deleted = %s, error = %s
           WHERE id = %s""",
        (datetime.now(UTC), status, inserted, updated, deleted, error, log_id),
    )


def has_active_rows(conn: psycopg.Connection, table: str) -> bool:
    query = sql.SQL("SELECT EXISTS (SELECT 1 FROM {} WHERE NOT is_deleted)").format(sql.Identifier(table))
    return conn.execute(query).fetchone()[0]


def sync_table(
    conn: psycopg.Connection,
    table: str,
    key: tuple[str, ...],
    columns: tuple[str, ...],
    rows: Iterable[dict[str, Any]],
) -> tuple[int, int, int]:
    cols = (*columns, "raw")
    t = sql.Identifier(table)
    col_list = sql.SQL(", ").join(map(sql.Identifier, cols))
    key_list = sql.SQL(", ").join(map(sql.Identifier, key))
    set_list = sql.SQL(", ").join(
        sql.SQL("{c} = excluded.{c}").format(c=sql.Identifier(c)) for c in cols if c not in key
    )
    key_match = sql.SQL(" AND ").join(
        sql.SQL("s.{c} = t.{c}").format(c=sql.Identifier(c)) for c in key
    )

    with conn.transaction():
        conn.execute(sql.SQL("CREATE TEMP TABLE _stage ON COMMIT DROP AS SELECT {} FROM {} WITH NO DATA").format(col_list, t))
        with conn.cursor().copy(sql.SQL("COPY _stage ({}) FROM STDIN").format(col_list)) as copy:
            for row in rows:
                copy.write_row([Jsonb(row["raw"]) if c == "raw" else row[c] for c in cols])

        results = conn.execute(
            sql.SQL("""
                INSERT INTO {t} AS t ({cols})
                SELECT DISTINCT ON ({key}) {cols} FROM _stage ORDER BY {key}
                ON CONFLICT ({key}) DO UPDATE SET {set_list}, updated_at = now(), is_deleted = false
                WHERE t.raw IS DISTINCT FROM excluded.raw OR t.is_deleted
                RETURNING (xmax = 0)
            """).format(t=t, cols=col_list, key=key_list, set_list=set_list)
        ).fetchall()
        inserted = sum(1 for (is_new,) in results if is_new)
        updated = len(results) - inserted

        deleted = conn.execute(
            sql.SQL("""
                UPDATE {t} AS t SET is_deleted = true, updated_at = now()
                WHERE NOT t.is_deleted AND NOT EXISTS (SELECT 1 FROM _stage s WHERE {key_match})
            """).format(t=t, key_match=key_match)
        ).rowcount
    return inserted, updated, deleted
