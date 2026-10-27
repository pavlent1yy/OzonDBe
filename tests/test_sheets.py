import uuid
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from ozon_sync import db, service, sheets
from ozon_sync.config import Settings

MSK = ZoneInfo("Europe/Moscow")


class FakeWorksheet:
    def __init__(self, title, rows=1, cols=1):
        self.title = title
        self.values = []
        self.size = (rows, cols)
        self.frozen = 0

    def resize(self, rows, cols):
        self.size = (rows, cols)
        self.values = self.values[:rows]

    def update(self, values, start, value_input_option):
        assert start == "A1" and value_input_option == "RAW"
        self.values = values + self.values[len(values):]

    def freeze(self, rows):
        self.frozen = rows


class FakeSpreadsheet:
    def __init__(self, *existing):
        self.sheets = {ws.title: ws for ws in existing}

    def worksheets(self):
        return list(self.sheets.values())

    def add_worksheet(self, title, rows, cols):
        self.sheets[title] = FakeWorksheet(title, rows, cols)
        return self.sheets[title]


def test_cell_conversion():
    assert sheets.cell(None, MSK) == ""
    assert sheets.cell(Decimal("19.90"), MSK) == 19.9
    assert sheets.cell(datetime(2026, 10, 27, 7, 0, tzinfo=UTC), MSK) == "2026-10-27 10:00"


def test_write_replaces_old_rows_and_creates_missing_sheets():
    old = FakeWorksheet(sheets.STOCKS_SHEET)
    old.values = [["h"], ["old1"], ["old2"], ["old3"]]
    book = FakeSpreadsheet(old)
    written = sheets.write_tables(book, [(sheets.STOCKS_SHEET, [["h"], ["new"]]), ("Новый", [["a", "b"]])])
    assert written == 1
    assert old.values == [["h"], ["new"]] and old.frozen == 1
    assert book.sheets["Новый"].values == [["a", "b"]]
    assert book.sheets["Новый"].size == (2, 2)


def sync(conn, table, key, columns, rows):
    db.sync_table(conn, table, key, columns, [{**r, "raw": {}} for r in rows])


def test_build_tables_from_real_schema(migrated):
    conn = migrated
    sync(conn, "ozon_products", ("product_id",), ("product_id", "offer_id", "name", "archived"), [
        {"product_id": 1, "offer_id": "A-1", "name": "Часы", "archived": False},
        {"product_id": 2, "offer_id": "B-2", "name": "Ремешок", "archived": False},
    ])
    sync(conn, "ozon_stock_management", ("product_id", "type"),
         ("product_id", "type", "offer_id", "sku", "present", "reserved"), [
        {"product_id": 1, "type": "fbo", "offer_id": "A-1", "sku": 10, "present": 40, "reserved": 1},
        {"product_id": 1, "type": "fbs", "offer_id": "A-1", "sku": 10, "present": 12, "reserved": 2},
    ])
    sync(conn, "ozon_product_prices", ("product_id",), ("product_id", "offer_id", "price", "currency_code"), [
        {"product_id": 1, "offer_id": "A-1", "price": Decimal("1990.00"), "currency_code": "RUB"},
    ])
    sync(conn, "ozon_warehouses", ("warehouse_id",), ("warehouse_id", "name"), [{"warehouse_id": 7, "name": "Москва"}])
    sync(conn, "ozon_stocks_rfbs", ("sku", "warehouse_id"),
         ("sku", "warehouse_id", "product_id", "offer_id", "present", "reserved"), [
        {"sku": 10, "warehouse_id": 7, "product_id": 1, "offer_id": "A-1", "present": 12, "reserved": 2},
    ])
    log_id = db.log_start(conn, uuid.uuid4(), "ozon_products")
    db.log_finish(conn, log_id, status="ok", inserted=2)

    tables = dict(sheets.build_tables(conn, MSK))
    stocks = tables[sheets.STOCKS_SHEET]
    assert stocks[1][:9] == ["A-1", 1, "Часы", 40, 1, 12, 2, 1990.0, "RUB"]
    assert stocks[2][:9] == ["B-2", 2, "Ремешок", "", "", "", "", "", ""]
    assert tables[sheets.WAREHOUSE_SHEET][1][:7] == ["Москва", 7, "A-1", 10, "Часы", 12, 2]
    assert tables[sheets.STATUS_SHEET][1][:3][::2] == ["ozon_products", 2]


def test_sheet_error_logged_and_alerted(migrated, monkeypatch):
    def boom(*a):
        raise PermissionError("нет доступа к таблице")

    monkeypatch.setattr(service.sheets, "export", boom)
    result = service.export_sheet(migrated, Settings(_env_file=None, gsheet_id="x"), uuid.uuid4())
    assert result.status == "error" and "нет доступа" in result.error
    assert migrated.execute("SELECT table_name, status FROM sync_log").fetchone() == ("gsheet", "error")
