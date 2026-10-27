from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import gspread
import psycopg

STOCKS_SHEET = "Остатки"
WAREHOUSE_SHEET = "Остатки по складам"
STATUS_SHEET = "Статус синхронизации"

STOCKS_QUERY = """
    SELECT p.offer_id, p.product_id, p.name,
           fbo.present, fbo.reserved, fbs.present, fbs.reserved,
           pr.price, pr.currency_code,
           greatest(fbo.updated_at, fbs.updated_at)
    FROM ozon_products p
    LEFT JOIN ozon_stock_management fbo
           ON fbo.product_id = p.product_id AND fbo.type = 'fbo' AND NOT fbo.is_deleted
    LEFT JOIN ozon_stock_management fbs
           ON fbs.product_id = p.product_id AND fbs.type = 'fbs' AND NOT fbs.is_deleted
    LEFT JOIN ozon_product_prices pr ON pr.product_id = p.product_id AND NOT pr.is_deleted
    WHERE NOT p.is_deleted
    ORDER BY p.offer_id, p.product_id
"""

WAREHOUSE_QUERY = """
    SELECT coalesce(w.name, s.warehouse_name), s.warehouse_id, s.offer_id, s.sku,
           p.name, s.present, s.reserved, s.updated_at
    FROM ozon_stocks_rfbs s
    LEFT JOIN ozon_warehouses w ON w.warehouse_id = s.warehouse_id
    LEFT JOIN ozon_products p ON p.product_id = s.product_id
    WHERE NOT s.is_deleted
    ORDER BY 1, s.offer_id
"""

STATUS_QUERY = """
    SELECT table_name, last_success_at, rows_inserted, rows_updated, rows_deleted, last_error_at, last_error
    FROM sync_status
    ORDER BY table_name
"""

SHEETS = [
    (
        STOCKS_SHEET,
        ["Артикул", "product_id", "Название", "FBO в наличии", "FBO резерв", "FBS в наличии", "FBS резерв",
         "Цена", "Валюта", "Обновлено"],
        STOCKS_QUERY,
    ),
    (
        WAREHOUSE_SHEET,
        ["Склад", "warehouse_id", "Артикул", "SKU", "Название", "В наличии", "Резерв", "Обновлено"],
        WAREHOUSE_QUERY,
    ),
    (
        STATUS_SHEET,
        ["Таблица", "Последнее успешное", "Добавлено", "Обновлено", "Удалено", "Последняя ошибка", "Текст ошибки"],
        STATUS_QUERY,
    ),
]


def cell(value: Any, tz: ZoneInfo) -> Any:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    return value


def build_tables(conn: psycopg.Connection, tz: ZoneInfo) -> list[tuple[str, list[list[Any]]]]:
    tables = []
    for title, header, query in SHEETS:
        rows = [[cell(v, tz) for v in row] for row in conn.execute(query)]
        tables.append((title, [header, *rows]))
    return tables


def write_tables(spreadsheet: gspread.Spreadsheet, tables: list[tuple[str, list[list[Any]]]]) -> int:
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    written = 0
    for title, values in tables:
        cols = len(values[0])
        ws = existing.get(title) or spreadsheet.add_worksheet(title, rows=len(values), cols=cols)
        ws.resize(rows=max(len(values), 2), cols=cols)
        ws.update(values, "A1", value_input_option="RAW")
        ws.freeze(rows=1)
        written += len(values) - 1
    return written


def export(conn: psycopg.Connection, sheet_id: str, credentials_file: str, timezone: str) -> int:
    tables = build_tables(conn, ZoneInfo(timezone))
    spreadsheet = gspread.service_account(filename=credentials_file).open_by_key(sheet_id)
    return write_tables(spreadsheet, tables)
