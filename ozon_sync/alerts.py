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


def failure_message(env: str, failed: list[TableResult]) -> str:
    lines = [f"❌ Ozon sync ({env}): упало таблиц: {len(failed)}"]
    lines += [f"• {r.table}: {r.error}" for r in failed]
    return "\n".join(lines)


def stale_message(env: str, tables: list[str], hours: int) -> str:
    return f"⏰ Ozon sync ({env}): не обновлялись дольше {hours} ч:\n" + "\n".join(f"• {t}" for t in tables)


def summary_message(env: str, results: list[TableResult]) -> str:
    ok = sum(r.status == "ok" for r in results)
    lines = [f"{'✅' if ok == len(results) else '⚠️'} Ozon sync ({env}): {ok}/{len(results)} таблиц ok"]
    for r in results:
        if r.status == "ok":
            lines.append(f"• {r.table}: +{r.inserted} ~{r.updated} -{r.deleted}")
        else:
            lines.append(f"• {r.table}: ошибка")
    return "\n".join(lines)
