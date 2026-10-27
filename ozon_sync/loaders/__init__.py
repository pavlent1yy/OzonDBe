from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import psycopg

from ozon_sync.ozon.client import OzonClient

Row = dict[str, Any]


@dataclass(frozen=True)
class Context:
    client: OzonClient
    conn: psycopg.Connection
    method_overrides: dict[str, str]

    def path(self, default: str) -> str:
        return self.method_overrides.get(default, default)


@dataclass(frozen=True)
class Loader:
    table: str
    key: tuple[str, ...]
    columns: tuple[str, ...]
    fetch: Callable[[Context], Iterable[Row]]
    depends: tuple[str, ...] = ()
    allow_empty: bool = False


def active_ids(ctx: Context, table: str, column: str) -> list[int]:
    return [r[0] for r in ctx.conn.execute(f"SELECT {column} FROM {table} WHERE NOT is_deleted ORDER BY 1")]


def chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def registry() -> dict[str, Loader]:
    from ozon_sync.loaders import actions, prices_stocks, products, warehouses

    loaders = [
        warehouses.WAREHOUSES,
        warehouses.DELIVERY_METHODS,
        products.PRODUCTS,
        prices_stocks.PRICES,
        prices_stocks.STOCKS_RFBS,
        prices_stocks.STOCK_MANAGEMENT,
        actions.ACTIONS,
        actions.ACTION_CANDIDATES,
        actions.ACTION_PRODUCTS,
    ]
    return {ld.table: ld for ld in loaders}
