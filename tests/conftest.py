import json
import os
from pathlib import Path

import httpx
import psycopg
import pytest

from ozon_sync.config import Settings
from ozon_sync.loaders import Context
from ozon_sync.ozon.client import OzonClient

BASE = "https://ozon.test"
FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def client():
    settings = Settings(_env_file=None, ozon_env="prod", ozon_client_id="cid", ozon_api_key="key")
    c = OzonClient(settings, http=httpx.Client(base_url=BASE), sleep=lambda _: None)
    yield c
    c.close()


class FakeConn:
    def __init__(self, ids: dict[str, list[int]]):
        self.ids = ids

    def execute(self, query: str):
        match = next((k for k in self.ids if k in query), None)
        return [(i,) for i in self.ids.get(match, [])]


@pytest.fixture
def fake_ctx(client):
    def make(ids=None, overrides=None):
        return Context(client, FakeConn(ids or {}), overrides or {})

    return make


@pytest.fixture
def pg():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL не задан")
    conn = psycopg.connect(url, autocommit=True)
    conn.execute("DROP SCHEMA IF EXISTS test_sync CASCADE")
    conn.execute("CREATE SCHEMA test_sync")
    conn.execute("SET search_path TO test_sync")
    yield conn
    conn.execute("DROP SCHEMA test_sync CASCADE")
    conn.close()
