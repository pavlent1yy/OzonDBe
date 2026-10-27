from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from ozon_sync.loaders import Context, Loader, Row, active_ids, chunks

PRODUCT_BATCH = 1000
SKU_BATCH = 500


def money(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def by_products(ctx: Context, path: str) -> Iterable[dict]:
    for batch in chunks(active_ids(ctx, "ozon_products", "product_id"), PRODUCT_BATCH):
        yield from ctx.client.paginate_last_id(
            path,
            {"filter": {"product_id": [str(i) for i in batch], "visibility": "ALL"}, "limit": PRODUCT_BATCH},
            lambda r: r.get("items", []),
            lambda r: r.get("cursor"),
            cursor_param="cursor",
        )


def fetch_prices(ctx: Context) -> Iterable[Row]:
    for item in by_products(ctx, ctx.path("/v5/product/info/prices")):
        price = item.get("price") or {}
        yield {
            "product_id": item["product_id"],
            "offer_id": item.get("offer_id"),
            "price": money(price.get("price")),
            "old_price": money(price.get("old_price")),
            "min_price": money(price.get("min_price")),
            "marketing_price": money(price.get("marketing_price")),
            "currency_code": price.get("currency_code"),
            "raw": item,
        }


def active_skus(ctx: Context) -> list[int]:
    query = """
        SELECT DISTINCT (s->>'sku')::bigint
        FROM ozon_products p, jsonb_array_elements(p.raw->'info'->'sources') s
        WHERE NOT p.is_deleted AND s->>'sku' IS NOT NULL
        ORDER BY 1
    """
    return [r[0] for r in ctx.conn.execute(query)]


def fetch_stocks_rfbs(ctx: Context) -> Iterable[Row]:
    path = ctx.path("/v1/product/info/stocks-by-warehouse/fbs")
    for batch in chunks(active_skus(ctx), SKU_BATCH):
        resp = ctx.client.post(path, {"sku": [str(s) for s in batch]})
        for s in resp.get("result", []):
            yield {
                "sku": s["sku"],
                "warehouse_id": s["warehouse_id"],
                "product_id": s.get("product_id"),
                "offer_id": s.get("offer_id"),
                "warehouse_name": s.get("warehouse_name"),
                "present": s.get("present"),
                "reserved": s.get("reserved"),
                "raw": s,
            }


def fetch_stock_management(ctx: Context) -> Iterable[Row]:
    for item in by_products(ctx, ctx.path("/v4/product/info/stocks")):
        for stock in item.get("stocks", []):
            yield {
                "product_id": item["product_id"],
                "type": stock["type"],
                "offer_id": item.get("offer_id"),
                "sku": stock.get("sku"),
                "present": stock.get("present"),
                "reserved": stock.get("reserved"),
                "raw": {**stock, "product_id": item["product_id"], "offer_id": item.get("offer_id")},
            }


PRICES = Loader(
    table="ozon_product_prices",
    key=("product_id",),
    columns=("product_id", "offer_id", "price", "old_price", "min_price", "marketing_price", "currency_code"),
    fetch=fetch_prices,
    depends=("ozon_products",),
)

STOCKS_RFBS = Loader(
    table="ozon_stocks_rfbs",
    key=("sku", "warehouse_id"),
    columns=("sku", "warehouse_id", "product_id", "offer_id", "warehouse_name", "present", "reserved"),
    fetch=fetch_stocks_rfbs,
    depends=("ozon_warehouses", "ozon_products"),
)

STOCK_MANAGEMENT = Loader(
    table="ozon_stock_management",
    key=("product_id", "type"),
    columns=("product_id", "type", "offer_id", "sku", "present", "reserved"),
    fetch=fetch_stock_management,
    depends=("ozon_products",),
)
