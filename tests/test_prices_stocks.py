import json
from decimal import Decimal

import httpx
import respx

from conftest import BASE, fixture
from ozon_sync.loaders import prices_stocks


def cursor_pages(name):
    def handler(req):
        body = json.loads(req.content)
        if body["cursor"] == "":
            return httpx.Response(200, json={**fixture(name), "cursor": "next"})
        return httpx.Response(200, json={"cursor": "", "items": []})

    return handler


@respx.mock
def test_prices_mapping(fake_ctx):
    route = respx.post(f"{BASE}/v5/product/info/prices").mock(side_effect=cursor_pages("product_info_prices"))
    rows = list(prices_stocks.fetch_prices(fake_ctx({"ozon_products": [223681945]})))
    assert len(rows) == 1
    r = rows[0]
    assert (r["product_id"], r["offer_id"], r["currency_code"]) == (223681945, "136748", "RUB")
    assert (r["price"], r["old_price"], r["min_price"], r["marketing_price"]) == (
        Decimal("1990"), Decimal("2490"), Decimal("1500"), Decimal("1790"),
    )
    assert r["raw"]["commissions"]["sales_percent_fbs"] == 17
    first = json.loads(route.calls[0].request.content)
    assert first["filter"]["product_id"] == ["223681945"]
    assert json.loads(route.calls[1].request.content)["cursor"] == "next"


def test_money_handles_garbage():
    assert prices_stocks.money("") is None
    assert prices_stocks.money("abc") is None
    assert prices_stocks.money("10.50") == Decimal("10.50")


@respx.mock
def test_prices_batches_products(fake_ctx, monkeypatch):
    monkeypatch.setattr(prices_stocks, "PRODUCT_BATCH", 2)
    route = respx.post(f"{BASE}/v5/product/info/prices").respond(json={"cursor": "", "items": []})
    list(prices_stocks.fetch_prices(fake_ctx({"ozon_products": [1, 2, 3]})))
    assert [json.loads(c.request.content)["filter"]["product_id"] for c in route.calls] == [["1", "2"], ["3"]]


@respx.mock
def test_stocks_rfbs_by_sku(fake_ctx):
    route = respx.post(f"{BASE}/v1/product/info/stocks-by-warehouse/fbs").respond(
        json=fixture("stocks_by_warehouse_fbs")
    )
    rows = list(prices_stocks.fetch_stocks_rfbs(fake_ctx({"jsonb_array_elements": [1234567]})))
    assert [(r["sku"], r["warehouse_id"], r["present"], r["reserved"]) for r in rows] == [
        (1234567, 1020000001, 12, 2),
        (1234567, 1020000002, 0, 0),
    ]
    assert json.loads(route.calls.last.request.content) == {"sku": ["1234567"]}


@respx.mock
def test_stock_management_row_per_type(fake_ctx):
    respx.post(f"{BASE}/v4/product/info/stocks").mock(side_effect=cursor_pages("product_info_stocks"))
    rows = list(prices_stocks.fetch_stock_management(fake_ctx({"ozon_products": [223681945]})))
    assert [(r["product_id"], r["type"], r["present"], r["reserved"]) for r in rows] == [
        (223681945, "fbs", 12, 2),
        (223681945, "fbo", 40, 0),
    ]
    assert rows[0]["raw"]["warehouse_ids"] == [1020000001]
