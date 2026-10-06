from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

TerminalStatus = Literal[
    "available",
    "not_available",
    "blocked",
    "not_applicable",
    "ambiguous",
    "failed",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Evidence:
    source_url: str
    retrieved_at: str
    effective_date: str | None
    content_hash: str
    hash_algorithm: str
    extraction_method: str


@dataclass(frozen=True)
class Fact:
    key: str
    value: Any
    evidence: list[Evidence] = field(default_factory=list)


@dataclass(frozen=True)
class CompanyProfile:
    organisation_number: str
    facts: list[Fact] = field(default_factory=list)


@dataclass(frozen=True)
class CompanyResult:
    organisation_number: str
    status: TerminalStatus
    profile: CompanyProfile | None = None
    error: dict[str, Any] | None = None
    run_id: str | None = None
    completed_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
