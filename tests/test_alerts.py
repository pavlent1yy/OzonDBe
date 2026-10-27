import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
import respx

from ozon_sync import alerts, service
from ozon_sync.config import Settings
from ozon_sync.runner import TableResult

TG = "https://api.telegram.org/botSECRET123/sendMessage"


def settings(**kw):
    return Settings(_env_file=None, telegram_bot_token="SECRET123", telegram_chat_id="42", **kw)


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True


@respx.mock
def test_telegram_send():
    route = respx.post(TG).respond(json={"ok": True})
    assert alerts.Telegram(settings()).send("привет")
    assert json.loads(route.calls.last.request.content)["chat_id"] == "42"


@respx.mock
def test_telegram_error_does_not_raise_or_leak_token(capsys):
    from ozon_sync.logging import setup_logging

    setup_logging()
    respx.post(TG).mock(side_effect=httpx.ConnectError(f"cannot connect to {TG}"))
    assert alerts.Telegram(settings()).send("x") is False
    assert "SECRET123" not in capsys.readouterr().out


def test_telegram_disabled_without_chat():
    assert alerts.Telegram(Settings(_env_file=None)).send("x") is False


def test_summary_and_failure_messages():
    results = [TableResult("a", "ok", 1, 2, 3), TableResult("b", "error", error="boom")]
    summary = alerts.summary_message("prod", results)
    assert "1/2" in summary and "a: +1 ~2 -3" in summary and "b: ошибка" in summary
    assert "b: boom" in alerts.failure_message("prod", results[1:])


def test_schedule_times_parsing():
    assert settings(sync_schedule="10:00, 14:30").schedule_times == [(10, 0), (14, 30)]


def test_scheduler_jobs_in_moscow_time():
    sched = service.build_scheduler(settings())
    jobs = sorted(sched.get_jobs(), key=lambda j: j.id)
    assert [j.id for j in jobs] == ["sync_1000", "sync_1400", "sync_1800"]
    next_run = jobs[0].trigger.get_next_fire_time(None, datetime(2026, 10, 27, 6, 0, tzinfo=UTC))
    assert next_run.astimezone(UTC) == datetime(2026, 10, 27, 7, 0, tzinfo=UTC)
    assert jobs[0].max_instances == 1


@pytest.fixture
def log_table(pg):
    pg.execute("""CREATE TABLE sync_log (id bigserial PRIMARY KEY, run_id uuid, table_name text,
        started_at timestamptz, finished_at timestamptz, status text, rows_inserted int,
        rows_updated int, rows_deleted int, error text)""")
    return pg


def test_stale_tables(log_table):
    now = datetime(2026, 10, 27, 12, tzinfo=UTC)
    for table, status, ago in [("fresh", "ok", 1), ("old", "ok", 20), ("old", "error", 1), ("broken", "error", 1)]:
        log_table.execute(
            "INSERT INTO sync_log (run_id, table_name, status, finished_at) VALUES (%s, %s, %s, %s)",
            (uuid.uuid4(), table, status, now - timedelta(hours=ago)),
        )
    assert alerts.stale_tables(log_table, ["fresh", "old", "broken", "never"], 12, now) == ["old", "broken", "never"]


@pytest.mark.parametrize("selected, checks_stale", [(None, True), (["ozon_warehouses"], False)])
def test_stale_checked_only_on_full_cycle(monkeypatch, selected, checks_stale):
    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    calls = []
    monkeypatch.setattr(service.db, "connect", lambda _: Conn())
    monkeypatch.setattr(service.runner, "run", lambda ctx, lds, *a: [TableResult(ld.table, "ok") for ld in lds])
    monkeypatch.setattr(service.alerts, "stale_tables", lambda *a: calls.append(a) or ["x"])
    tg = FakeTelegram()
    assert service.run_cycle(settings(telegram_summary=False), selected, client=object(), telegram=tg)
    assert bool(calls) is checks_stale
    assert bool(tg.sent) is checks_stale


def test_cycle_failure_alerts_when_db_down(monkeypatch):
    def down(_):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(service.db, "connect", down)
    tg = FakeTelegram()
    assert service.run_cycle(settings(), client=object(), telegram=tg) is False
    assert len(tg.sent) == 1 and "цикл упал" in tg.sent[0]
