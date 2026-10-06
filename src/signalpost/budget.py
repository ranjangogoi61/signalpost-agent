from __future__ import annotations

import threading
import time


class BudgetExceeded(RuntimeError):
    """Raised when a request would exceed the configured run budget."""


class BudgetController:
    def __init__(
        self,
        *,
        max_requests: int | None = None,
        max_runtime_seconds: float | None = None,
    ) -> None:
        self._max_requests = max_requests
        self._deadline = (
            time.monotonic() + max_runtime_seconds
            if max_runtime_seconds is not None
            else None
        )
        self._requests = 0
        self._lock = threading.Lock()

    @property
    def requests_used(self) -> int:
        with self._lock:
            return self._requests

    def remaining_seconds(self) -> float | None:
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())

    def acquire_request(self) -> None:
        with self._lock:
            if self._deadline is not None and time.monotonic() >= self._deadline:
                raise BudgetExceeded("runtime budget exhausted")
            if self._max_requests is not None and self._requests >= self._max_requests:
                raise BudgetExceeded("request budget exhausted")
            self._requests += 1

    def ensure_time_available(self) -> None:
        remaining = self.remaining_seconds()
        if remaining is not None and remaining <= 0:
            raise BudgetExceeded("runtime budget exhausted")
