# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Состояние

ТЗ: `docs/ТЗ выгрузка Ozon → PostgreSQL + Telegram.docx`. Решено: Postgres служит источником правды, плюс отдельным шагом выгружаем остатки в Google Таблицу. Все этапы плана готовы: 9 загрузчиков, расписание, Telegram, выгрузка в Sheets, тесты, README.

## Команды

```
uv sync --python 3.12                 # зависимости (проект закреплён на 3.12)
uv run pytest -q                      # все тесты, без сети
uv run pytest tests/test_client.py::test_429_waits_retry_after
TEST_DATABASE_URL=postgresql://... uv run pytest   # плюс тесты upsert на живом Postgres (иначе skip)
uv run --with pgserver python -c "import pgserver; print(pgserver.get_server('.pg', cleanup_mode=None).get_uri())"  # Postgres без Docker
uv run ozon-sync sync --all           # или --table ozon_products (можно несколько)
uv run ozon-sync schedule             # планировщик (так стартует контейнер app)
uv run alembic upgrade head           # миграции (DATABASE_URL из .env)
uv run alembic upgrade head --sql     # посмотреть SQL без БД
uv run ozon-sync ping                 # проверить доступ к Ozon API
docker compose up --build
```

Миграции пишутся на raw SQL через `op.execute`, без SQLAlchemy-моделей. Роль `analytics_ro` создаёт/обновляет `ozon-sync ro-role` при каждом старте контейнера, если задан `ANALYTICS_RO_PASSWORD`.

## Что делаем

Сервис 3 раза в день (10:00, 14:00, 18:00 МСК, задаётся в конфиге) и по ручному запуску (`sync --all` / `sync --table ozon_products`) забирает данные из Ozon Seller API в PostgreSQL 16. В нём 9 таблиц данных и журнал `sync_log`, по ошибкам шлёт алерты в Telegram.

Стек: Python 3.12, httpx, psycopg 3 без ORM, Alembic, APScheduler в контейнере, gspread, structlog, pytest + respx, Docker Compose (`db` + `app`).

## Как устроено

- `ozon_sync/loaders/`: каждая таблица описывается `Loader(table, key, columns, fetch, depends)`. `fetch(ctx)` отдаёт dict с колонками и `raw`. Новый загрузчик регистрируется в `loaders.registry()`, плюс к нему нужна миграция.
- Режим песочницы: при `OZON_ENV=sandbox` запускаются только загрузчики с `sandbox=True` (`ozon_products` без `/v3/product/info/list`, `ozon_stock_management`), остальные пропускаются в `service.available_loaders`. Песочница поддерживает только эти 2 метода, отдаёт токен в form-urlencoded и стоит за антибот-редиректом 307.
- Режим мока: `OZON_ENV=mock` + `node tools/ozon-sandbox-mock.js` (localhost:8080, в Docker `--profile mock` и `http://mock:8080`, авторизация как в prod, мок её не проверяет). Запускаются загрузчики с `mock=True`: всё, кроме способов доставки и акций.
- Пути методов берутся через `ctx.path(default)`. В конфиге их можно переопределить через `OZON_METHOD_OVERRIDES` (JSON `{"/v1/x": "/v2/x"}`), не трогая код.
- `run_cycle` берёт `pg_try_advisory_lock`: второй параллельный цикл (ручной + плановый) сразу выходит. Под локом все `running` в `sync_log` закрываются как прерванные.
- `runner.run_table` сначала целиком материализует `fetch` (API не дёргается внутри транзакции), затем вызывает `db.sync_table`. Тот кладёт строки через COPY во временную таблицу, делает upsert и помечает `is_deleted` в одной транзакции.

## Архитектурные инварианты (из ТЗ)

- **Загрузчик на таблицу**: декларация (таблица, ключ upsert, зависимости, fetch). Runner выстраивает таблицы по зависимостям: склады и товары идут первыми, цены и остатки берут ID товаров, способы доставки берут ID складов, кандидаты и товары акций берут ID акций.
- **Зависимые таблицы берут ID из БД** (`NOT is_deleted`), а не из памяти. Тогда, если родительская таблица упала, используется её последняя успешная загрузка.
- **Каждая таблица грузится в своей транзакции.** Если таблица упала, откатывается только она, в `sync_log` пишется error, уходит алерт, а цикл идёт дальше.
- **Upsert по естественному ключу** (`ON CONFLICT DO UPDATE`). Повторный запуск без изменений в кабинете не должен менять ни одной строки. Записи, которых больше нет в ответе API, получают `is_deleted = true`: только после полностью успешной загрузки и без DELETE.
- **Общие колонки каждой таблицы данных**: `raw jsonb` (полный ответ по записи), `first_seen_at`, `updated_at`, `is_deleted`. Ключевые поля хранятся отдельными колонками.
- **Пагинация** через `last_id`/offset до пустой страницы. Поле `total` не использовать: Ozon объявил его устаревшим.
- **Ozon-клиент**: учитывать `Ratelimit-Remaining`. На 429 ждать `Retry-After` и повторять. На 5xx и сетевые ошибки делать до 3 повторов с экспоненциальной паузой.
- **Режим работы** `OZON_ENV=sandbox|prod|mock` переключается только конфигом. Prod авторизуется заголовками `Client-Id` + `Api-Key`, sandbox берёт OAuth client credentials через `api-seller-sandbox.ozon.ru/oauth/token`.
- **Только чтение**: сервис ничего не пишет в кабинет Ozon.
- **Секреты** хранятся только в `.env`, в репозитории лежит `.env.example`. Ключи не попадают в логи и в `sync_log`.
- **Postgres** не слушает внешний интерфейс. Для аналитики заказчика есть отдельная роль только на чтение.
- **Выгрузка в Sheets** (`ozon_sync/sheets.py`, включается через `GSHEET_ID`) перезаписывает 3 листа: остатки по товарам, остатки по складам, статус синхронизации. Идёт после цикла и пишет только остатки, без raw. Её ошибка пишется в `sync_log` с `table_name='gsheet'` и не трогает БД.

## Таблицы и методы API

Версии методов предварительные, сверяй их с docs.ozon.ru/api/seller. v1 candidates/products отключены 19.10.2026, новая логика акций v2 на живом API ещё не проверена.

| Таблица | Метод | Ключ |
|---|---|---|
| ozon_warehouses | /v1/warehouse/list | warehouse_id |
| ozon_delivery_methods | /v1/delivery-method/list | id |
| ozon_products | /v3/product/list + /v3/product/info/list | product_id |
| ozon_product_prices | /v5/product/info/prices | product_id |
| ozon_stocks_rfbs | /v1/product/info/stocks-by-warehouse/fbs | sku + warehouse_id |
| ozon_stock_management | /v4/product/info/stocks | product_id + type |
| ozon_actions | GET /v1/actions | action_id |
| ozon_action_candidates | /v2/actions/candidates | action_id + product_id |
| ozon_action_products | /v2/actions/products | action_id + product_id |

`sync_log`: id, run_id, table_name, started_at, finished_at, status (ok/error), rows_inserted, rows_updated, rows_deleted, error. Представление `sync_status` показывает по каждой таблице последнее успешное обновление и последнюю ошибку.

## Тесты

Тесты должны проходить без сети: ответы Ozon лежат в фикстурах `tests/fixtures/`, httpx мокается через respx. Обязательные сценарии: повторный запуск не создаёт дублей, падение одной таблицы не роняет остальные, 429 отрабатывается. Цены и акции в песочнице, скорее всего, недоступны, для них используются фикстуры из примеров в доке Ozon.
