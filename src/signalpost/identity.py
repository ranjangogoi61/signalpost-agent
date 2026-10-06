from __future__ import annotations


def exact_entity_match(requested_orgnr: str, payload: dict) -> bool:
    requested = "".join(ch for ch in requested_orgnr if ch.isdigit())
    candidate = str(payload.get("organisasjonsnummer", ""))
    candidate = "".join(ch for ch in candidate if ch.isdigit())
    return requested == candidate and len(candidate) == 9
