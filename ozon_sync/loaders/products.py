from collections.abc import Iterable

from ozon_sync.loaders import Context, Loader, Row, chunks

LIST_PAGE = 1000
INFO_BATCH = 1000


def fetch_products(ctx: Context) -> Iterable[Row]:
    listed = list(
        ctx.client.paginate_last_id(
            ctx.path("/v3/product/list"),
            {"filter": {"visibility": "ALL"}, "limit": LIST_PAGE},
            lambda r: r.get("result", {}).get("items", []),
            lambda r: r.get("result", {}).get("last_id"),
        )
    )
    info_path = ctx.path("/v3/product/info/list")
    for batch in chunks(listed, INFO_BATCH):
        info = {}
        if not ctx.sandbox:
            resp = ctx.client.post(info_path, {"product_id": [str(p["product_id"]) for p in batch]})
            info = {i["id"]: i for i in resp.get("items", [])}
        for p in batch:
            details = info.get(p["product_id"], {})
            yield {
                "product_id": p["product_id"],
                "offer_id": p.get("offer_id") or details.get("offer_id"),
                "name": details.get("name"),
                "archived": p.get("archived", details.get("is_archived")),
                "raw": {"list": p, "info": details},
            }


PRODUCTS = Loader(
    table="ozon_products",
    key=("product_id",),
    columns=("product_id", "offer_id", "name", "archived"),
    fetch=fetch_products,
    mock=True,
    sandbox=True,
)
