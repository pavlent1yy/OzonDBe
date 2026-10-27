"""sync_log, sync_status, analytics role

Revision ID: 0001
Revises:
"""
import os

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sync_log (
            id            bigserial PRIMARY KEY,
            run_id        uuid        NOT NULL,
            table_name    text        NOT NULL,
            started_at    timestamptz NOT NULL,
            finished_at   timestamptz,
            status        text        NOT NULL CHECK (status IN ('running', 'ok', 'error')),
            rows_inserted integer     NOT NULL DEFAULT 0,
            rows_updated  integer     NOT NULL DEFAULT 0,
            rows_deleted  integer     NOT NULL DEFAULT 0,
            error         text
        )
    """)
    op.execute("CREATE INDEX sync_log_table_started_idx ON sync_log (table_name, started_at DESC)")
    op.execute("CREATE INDEX sync_log_run_idx ON sync_log (run_id)")
    op.execute("""
        CREATE VIEW sync_status AS
        SELECT t.table_name,
               ok.finished_at AS last_success_at,
               ok.rows_inserted, ok.rows_updated, ok.rows_deleted,
               err.finished_at AS last_error_at,
               err.error       AS last_error
        FROM (SELECT DISTINCT table_name FROM sync_log) t
        LEFT JOIN LATERAL (
            SELECT * FROM sync_log s
            WHERE s.table_name = t.table_name AND s.status = 'ok'
            ORDER BY s.finished_at DESC LIMIT 1
        ) ok ON true
        LEFT JOIN LATERAL (
            SELECT * FROM sync_log s
            WHERE s.table_name = t.table_name AND s.status = 'error'
            ORDER BY s.finished_at DESC LIMIT 1
        ) err ON true
    """)

    ro_password = os.environ.get("ANALYTICS_RO_PASSWORD")
    if ro_password:
        quoted = ro_password.replace("'", "''")
        op.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'analytics_ro') THEN
                    CREATE ROLE analytics_ro LOGIN PASSWORD '{quoted}';
                END IF;
            END $$
        """)
        op.execute("GRANT USAGE ON SCHEMA public TO analytics_ro")
        op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO analytics_ro")
        op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analytics_ro")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS sync_status")
    op.execute("DROP TABLE IF EXISTS sync_log")
