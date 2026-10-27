import json

import httpx
import pytest
import respx

from conftest import BASE, fixture
from ozon_sync import service
from ozon_sync.config import Settings
from ozon_sync.loaders import registry
from ozon_sync.ozon.client import OzonClient

TABLES = list(registry())


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True


def first_page(name, cursor="last_id"):
    def handler(req):
        if json.loads(req.content)[cursor] == "":
            return httpx.Response(200, json=fixture(name))
        return httpx.Response(200, json={"result": {"items": []}, "items": [], "products": [], "cursor": ""})

    return handler


def delivery_methods(req):
    body = json.loads(req.content)
    if body["offset"] == 0 and body["filter"]["warehouse_id"] == 1020000001:
        return httpx.Response(200, json=fixture("delivery_method_list"))
    return httpx.Response(200, json={"result": []})


@pytest.fixture
def ozon_api():
    with respx.mock(base_url=BASE, assert_all_called=False) as api:
        api.post("/v1/warehouse/list").respond(json=fixture("warehouse_list"))
        api.post("/v1/delivery-method/list").mock(side_effect=delivery_methods)
        api.post("/v3/product/list").mock(side_effect=first_page("product_list"))
        api.post("/v3/product/info/list").respond(json=fixture("product_info_list"))
        api.post("/v5/product/info/prices").mock(side_effect=first_page("product_info_prices", "cursor"))
        api.post("/v4/product/info/stocks").mock(side_effect=first_page("product_info_stocks", "cursor"))
        api.post("/v1/product/info/stocks-by-warehouse/fbs").respond(json=fixture("stocks_by_warehouse_fbs"))
        api.get("/v1/actions").respond(json=fixture("actions_list"))
        api.post("/v2/actions/candidates").mock(side_effect=first_page("actions_candidates"))
        api.post("/v2/actions/products").mock(side_effect=first_page("actions_products"))
        api.post("/v1/broken").respond(404, json={"code": 5, "message": "Not Found"})
        yield api


def cycle(**overrides):
    settings = Settings(_env_file=None, ozon_env="prod", telegram_summary=False, **overrides)
    client = OzonClient(settings, http=httpx.Client(base_url=BASE), sleep=lambda _: None)
    tg = FakeTelegram()
    ok = service.run_cycle(settings, client=client, telegram=tg)
    return ok, tg


def counts(conn):
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}


def last_run(conn):
    return conn.execute("""
        SELECT table_name, status, rows_inserted, rows_updated, rows_deleted
        FROM sync_log WHERE run_id = (SELECT run_id FROM sync_log ORDER BY id DESC LIMIT 1)
        ORDER BY id
    """).fetchall()


def test_full_cycle_fills_all_tables_and_is_idempotent(migrated, ozon_api):
    ok, tg = cycle()
    assert ok and tg.sent == []
    first = counts(migrated)
    assert all(first[t] > 0 for t in TABLES), first
    assert [r[0] for r in last_run(migrated)] == TABLES
    assert all(r[1] == "ok" for r in last_run(migrated))

    ok, _ = cycle()
    assert ok
    assert counts(migrated) == first
    assert [r[2:] for r in last_run(migrated)] == [(0, 0, 0)] * len(TABLES)


def test_removed_product_marked_deleted(migrated, ozon_api):
    cycle()
    page = fixture("product_list")
    page["result"]["items"] = page["result"]["items"][:1]
    ozon_api.post("/v3/product/list").mock(
        side_effect=lambda req: httpx.Response(
            200, json=page if json.loads(req.content)["last_id"] == "" else {"result": {"items": []}}
        )
    )
    cycle()
    assert migrated.execute("SELECT product_id, is_deleted FROM ozon_products ORDER BY 1").fetchall() == [
        (223681945, False),
        (223681946, True),
    ]


def test_broken_method_fails_one_table_and_alerts(migrated, ozon_api):
    ok, tg = cycle(ozon_method_overrides={"/v3/product/list": "/v1/broken"})
    assert not ok
    statuses = {r[0]: r[1] for r in last_run(migrated)}
    assert statuses.pop("ozon_products") == "error"
    assert set(statuses.values()) == {"ok"} and len(statuses) == 8
    assert any("ozon_products" in m and "404" in m for m in tg.sent)


def test_rate_limit_mid_cycle(migrated, ozon_api):
    ozon_api.post("/v1/warehouse/list").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json=fixture("warehouse_list")),
        ]
    )
    ok, _ = cycle()
    assert ok
    assert counts(migrated)["ozon_warehouses"] == 2


def test_sheet_failure_does_not_touch_db(migrated, ozon_api, monkeypatch):
    def boom(*a):
        raise PermissionError("нет доступа")

    monkeypatch.setattr(service.sheets, "export", boom)
    ok, tg = cycle(gsheet_id="sheet")
    assert not ok
    run = {r[0]: r[1] for r in last_run(migrated)}
    assert run.pop("gsheet") == "error" and set(run.values()) == {"ok"}
    assert all(n > 0 for n in counts(migrated).values())
    assert any("gsheet" in m for m in tg.sent)
