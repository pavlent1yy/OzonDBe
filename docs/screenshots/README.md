# Скриншоты

Данные из локального мока Ozon API (200 товаров, `OZON_ENV=mock`)

| Файл | Что на нём |
|---|---|
| `01_sync_status.png` | представление `sync_status`: последнее обновление и ошибка по каждой таблице |
| `02_sync_log.png` | журнал запусков: первый прогон вставляет строки, повторные — 0/0/0 |
| `03_ozon_products.png` | товары |
| `04_ozon_product_prices.png` | цены |
| `05_ozon_stocks_rfbs.png` | остатки FBS по складам |
| `06_ozon_stock_management.png` | остатки FBO/FBS |
| `07_ozon_warehouses.png` | склады |
| `08_raw_jsonb.png` | полный ответ API в колонке `raw` |
| `09_cli_sync.png` | ручной запуск `ozon-sync sync --all`, JSON-логи |
| `10_pytest.png` | тесты |
| `11_telegram.png` | сводка цикла в Telegram |
| `12_google_sheet.png` | выгрузка остатков в Google Таблицу |
