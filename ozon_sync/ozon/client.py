import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import structlog

from ozon_sync.config import Settings

log = structlog.get_logger()


class OzonError(Exception):
    pass


class OzonClient:
    def __init__(
        self,
        settings: Settings,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings
        self.http = http or httpx.Client(base_url=settings.ozon_base_url, timeout=settings.ozon_timeout)
        self.sleep = sleep
        self.clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    def close(self) -> None:
        self.http.close()

    def _auth_headers(self) -> dict[str, str]:
        s = self.settings
        if s.ozon_env == "prod":
            return {"Client-Id": s.ozon_client_id, "Api-Key": s.ozon_api_key.get_secret_value()}
        if self._token is None or self.clock() >= self._token_expires_at:
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _fetch_token(self) -> None:
        s = self.settings
        resp = self.http.post(
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": s.ozon_sandbox_client_id,
                "client_secret": s.ozon_sandbox_client_secret.get_secret_value(),
            },
        )
        if resp.status_code != 200:
            raise OzonError(f"sandbox oauth failed: {resp.status_code} {resp.text[:500]}")
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = self.clock() + float(body.get("expires_in", 3600)) - 60

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        s = self.settings
        failures = 0
        throttled = 0
        while True:
            try:
                resp = self.http.post(path, json=body or {}, headers=self._auth_headers())
            except httpx.TransportError as e:
                failures += 1
                if failures > s.ozon_max_retries:
                    raise OzonError(f"{path}: network error: {e}") from e
                self._backoff(path, failures, str(e))
                continue

            if resp.status_code == 429:
                throttled += 1
                if throttled > s.ozon_max_429_retries:
                    raise OzonError(f"{path}: 429 after {throttled - 1} retries")
                wait = _float_header(resp, "Retry-After", 1.0)
                log.warning("ozon_rate_limited", path=path, retry_after=wait)
                self.sleep(wait)
                continue

            if resp.status_code == 401 and s.ozon_env == "sandbox" and self._token is not None:
                self._token = None
                failures += 1
                if failures > s.ozon_max_retries:
                    raise OzonError(f"{path}: 401 {resp.text[:500]}")
                continue

            if resp.status_code >= 500:
                failures += 1
                if failures > s.ozon_max_retries:
                    raise OzonError(f"{path}: {resp.status_code} {resp.text[:500]}")
                self._backoff(path, failures, f"http {resp.status_code}")
                continue

            if resp.status_code >= 400:
                raise OzonError(f"{path}: {resp.status_code} {resp.text[:500]}")

            if resp.headers.get("Ratelimit-Remaining") == "0":
                wait = _float_header(resp, "Ratelimit-Reset", 1.0)
                log.info("ozon_rate_limit_exhausted", path=path, wait=wait)
                self.sleep(wait)
            return resp.json()

    def _backoff(self, path: str, attempt: int, reason: str) -> None:
        wait = 2 ** (attempt - 1)
        log.warning("ozon_retry", path=path, attempt=attempt, wait=wait, reason=reason)
        self.sleep(wait)

    def paginate_last_id(
        self,
        path: str,
        body: dict[str, Any],
        items: Callable[[dict[str, Any]], list[Any]],
        last_id: Callable[[dict[str, Any]], str | None] = lambda r: r.get("last_id"),
        cursor_param: str = "last_id",
    ) -> Iterator[Any]:
        cursor = ""
        while True:
            resp = self.post(path, {**body, cursor_param: cursor})
            page = items(resp)
            if not page:
                return
            yield from page
            nxt = last_id(resp)
            if not nxt or nxt == cursor:
                return
            cursor = nxt

    def paginate_offset(
        self,
        path: str,
        body: dict[str, Any],
        items: Callable[[dict[str, Any]], list[Any]],
        limit: int,
    ) -> Iterator[Any]:
        offset = 0
        while True:
            page = items(self.post(path, {**body, "limit": limit, "offset": offset}))
            if not page:
                return
            yield from page
            offset += len(page)


def _float_header(resp: httpx.Response, name: str, default: float) -> float:
    try:
        return max(float(resp.headers[name]), 0.0)
    except (KeyError, ValueError):
        return default
