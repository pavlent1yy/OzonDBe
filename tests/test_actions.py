import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import respx

from conftest import BASE, fixture
from ozon_sync.loaders import actions


def last_id_pages(name):
    def handler(req):
        if json.loads(req.content)["last_id"] == "":
            return httpx.Response(200, json=fixture(name))
        return httpx.Response(200, json={"products": [], "last_id": ""})

    return handler


@respx.mock
def test_actions_list_is_get(fake_ctx):
    route = respx.get(f"{BASE}/v1/actions").respond(json=fixture("actions_list"))
    rows = list(actions.fetch_actions(fake_ctx()))
    assert route.calls.last.request.method == "GET"
    assert [(r["action_id"], r["action_type"], r["is_participating"]) for r in rows] == [
        (71342, "DISCOUNT", True),
        (71343, "VOUCHER", False),
    ]
    assert rows[0]["date_start"] == datetime(2026, 10, 20, tzinfo=UTC)
    assert (rows[1]["date_start"], rows[1]["date_end"]) == (None, None)


@respx.mock
def test_candidates_per_action(fake_ctx):
    route = respx.post(f"{BASE}/v2/actions/candidates").mock(side_effect=last_id_pages("actions_candidates"))
    rows = list(actions.fetch_candidates(fake_ctx({"ozon_actions": [71342]})))
    assert [(r["action_id"], r["product_id"], r["price"], r["action_price"], r["currency"]) for r in rows] == [
        (71342, 223681945, Decimal("1990"), Decimal("1790"), "RUB"),
    ]
    bodies = [json.loads(c.request.content) for c in route.calls]
    assert bodies == [
        {"action_id": 71342, "limit": 100, "last_id": ""},
        {"action_id": 71342, "limit": 100, "last_id": "223681945"},
    ]


@respx.mock
def test_action_products_extra_fields(fake_ctx):
    respx.post(f"{BASE}/v2/actions/products").mock(side_effect=last_id_pages("actions_products"))
    [row] = list(actions.fetch_action_products(fake_ctx({"ozon_actions": [71342]})))
    assert (row["product_id"], row["stock"], row["add_mode"], row["max_action_price"]) == (
        223681946, 2, "SELLER", Decimal("3560"),
    )


def test_amount_tolerates_missing():
    assert actions.amount(None) is None
    assert actions.amount({"currency": "RUB"}) is None
