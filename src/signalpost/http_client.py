from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .budget import BudgetController, BudgetExceeded


class HttpClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class JsonResponse:
    status_code: int
    url: str
    payload: object


class JsonHttpClient:
    def __init__(
        self,
        budget: BudgetController,
        *,
        timeout_seconds: float = 15.0,
        user_agent: str = "signalpost-agent/0.1",
        retries: int = 2,
    ) -> None:
        self._budget = budget
        self._timeout = timeout_seconds
        self._user_agent = user_agent
        self._retries = retries

    def get_json(self, url: str) -> JsonResponse:
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                self._budget.acquire_request()
                req = Request(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": self._user_agent,
                    },
                    method="GET",
                )
                with urlopen(req, timeout=self._timeout) as response:
                    raw = response.read()
                    payload = json.loads(raw.decode("utf-8"))
                    return JsonResponse(response.status, response.geturl(), payload)
            except BudgetExceeded:
                raise
            except HTTPError as exc:
                if exc.code in {429, 502, 503, 504} and attempt < self._retries:
                    last_error = exc
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise HttpClientError(
                    f"HTTP {exc.code} for {url}",
                    status_code=exc.code,
                ) from exc
            except (URLError, TimeoutError, ValueError, OSError) as exc:
                last_error = exc
                if attempt < self._retries:
                    time.sleep(0.5 * (2**attempt))
                    continue
                raise HttpClientError(f"request failed for {url}: {exc}") from exc
        raise HttpClientError(f"request failed for {url}: {last_error}")
