from collections.abc import Iterable
from datetime import datetime
from typing import Any

from ozon_sync.loaders import Context, Loader, Row, active_ids
from ozon_sync.loaders.prices_stocks import money

ACTION_PAGE = 100


def timestamp(value: Any) -> datetime | None:
    if not value or not str(value).strip():
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def amount(obj: Any):
    return money(obj.get("amount")) if isinstance(obj, dict) else None


def fetch_actions(ctx: Context) -> Iterable[Row]:
    for a in ctx.client.get(ctx.path("/v1/actions")).get("result", []):
        yield {
            "action_id": int(a["id"]),
            "title": a.get("title"),
            "action_type": a.get("action_type"),
            "date_start": timestamp(a.get("date_start")),
            "date_end": timestamp(a.get("date_end")),
            "is_participating": a.get("is_participating"),
            "raw": a,
        }


def action_product_row(action_id: int, p: dict) -> Row:
    price = p.get("price")
    return {
        "action_id": action_id,
        "product_id": int(p["id"]),
        "price": amount(price),
        "action_price": amount(p.get("action_price")),
        "max_action_price": amount(p.get("max_action_price")),
        "currency": price.get("currency") if isinstance(price, dict) else None,
        "raw": p,
    }


def by_actions(ctx: Context, path: str) -> Iterable[tuple[int, dict]]:
    for action_id in active_ids(ctx, "ozon_actions", "action_id"):
        products = ctx.client.paginate_last_id(
            path, {"action_id": action_id, "limit": ACTION_PAGE}, lambda r: r.get("products", [])
        )
        for p in products:
            yield action_id, p


def fetch_candidates(ctx: Context) -> Iterable[Row]:
    for action_id, p in by_actions(ctx, ctx.path("/v2/actions/candidates")):
        yield action_product_row(action_id, p)


def fetch_action_products(ctx: Context) -> Iterable[Row]:
    for action_id, p in by_actions(ctx, ctx.path("/v2/actions/products")):
        yield {**action_product_row(action_id, p), "stock": p.get("stock"), "add_mode": p.get("add_mode")}


ACTION_PRODUCT_COLUMNS = ("action_id", "product_id", "price", "action_price", "max_action_price", "currency")

ACTIONS = Loader(
    table="ozon_actions",
    key=("action_id",),
    columns=("action_id", "title", "action_type", "date_start", "date_end", "is_participating"),
    fetch=fetch_actions,
    allow_empty=True,
)

ACTION_CANDIDATES = Loader(
    table="ozon_action_candidates",
    key=("action_id", "product_id"),
    columns=ACTION_PRODUCT_COLUMNS,
    fetch=fetch_candidates,
    depends=("ozon_actions",),
    allow_empty=True,
)

ACTION_PRODUCTS = Loader(
    table="ozon_action_products",
    key=("action_id", "product_id"),
    columns=(*ACTION_PRODUCT_COLUMNS, "stock", "add_mode"),
    fetch=fetch_action_products,
    depends=("ozon_actions",),
    allow_empty=True,
)
