from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import structlog

from ozon_sync.config import Settings
from ozon_sync.runner import TableResult

log = structlog.get_logger()

TELEGRAM_LIMIT = 4000


class Telegram:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.token = settings.telegram_bot_token.get_secret_value()
        self.chat_id = settings.telegram_chat_id
        self.http = http or httpx.Client(timeout=15)

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        try:
            return self._send(text)
        except Exception as e:
            log.error("telegram_failed", error=type(e).__name__)
            return False

    def _send(self, text: str) -> bool:
        if not self.enabled:
            log.info("telegram_disabled", text=text)
            return False
        try:
            resp = self.http.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text[:TELEGRAM_LIMIT], "disable_web_page_preview": True},
            )
        except httpx.HTTPError as e:
            log.error("telegram_failed", error=type(e).__name__)
            return False
        if resp.status_code != 200:
            log.error("telegram_failed", status=resp.status_code, body=resp.text[:300])
            return False
        return True


def stale_tables(conn: psycopg.Connection, tables: list[str], hours: int, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    last_ok = dict(
        conn.execute(
            "SELECT table_name, max(finished_at) FROM sync_log WHERE status = 'ok' AND table_name = ANY(%s) GROUP BY 1",
            (tables,),
        ).fetchall()
    )
    threshold = now - timedelta(hours=hours)
    return [t for t in tables if last_ok.get(t) is None or last_ok[t] < threshold]


TITLES = {
    "ozon_warehouses": "Склады",
    "ozon_delivery_methods": "Способы доставки",
    "ozon_products": "Товары",
    "ozon_product_prices": "Цены",
    "ozon_stocks_rfbs": "Остатки FBS/rFBS по складам",
    "ozon_stock_management": "Остатки FBO/FBS",
    "ozon_actions": "Акции",
    "ozon_action_candidates": "Кандидаты в акции",
    "ozon_action_products": "Товары в акциях",
    "gsheet": "Google Таблица",
}

ENVS = {"sandbox": "песочница", "prod": "боевой кабинет"}

ERROR_LIMIT = 300


def title(table: str) -> str:
    return TITLES.get(table, table)


def header(env: str) -> str:
    return f"Ozon → БД ({ENVS.get(env, env)})"


def changes(r: TableResult) -> str:
    parts = []
    if r.inserted:
        parts.append(f"+{r.inserted} новых")
    if r.updated:
        parts.append(f"{r.updated} изменено")
    if r.deleted:
        parts.append(f"{r.deleted} удалено")
    return ", ".join(parts) or "без изменений"


def result_line(r: TableResult) -> str:
    if r.status != "ok":
        return f"❌ {title(r.table)} — ошибка: {(r.error or '')[:ERROR_LIMIT]}"
    if r.table == "gsheet":
        return f"📄 {title(r.table)} — выгружено строк: {r.updated}"
    return f"📦 {title(r.table)} — получено {r.fetched} шт., {changes(r)}"


def failure_message(env: str, failed: list[TableResult]) -> str:
    lines = [f"❌ {header(env)}: ошибки при обновлении ({len(failed)})", ""]
    lines += [result_line(r) for r in failed]
    return "\n".join(lines)


def stale_message(env: str, tables: list[str], hours: int) -> str:
    lines = [f"⏰ {header(env)}: данные не обновлялись дольше {hours} ч", ""]
    lines += [f"• {title(t)}" for t in tables]
    return "\n".join(lines)


def cycle_failed_message(env: str, error: str) -> str:
    return f"🔥 {header(env)}: синхронизация не выполнена\n\n{error[:ERROR_LIMIT]}"


def summary_message(
    env: str, results: list[TableResult], finished_at: datetime | None = None, duration: float | None = None
) -> str:
    tables = [r for r in results if r.table != "gsheet"]
    ok = sum(r.status == "ok" for r in tables)
    all_ok = all(r.status == "ok" for r in results)
    if all_ok:
        status = "все данные обновлены"
    else:
        status = f"обновлено таблиц {ok} из {len(tables)}"
    lines = [f"{'✅' if all_ok else '⚠️'} {header(env)}: {status}"]
    meta = []
    if finished_at:
        meta.append(finished_at.strftime("%d.%m.%Y %H:%M"))
    if duration is not None:
        meta.append(f"за {duration:.0f} с")
    if meta:
        lines.append(" · ".join(meta))
    lines.append("")
    lines += [result_line(r) for r in results]
    return "\n".join(lines)
