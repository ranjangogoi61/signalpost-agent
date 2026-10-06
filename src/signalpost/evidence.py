from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import Evidence, utc_now


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_hash(value: Any) -> tuple[str, str]:
    """Return a stable content hash.

    SHA-256 is used as an implementation choice. The competition requirement is
    the existence of a content hash; this module does not claim SHA-256 is a
    mandated Builderr algorithm.
    """
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest(), "sha256"


def make_evidence(
    *,
    source_url: str,
    payload: Any,
    effective_date: str | None,
    extraction_method: str,
) -> Evidence:
    digest, algorithm = content_hash(payload)
    return Evidence(
        source_url=source_url,
        retrieved_at=utc_now(),
        effective_date=effective_date,
        content_hash=digest,
        hash_algorithm=algorithm,
        extraction_method=extraction_method,
    )
