import uuid

import pytest

from ozon_sync import db, runner
from ozon_sync.loaders import Context, Loader, registry

COMMON = """raw jsonb NOT NULL, first_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(), is_deleted boolean NOT NULL DEFAULT false"""


def test_order_puts_dependencies_first():
    names = [ld.table for ld in runner.order(registry(), ["ozon_delivery_methods", "ozon_products", "ozon_warehouses"])]
    assert names.index("ozon_warehouses") < names.index("ozon_delivery_methods")
    assert sorted(names) == sorted(set(names))


def test_order_does_not_pull_unselected_dependencies():
    assert [ld.table for ld in runner.order(registry(), ["ozon_delivery_methods"])] == ["ozon_delivery_methods"]


@pytest.fixture
def items(pg):
    pg.execute(f"CREATE TABLE items (a bigint, b text, name text, {COMMON}, PRIMARY KEY (a, b))")
    pg.execute("""CREATE TABLE sync_log (id bigserial PRIMARY KEY, run_id uuid, table_name text,
        started_at timestamptz, finished_at timestamptz, status text, rows_inserted int,
        rows_updated int, rows_deleted int, error text)""")
    return pg


def rows(*specs):
    return [{"a": a, "b": b, "name": n, "raw": {"a": a, "b": b, "name": n}} for a, b, n in specs]


def sync(conn, data):
    return db.sync_table(conn, "items", ("a", "b"), ("a", "b", "name"), data)


def test_upsert_is_idempotent(items):
    assert sync(items, rows((1, "x", "one"), (2, "x", "two"))) == (2, 0, 0)
    assert sync(items, rows((1, "x", "one"), (2, "x", "two"))) == (0, 0, 0)
    assert items.execute("SELECT count(*) FROM items").fetchone()[0] == 2


def test_upsert_updates_changed_and_marks_deleted(items):
    sync(items, rows((1, "x", "one"), (2, "x", "two")))
    assert sync(items, rows((1, "x", "ONE"), (3, "x", "three"))) == (1, 1, 1)
    state = items.execute("SELECT a, name, is_deleted FROM items ORDER BY a").fetchall()
    assert state == [(1, "ONE", False), (2, "two", True), (3, "three", False)]


def test_deleted_row_comes_back(items):
    sync(items, rows((1, "x", "one")))
    sync(items, [])
    assert sync(items, rows((1, "x", "one"))) == (0, 1, 0)
    assert items.execute("SELECT is_deleted FROM items").fetchone()[0] is False


def test_duplicate_keys_in_response(items):
    assert sync(items, rows((1, "x", "one"), (1, "x", "one"))) == (1, 0, 0)


def test_failed_table_does_not_stop_others(items):
    def boom(ctx):
        raise RuntimeError("bad method")

    bad = Loader("missing_table", ("a",), ("a",), boom)
    good = Loader("items", ("a", "b"), ("a", "b", "name"), lambda ctx: rows((1, "x", "one")))
    results = runner.run(Context(None, items, {}), [bad, good], uuid.uuid4())
    assert [r.status for r in results] == ["error", "ok"]
    log = items.execute("SELECT table_name, status, error FROM sync_log ORDER BY id").fetchall()
    assert log[0][:2] == ("missing_table", "error") and "bad method" in log[0][2]
    assert log[1] == ("items", "ok", None)


def test_empty_response_does_not_wipe_table(items):
    sync(items, rows((1, "x", "one")))
    empty = Loader("items", ("a", "b"), ("a", "b", "name"), lambda ctx: [])
    [result] = runner.run(Context(None, items, {}), [empty], uuid.uuid4())
    assert result.status == "error" and "0 записей" in result.error
    assert items.execute("SELECT is_deleted FROM items").fetchone()[0] is False


def test_empty_response_allowed_when_flagged(items):
    sync(items, rows((1, "x", "one")))
    empty = Loader("items", ("a", "b"), ("a", "b", "name"), lambda ctx: [], allow_empty=True)
    [result] = runner.run(Context(None, items, {}), [empty], uuid.uuid4())
    assert (result.status, result.deleted) == ("ok", 1)


def test_db_error_rolls_back_only_that_table(items):
    bad = Loader("no_such_table", ("a",), ("a",), lambda ctx: [{"a": 1, "raw": {}}])
    good = Loader("items", ("a", "b"), ("a", "b", "name"), lambda ctx: rows((1, "x", "one")))
    results = runner.run(Context(None, items, {}), [bad, good], uuid.uuid4())
    assert [r.status for r in results] == ["error", "ok"]


def test_interrupted_runs_closed(items):
    old = db.log_start(items, uuid.uuid4(), "items")
    items.execute("UPDATE sync_log SET started_at = now() - interval '7 hours' WHERE id = %s", (old,))
    fresh = db.log_start(items, uuid.uuid4(), "items")
    assert db.close_interrupted(items) == 1
    rows = dict(items.execute("SELECT id, status FROM sync_log").fetchall())
    assert rows == {old: "error", fresh: "running"}
