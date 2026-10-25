"""Recent official register activity from Enhetsregisteret's open update feed.

One request per chunk of organisation numbers (GET /api/oppdateringer/enheter with
organisasjonsnummer=..., includeChanges=true). Only the change type, the publication date and
the names of the changed register fields are kept; changed values are never copied, so no
personal data leaves the feed.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from .evidence import evidence
from .http import FetchResult, fetch_json

UPDATES_URL = "https://data.brreg.no/enhetsregisteret/api/oppdateringer/enheter"
CHUNK = 100
MAX_EVENTS_KEPT = 10
CHANGE_TYPES = {"Ny": "new registration", "Endring": "change", "Sletting": "struck off", "Fjernet": "removed", "Ukjent": "unknown"}
FIELD_NAMES = {
    "navn": "name",
    "forretningsadresse": "business address",
    "postadresse": "postal address",
    "naeringskode1": "industry",
    "naeringskode2": "secondary industry",
    "naeringskode3": "secondary industry",
    "antallAnsatte": "employee count",
    "harRegistrertAntallAnsatte": "employee count",
    "hjemmeside": "website",
    "epostadresse": "e-mail",
    "organisasjonsform": "legal form",
    "aktivitet": "business activity",
    "vedtektsfestetFormaal": "registered purpose",
    "konkurs": "bankruptcy status",
    "underAvvikling": "liquidation status",
    "underTvangsavviklingEllerTvangsopploesning": "forced liquidation status",
    "registrertIMvaregisteret": "VAT registration",
    "sisteInnsendteAarsregnskap": "annual accounts filed",
    "overordnetEnhet": "parent unit",
    "institusjonellSektorkode": "institutional sector",
    "stiftelsesdato": "founding date",
}
PRIVATE_FIELDS = {"telefon", "mobil"}


def _changed_fields(changes: Any) -> list[str]:
    names: list[str] = []
    for change in changes if isinstance(changes, list) else []:
        path = str((change or {}).get("path") or "").strip("/")
        key = path.split("/", 1)[0]
        if not key or key in PRIVATE_FIELDS or key.startswith("_"):
            continue
        label = FIELD_NAMES.get(key, key)
        if label not in names:
            names.append(label)
    return names


def fetch_registry_updates(
    orgs: list[str],
    *,
    fetcher: Callable[[str], FetchResult] = fetch_json,
    since_days: int = 365,
    today: dt.date | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Return ({org: evidence record}, metrics). A failed chunk marks only its own companies as failed."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    since = today - dt.timedelta(days=since_days)
    since_param = f"{since.isoformat()}T00:00:00.000Z"
    records: dict[str, dict[str, Any]] = {}
    metrics = {"requests": 0, "chunks": 0, "failed_chunks": 0, "events": 0}
    for start in range(0, len(orgs), CHUNK):
        chunk = orgs[start:start + CHUNK]
        url = f"{UPDATES_URL}?dato={since_param}&organisasjonsnummer={','.join(chunk)}&includeChanges=true&size=10000&sort=id,DESC"
        metrics["chunks"] += 1
        metrics["requests"] += 1
        try:
            result = fetcher(url)
        except Exception as exc:  # network or budget error: this chunk fails, the run continues
            result = FetchResult(url, 0, 0, 0, None, error=f"{type(exc).__name__}: {str(exc)[:140]}")
        body = result.body if isinstance(result.body, dict) else None
        if result.status != 200 or body is None:
            metrics["failed_chunks"] += 1
            for org in chunk:
                records[org] = evidence("registry_updates", "source_error", "official_registry_update_feed", url, note=f"update feed request failed: {result.error or result.status}")
            continue
        events: dict[str, list[dict[str, Any]]] = {org: [] for org in chunk}
        for item in (body.get("_embedded") or {}).get("oppdaterteEnheter") or []:
            org = str(item.get("organisasjonsnummer") or "").zfill(9)
            if org not in events:
                continue
            events[org].append({
                "date": str(item.get("dato") or "")[:10],
                "type": CHANGE_TYPES.get(str(item.get("endringstype") or "Ukjent"), str(item.get("endringstype"))),
                "fields": _changed_fields(item.get("endringer")),
                "update_id": item.get("oppdateringsid"),
            })
        for org in chunk:
            found = sorted(events[org], key=lambda e: (e["date"], e.get("update_id") or 0), reverse=True)
            metrics["events"] += len(found)
            if not found:
                records[org] = evidence("registry_updates", "not_found", "official_registry_update_feed", url, value=None, retrieved_at=result.retrieved_at, content_sha256=result.content_sha256, note=f"No register update published since {since.isoformat()}.")
                continue
            changed: list[str] = []
            for event in found:
                for name in event["fields"]:
                    if name not in changed:
                        changed.append(name)
            value = {
                "since": since.isoformat(),
                "update_count": len(found),
                "latest_update": found[0]["date"],
                "latest_type": found[0]["type"],
                "changed_fields": changed,
                "events": [{k: v for k, v in e.items() if k != "update_id"} for e in found[:MAX_EVENTS_KEPT]],
            }
            records[org] = evidence("registry_updates", "available", "official_registry_update_feed", url, value=value, retrieved_at=result.retrieved_at, content_sha256=result.content_sha256, source_row_key=org)
    return records, metrics
