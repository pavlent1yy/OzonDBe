import json

import respx

from conftest import BASE, fixture
from ozon_sync.loaders import products, warehouses


@respx.mock
def test_warehouses_mapping(fake_ctx):
    respx.post(f"{BASE}/v1/warehouse/list").respond(json=fixture("warehouse_list"))
    rows = list(warehouses.fetch_warehouses(fake_ctx()))
    assert [(r["warehouse_id"], r["name"], r["is_rfbs"], r["status"]) for r in rows] == [
        (1020000001, "Склад Москва", False, "created"),
        (1020000002, "rFBS Казань", True, "disabled"),
    ]
    assert rows[0]["raw"]["first_mile_type"]["first_mile_type"] == "PickUp"


@respx.mock
def test_delivery_methods_per_warehouse(fake_ctx):
    route = respx.post(f"{BASE}/v1/delivery-method/list").mock(
        side_effect=lambda req: respx.MockResponse(
            json=fixture("delivery_method_list") if json.loads(req.content)["offset"] == 0 else {"result": []}
        )
    )
    rows = list(warehouses.fetch_delivery_methods(fake_ctx({"ozon_warehouses": [1020000001, 7]})))
    assert [(r["id"], r["warehouse_id"], r["status"]) for r in rows] == [
        (15430, 1020000001, "ACTIVE"),
        (15430, 1020000001, "ACTIVE"),
    ]
    sent = [json.loads(c.request.content)["filter"]["warehouse_id"] for c in route.calls]
    assert sent == [1020000001, 1020000001, 7, 7]


@respx.mock
def test_products_list_and_info(fake_ctx):
    respx.post(f"{BASE}/v3/product/list").mock(
        side_effect=lambda req: respx.MockResponse(
            json=fixture("product_list")
            if json.loads(req.content)["last_id"] == ""
            else {"result": {"items": [], "last_id": ""}}
        )
    )
    info = respx.post(f"{BASE}/v3/product/info/list").respond(json=fixture("product_info_list"))
    rows = list(products.fetch_products(fake_ctx()))
    assert [(r["product_id"], r["offer_id"], r["name"], r["archived"]) for r in rows] == [
        (223681945, "136748", "Смарт-часы X1", False),
        (223681946, "136749", "Ремешок", True),
    ]
    assert rows[0]["raw"]["info"]["sources"][0]["sku"] == 1234567
    assert json.loads(info.calls.last.request.content) == {"product_id": ["223681945", "223681946"]}


@respx.mock
def test_method_override(fake_ctx):
    route = respx.post(f"{BASE}/v2/warehouse/list").respond(json={"result": []})
    list(warehouses.fetch_warehouses(fake_ctx(overrides={"/v1/warehouse/list": "/v2/warehouse/list"})))
    assert route.called
