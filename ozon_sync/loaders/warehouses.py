from collections.abc import Iterable

from ozon_sync.loaders import Context, Loader, Row, active_ids

DELIVERY_METHODS_PAGE = 50


def fetch_warehouses(ctx: Context) -> Iterable[Row]:
    resp = ctx.client.post(ctx.path("/v1/warehouse/list"))
    for w in resp.get("result", []):
        yield {
            "warehouse_id": w["warehouse_id"],
            "name": w.get("name"),
            "is_rfbs": w.get("is_rfbs"),
            "status": w.get("status"),
            "raw": w,
        }


def fetch_delivery_methods(ctx: Context) -> Iterable[Row]:
    path = ctx.path("/v1/delivery-method/list")
    for warehouse_id in active_ids(ctx, "ozon_warehouses", "warehouse_id"):
        items = ctx.client.paginate_offset(
            path,
            {"filter": {"warehouse_id": warehouse_id}},
            lambda r: r.get("result", []),
            limit=DELIVERY_METHODS_PAGE,
        )
        for m in items:
            yield {
                "id": m["id"],
                "warehouse_id": m.get("warehouse_id", warehouse_id),
                "name": m.get("name"),
                "status": m.get("status"),
                "provider_id": m.get("provider_id"),
                "raw": m,
            }


WAREHOUSES = Loader(
    table="ozon_warehouses",
    key=("warehouse_id",),
    columns=("warehouse_id", "name", "is_rfbs", "status"),
    fetch=fetch_warehouses,
    mock=True,
)

DELIVERY_METHODS = Loader(
    table="ozon_delivery_methods",
    key=("id",),
    columns=("id", "warehouse_id", "name", "status", "provider_id"),
    fetch=fetch_delivery_methods,
    depends=("ozon_warehouses",),
)
