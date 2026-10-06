from __future__ import annotations

import os
from dataclasses import dataclass


def _int_or_none(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _float_or_none(name: str) -> float | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


@dataclass(frozen=True)
class Settings:
    brreg_base_url: str = "https://data.brreg.no/enhetsregisteret/api"
    http_timeout_seconds: float = 15.0
    max_concurrency: int = 8
    max_requests: int | None = None
    max_runtime_seconds: float | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        concurrency = int(os.getenv("SIGNALPOST_MAX_CONCURRENCY", "8"))
        if concurrency <= 0:
            raise ValueError("SIGNALPOST_MAX_CONCURRENCY must be positive")
        timeout = float(os.getenv("SIGNALPOST_HTTP_TIMEOUT", "15"))
        if timeout <= 0:
            raise ValueError("SIGNALPOST_HTTP_TIMEOUT must be positive")
        return cls(
            brreg_base_url=os.getenv(
                "SIGNALPOST_BRREG_BASE_URL",
                "https://data.brreg.no/enhetsregisteret/api",
            ).rstrip("/"),
            http_timeout_seconds=timeout,
            max_concurrency=concurrency,
            max_requests=_int_or_none("SIGNALPOST_MAX_REQUESTS"),
            max_runtime_seconds=_float_or_none("SIGNALPOST_MAX_RUNTIME_SECONDS"),
        )
