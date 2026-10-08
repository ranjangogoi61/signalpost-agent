"""Hardened Signalpost batch runner built on the Builderr reference agent.

Guarantees (each covered by tests/test_signalpost_run.py):
  * exactly one terminal envelope per input row, in input order, never a crash
    for a bad, duplicate, unknown or deleted organisation number;
  * every module carries one of the six contract availability states;
  * a global request and wall-clock guard (retries and redirects included) that
    degrades the optional website phase before the official phase;
  * an unverified website is `ambiguous`, never published as a claim;
  * contract-shaped fields (run, claims, evidence, changes, errors, operations)
    are added next to the reference agent's own envelope fields.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable

from .batch import evidence_terminal_state, terminal_envelope
from .evidence import evidence, utc_now
from .http import FetchResult, fetch_json
from .identity import apply_website_identity_gate
from .official import (
    BRREG_ENTITY,
    accounting_obligation_assessment,
    fetch_official_modules,
)
from .refresh import diff_profile
from .sampling import iter_bulk
from .website import fetch_website

AVAILABILITY_STATES = ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")
BRREG_SEARCH = "https://data.brreg.no/enhetsregisteret/api/enheter"

STATE_TO_AVAILABILITY = {
    "complete": "available",
    "not_applicable": "not_applicable",
    "not_found": "not_available",
    "blocked_policy": "blocked",
    "blocked_robots": "blocked",
    "source_error": "failed",
    "budget_exhausted": "failed",
    "submission_error": "failed",
}

OFFICIAL_MODULES = ("registry_live", "financials", "financial_history", "roles", "group", "locations")


class BudgetExceeded(urllib.error.URLError):
    """Raised inside urllib when the request or time budget is spent."""


class Budget:
    """Thread-safe request/time guard installed under urllib (counts retries and redirects)."""

    def __init__(self, max_requests: int, max_seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_requests = max_requests
        self.max_seconds = max_seconds
        self._clock = clock
        self._start = clock()
        self._lock = threading.Lock()
        self.requests = 0
        self.refused = 0

    def elapsed(self) -> float:
        return self._clock() - self._start

    def time_left(self) -> float:
        return self.max_seconds - self.elapsed()

    def exhausted(self) -> bool:
        return self.requests >= self.max_requests or self.time_left() <= 0

    def fraction_used(self) -> float:
        return max(self.requests / self.max_requests if self.max_requests else 1.0, self.elapsed() / self.max_seconds if self.max_seconds else 1.0)

    def acquire(self) -> None:
        with self._lock:
            if self.requests >= self.max_requests:
                self.refused += 1
                raise BudgetExceeded("budget_exhausted: request limit reached")
            if self.time_left() <= 0:
                self.refused += 1
                raise BudgetExceeded("budget_exhausted: time limit reached")
            self.requests += 1

    def install(self) -> Callable[[], None]:
        original = urllib.request.OpenerDirector.open
        budget = self

        def counted(opener, fullurl, data=None, timeout=urllib.request.socket._GLOBAL_DEFAULT_TIMEOUT):  # type: ignore[attr-defined]
            budget.acquire()
            return original(opener, fullurl, data, timeout)

        urllib.request.OpenerDirector.open = counted  # type: ignore[method-assign]

        def uninstall() -> None:
            urllib.request.OpenerDirector.open = original  # type: ignore[method-assign]

        return uninstall


# --------------------------------------------------------------------------- inputs

def read_rows(path: str | Path) -> list[dict[str, Any]]:
    """Read JSON, JSONL or text input. Never raises on a bad row; keeps one row per line."""
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    values: list[Any]
    if source.suffix == ".json":
        body = json.loads(text)
        values = body if isinstance(body, list) else body.get("organisation_numbers", [])
    elif source.suffix == ".jsonl":
        values = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError:
                values.append(line.strip())
    else:
        values = [line.strip() for line in text.splitlines() if line.strip()]
    rows = []
    for value in values:
        raw = value.get("organisation_number") if isinstance(value, dict) else value
        digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
        row: dict[str, Any] = {"raw": str(raw), "organisation_number": digits if len(digits) == 9 else None}
        if isinstance(value, dict):
            for key in ("evaluation_split", "sample_slice"):
                if value.get(key) is not None:
                    row[key] = value[key]
        rows.append(row)
    return rows


# ------------------------------------------------------------------ registry anchor

def _addr_part(row: dict[str, Any], key: str, part: str) -> str:
    value = row.get(key)
    return str(value.get(part) or "") if isinstance(value, dict) else ""


def profile_from_api_row(row: dict[str, Any], url: str, *, retrieved_at: str | None = None, note: str | None = None) -> dict[str, Any]:
    org = str(row.get("organisasjonsnummer") or "").zfill(9)
    digest = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    employees = row.get("antallAnsatte")
    profile = {
        "organisation_number": org,
        "name": row.get("navn") or "",
        "legal_form": (row.get("organisasjonsform") or {}).get("kode") or "",
        "employees": employees if isinstance(employees, int) else None,
        "bankrupt": bool(row.get("konkurs")),
        "liquidating": bool(row.get("underAvvikling")),
        "municipality": _addr_part(row, "forretningsadresse", "kommune"),
        "municipality_number": _addr_part(row, "forretningsadresse", "kommunenummer"),
        "industry_code": (row.get("naeringskode1") or {}).get("kode") or "",
        "industry_label": (row.get("naeringskode1") or {}).get("beskrivelse") or "",
        "website": row.get("hjemmeside") or "",
        "latest_submitted_accounts": row.get("sisteInnsendteAarsregnskap") or "",
    }
    profile["evidence"] = {
        "registry": evidence("registry", "available", "official_registry_live", url, value=row, retrieved_at=retrieved_at, content_sha256=digest, source_row_key=org, note=note),
    }
    profile["evidence"]["registry_live"] = {**profile["evidence"]["registry"], "field": "registry_live"}
    profile["evidence"]["accounting_obligation"] = accounting_obligation_assessment(profile)
    profile["anchor"] = "live_api"
    return profile


def _missing_profile(org: str, note: str, status: str, modules: Iterable[str]) -> dict[str, Any]:
    url = BRREG_ENTITY.format(org=org)
    profile: dict[str, Any] = {"organisation_number": org, "name": "", "legal_form": "", "employees": None, "website": "", "anchor": "none", "evidence": {}}
    for module in set(modules) | {"registry"}:
        profile["evidence"][module] = evidence(module, status, "official_registry_live", url, note=note)
    return profile


def anchor_profiles(
    orgs: list[str],
    *,
    bulk_path: str | None,
    modules: Iterable[str],
    fetcher: Callable[[str], FetchResult] = fetch_json,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Identity anchor for each unique org: bulk snapshot first, then chunked live batch, then direct lookup."""
    wanted = set(orgs)
    found: dict[str, dict[str, Any]] = {}
    meta: dict[str, Any] = {"bulk_used": bool(bulk_path), "from_bulk": 0, "from_live_batch": 0, "from_direct": 0, "missing": 0}
    if bulk_path and Path(bulk_path).exists():
        snapshot = hashlib.sha256(Path(bulk_path).read_bytes()).hexdigest()
        retrieved = utc_now()
        meta["registry_snapshot_sha256"] = snapshot
        for profile in iter_bulk(bulk_path):
            org = profile["organisation_number"]
            if org not in wanted:
                continue
            raw = profile.pop("raw", {})
            profile["evidence"] = {
                "registry": evidence("registry", "available", "official_registry_bulk", "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv", value=raw, retrieved_at=retrieved, content_sha256=snapshot, source_row_key=org),
            }
            profile["evidence"]["accounting_obligation"] = accounting_obligation_assessment(profile)
            profile["anchor"] = "bulk"
            found[org] = profile
            if len(found) == len(wanted):
                break
        meta["from_bulk"] = len(found)
    remaining = [org for org in orgs if org not in found]
    for start in range(0, len(remaining), 2000):
        chunk = remaining[start:start + 2000]
        page = 0
        while True:
            url = f"{BRREG_SEARCH}?organisasjonsnummer={','.join(chunk)}&size={len(chunk)}&page={page}"
            result = fetcher(url)
            if result.status != 200 or not isinstance(result.body, dict):
                break
            rows = (result.body.get("_embedded") or {}).get("enheter") or []
            for row in rows:
                org = str(row.get("organisasjonsnummer") or "").zfill(9)
                if org in wanted and org not in found:
                    found[org] = profile_from_api_row(row, BRREG_ENTITY.format(org=org), retrieved_at=result.retrieved_at, note="Resolved through the official chunked organisation-number query")
                    meta["from_live_batch"] += 1
            total_pages = (result.body.get("page") or {}).get("totalPages", 1)
            page += 1
            if not rows or not isinstance(total_pages, int) or page >= total_pages:
                break
    for org in [o for o in orgs if o not in found]:
        result = fetcher(BRREG_ENTITY.format(org=org))
        if result.status == 200 and isinstance(result.body, dict):
            found[org] = profile_from_api_row(result.body, result.url, retrieved_at=result.retrieved_at)
            meta["from_direct"] += 1
        elif result.status in {404, 410}:
            found[org] = _missing_profile(org, f"HTTP {result.status}: organisation number not found or deleted in BRREG", "not_found", modules)
            meta["missing"] += 1
        else:
            found[org] = _missing_profile(org, f"registry lookup failed: {result.error or result.status}", "source_error", modules)
            meta["missing"] += 1
    return found, meta


# ---------------------------------------------------------------------- enrichment

def _mark_budget(profile: dict[str, Any], module: str, source_url: str) -> None:
    profile["evidence"][module] = evidence(module, "source_error", "budget", source_url, note="budget_exhausted: not fetched to stay inside the run budget")


def _official_phase(profile: dict[str, Any], modules: set[str], budget: Budget, fetcher: Callable[[str], FetchResult]) -> dict[str, Any]:
    org = profile["organisation_number"]
    if profile.get("anchor") == "none":
        return {"requests": 0, "bytes": 0, "latencies_ms": []}
    wanted = (modules & set(OFFICIAL_MODULES))
    if profile.get("anchor") == "live_api":
        wanted -= {"registry_live"}
    try:
        records, metrics = fetch_official_modules(org, wanted, fetcher=fetcher)
    except Exception as exc:  # defensive: one company can never abort the batch
        for module in wanted:
            profile["evidence"][module] = evidence(module, "source_error", "official", BRREG_ENTITY.format(org=org), note=f"{type(exc).__name__}: {str(exc)[:160]}")
        return {"requests": 0, "bytes": 0, "latencies_ms": []}
    profile["evidence"].update(records)
    _add_metrics(profile, len(metrics))
    return {"requests": len(metrics), "bytes": sum(m.bytes_received for m in metrics), "latencies_ms": [m.elapsed_ms for m in metrics]}


def _add_metrics(profile: dict[str, Any], requests: int) -> None:
    metrics = profile.setdefault("run_metrics", {"requests": 0})
    metrics["requests"] = int(metrics.get("requests", 0)) + int(requests)


def _website_phase(profile: dict[str, Any], budget: Budget, soft_limit: float, site_fetcher: Callable[..., tuple[dict, dict]]) -> dict[str, Any]:
    url = profile.get("website")
    if budget.fraction_used() >= soft_limit:
        _mark_budget(profile, "website", str(url or BRREG_ENTITY.format(org=profile["organisation_number"])))
        return {"requests": 0, "bytes": 0, "latencies_ms": []}
    try:
        record, metrics = site_fetcher(url)
        profile["evidence"]["website"] = apply_website_identity_gate(profile, record)["website"]
    except Exception as exc:
        profile["evidence"]["website"] = evidence("website", "source_error", "registry_linked_company_website", str(url or ""), note=f"{type(exc).__name__}: {str(exc)[:160]}")
        return {"requests": 0, "bytes": 0, "latencies_ms": []}
    _add_metrics(profile, metrics.get("requests", 0))
    return metrics


# ------------------------------------------------------------------------ envelope

def module_availability(profile: dict[str, Any], module: str) -> tuple[str, str | None]:
    record = profile.get("evidence", {}).get(module)
    state = evidence_terminal_state(record)
    note = str((record or {}).get("note") or "")
    if state == "source_error" and ("budget_exhausted" in note or "BudgetExceeded" in note):
        state = "budget_exhausted"
    availability = STATE_TO_AVAILABILITY.get(state, "failed")
    if module == "website" and availability == "available":
        assessment = ((record or {}).get("value") or {}).get("identity_assessment") or {}
        if not assessment.get("publishable"):
            return "ambiguous", "website fetched but not verified as the exact legal entity"
    return availability, note or None


def _claim(field: str, value: Any, availability: str, evidence_ids: list[str], confidence: float | None) -> dict[str, Any]:
    return {"field": field, "value": value, "availability": availability, "confidence": confidence, "evidence_ids": evidence_ids}


def contract_view(profile: dict[str, Any], modules: Iterable[str], *, run_id: str, started_at: str, completed_at: str, requests: int, runtime_ms: int, changes: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the OUTPUT_CONTRACT.md fields from a finished profile; values only come from captured evidence."""
    evidence_list: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    org = profile["organisation_number"]

    def ref(module: str, span: str) -> list[str]:
        record = profile.get("evidence", {}).get(module) or {}
        if not record.get("source_url") or not record.get("content_sha256") and module != "accounting_obligation":
            return []
        key = f"{module}:{span}"
        if key not in ids:
            ids[key] = f"ev-{len(ids) + 1}"
            evidence_list.append({
                "id": ids[key],
                "source_url": record.get("source_url"),
                "source_class": record.get("source_class") or record.get("source_type"),
                "retrieved_at": record.get("retrieved_at"),
                "content_sha256": record.get("content_sha256"),
                "claim_span": span[:300],
            })
        return [ids[key]]

    def add(module: str, field: str, value: Any, span: str, confidence: float = 1.0) -> None:
        availability, note = module_availability(profile, module)
        if availability == "available" and value not in (None, "", [], {}):
            claims.append(_claim(field, value, "available", ref(module, span), confidence))
        else:
            if availability == "available":
                availability = "not_available"
            claims.append(_claim(field, None, availability, [], None))
            if availability in ("failed", "blocked", "ambiguous") and note:
                errors.append({"field": field, "availability": availability, "note": note[:240]})

    reg = profile.get("evidence", {}).get("registry_live") or profile.get("evidence", {}).get("registry") or {}
    reg_module = "registry_live" if "registry_live" in profile.get("evidence", {}) else "registry"
    reg_span = f"organisasjonsnummer={org} navn={profile.get('name')}"
    if reg.get("status") == "available":
        add(reg_module, "legal_name", profile.get("name"), reg_span)
        add(reg_module, "legal_form", profile.get("legal_form"), reg_span)
        add(reg_module, "employees", profile.get("employees"), f"{reg_span} antallAnsatte={profile.get('employees')}")
        add(reg_module, "industry", profile.get("industry_label") or None, f"{reg_span} naeringskode1={profile.get('industry_code')}")
        add(reg_module, "municipality", profile.get("municipality") or None, f"{reg_span} kommune={profile.get('municipality')}")
        add(reg_module, "registered_website", profile.get("website") or None, f"{reg_span} hjemmeside={profile.get('website')}")
    else:
        add(reg_module, "legal_name", None, reg_span)
    if "financials" in set(modules):
        records = ((profile.get("evidence", {}).get("financials") or {}).get("value") or {}).get("records") or []
        add("financials", "financials_latest", records[0] if records else None, f"org={org} period={(records[0] or {}).get('period') if records else None}")
    if "roles" in set(modules):
        roles = ((profile.get("evidence", {}).get("roles") or {}).get("value") or {}).get("roles") or []
        active = [r for r in roles if not r.get("inactive")]
        add("roles", "role_holders", [{"name": r.get("name"), "role": r.get("role")} for r in active][:50], f"org={org} active_roles={len(active)}")
    if "locations" in set(modules):
        locations = ((profile.get("evidence", {}).get("locations") or {}).get("value") or {}).get("locations") or []
        add("locations", "registered_locations", locations[:100], f"org={org} underenheter={len(locations)}")
    if "website" in set(modules):
        availability, note = module_availability(profile, "website")
        value = ((profile.get("evidence", {}).get("website") or {}).get("value") or {})
        assessment = value.get("identity_assessment") or {}
        if availability == "available":
            add("website", "official_website", value.get("final_url"), f"{value.get('title') or ''} org={org}", float(assessment.get("score") or 0.0))
            add("website", "website_title", value.get("title"), f"title={value.get('title')}", float(assessment.get("score") or 0.0))
            add("website", "social_links", value.get("social_links"), f"social links on {value.get('final_url')}", float(assessment.get("score") or 0.0))
        else:
            claims.append(_claim("official_website", None, availability, [], None))
            if note and availability in ("failed", "blocked", "ambiguous"):
                errors.append({"field": "official_website", "availability": availability, "note": note[:240]})
    return {
        "run": {"run_id": run_id, "started_at": started_at, "completed_at": completed_at, "terminal_status": "completed"},
        "claims": claims,
        "evidence": evidence_list,
        "changes": changes,
        "errors": errors,
        "operations": {"requests": requests, "runtime_ms": runtime_ms, "third_party_cost_usd": 0},
    }


def _failed_row_envelope(row: dict[str, Any], run_id: str, started_at: str, completed_at: str, modules: list[str], reason: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "organisation_number": row["raw"],
        "state": "submission_error",
        "started_at": started_at,
        "completed_at": completed_at,
        "modules": {m: {"state": "submission_error", "availability": "failed", "retry_count": 0, "final_timestamp": completed_at} for m in modules},
        "profile": {"organisation_number": row["raw"], "evidence": {}},
        "run": {"run_id": run_id, "started_at": started_at, "completed_at": completed_at, "terminal_status": "completed"},
        "claims": [_claim("legal_name", None, "failed", [], None)],
        "evidence": [],
        "changes": [],
        "errors": [{"field": "organisation_number", "availability": "failed", "note": reason}],
        "operations": {"requests": 0, "runtime_ms": 0, "third_party_cost_usd": 0},
    }


# --------------------------------------------------------------------------- driver

def run_batch(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
    modules: list[str],
    budget: Budget,
    bulk_path: str | None = None,
    previous: dict[str, dict[str, Any]] | None = None,
    workers: int = 8,
    website_soft_limit: float = 0.85,
    fetcher: Callable[[str], FetchResult] = fetch_json,
    site_fetcher: Callable[..., tuple[dict, dict]] = fetch_website,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    started_at = utc_now()
    t0 = time.monotonic()
    valid_orgs = list(dict.fromkeys(r["organisation_number"] for r in rows if r["organisation_number"]))
    module_set = set(modules)
    fetch_modules = [m for m in modules if m not in {"registry", "accounting_obligation", "website"}]
    profiles, anchor_meta = anchor_profiles(valid_orgs, bulk_path=bulk_path, modules=modules, fetcher=fetcher)
    operations = {"requests_by_phase": Counter(), "bytes": 0, "latencies_ms": []}

    def phase_one(org: str) -> None:
        metric = _official_phase(profiles[org], module_set, budget, fetcher)
        operations["requests_by_phase"]["official"] += metric["requests"]
        operations["bytes"] += metric["bytes"]
        operations["latencies_ms"].extend(metric["latencies_ms"])

    def phase_two(org: str) -> None:
        profile = profiles[org]
        if "website" not in module_set or profile.get("anchor") == "none":
            return
        metric = _website_phase(profile, budget, website_soft_limit, site_fetcher)
        operations["requests_by_phase"]["website"] += metric["requests"]
        operations["bytes"] += metric["bytes"]
        operations["latencies_ms"].extend(metric["latencies_ms"])

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(phase_one, valid_orgs))
        list(pool.map(phase_two, valid_orgs))

    completed_at = utc_now()
    runtime_ms = int((time.monotonic() - t0) * 1000)
    envelopes: list[dict[str, Any]] = []
    for row in rows:
        org = row["organisation_number"]
        if org is None:
            envelopes.append(_failed_row_envelope(row, run_id, started_at, completed_at, modules, "invalid organisation number: expected 9 digits"))
            continue
        profile = json.loads(json.dumps(profiles[org]))
        for key in ("evaluation_split", "sample_slice"):
            if key in row:
                profile[key] = row[key]
        envelope = terminal_envelope(profile, run_id=run_id, modules=modules, started_at=started_at, completed_at=completed_at)
        for module in modules:
            availability, note = module_availability(profile, module)
            envelope["modules"][module]["availability"] = availability
        changes: list[dict[str, Any]] = []
        if previous and org in previous:
            try:
                changes = diff_profile(previous[org], profile)
            except Exception:
                changes = []
        per_company_requests = (profile.get("run_metrics") or {}).get("requests", 0)
        envelope.update(contract_view(profile, modules, run_id=run_id, started_at=started_at, completed_at=completed_at, requests=per_company_requests, runtime_ms=runtime_ms, changes=changes))
        envelopes.append(envelope)

    totals: Counter = Counter()
    for envelope in envelopes:
        for state in envelope["modules"].values():
            totals[state.get("availability", "failed")] += 1
    latencies = sorted(operations["latencies_ms"])
    report = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "expected_count": len(rows),
        "emitted_envelopes": len(envelopes),
        "modules": modules,
        "registry_anchor": anchor_meta,
        "operations": {
            "requests": budget.requests,
            "requests_by_phase": dict(operations["requests_by_phase"]),
            "requests_refused_by_budget": budget.refused,
            "bytes": operations["bytes"],
            "runtime_ms": runtime_ms,
            "p50_ms": latencies[len(latencies) // 2] if latencies else None,
            "p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None,
            "third_party_cost_usd": 0,
        },
        "budget": {"max_requests": budget.max_requests, "max_seconds": budget.max_seconds, "exhausted": budget.exhausted()},
        "availability_totals": {state: totals.get(state, 0) for state in AVAILABILITY_STATES},
        "validation": validate(rows, envelopes),
    }
    return envelopes, [profiles[o] for o in valid_orgs], report


def validate(rows: list[dict[str, Any]], envelopes: list[dict[str, Any]]) -> dict[str, Any]:
    expected = [r["organisation_number"] or r["raw"] for r in rows]
    got = [e.get("organisation_number") for e in envelopes]
    checks = {
        "exact_expected_count": len(envelopes) == len(rows),
        "same_order_as_input": got == expected,
        "all_modules_have_six_state_availability": all(
            state.get("availability") in AVAILABILITY_STATES for e in envelopes for state in e.get("modules", {}).values()
        ),
        "every_available_claim_has_evidence": all(
            c["availability"] != "available" or (c["evidence_ids"] and all(i in {ev["id"] for ev in e["evidence"]} for i in c["evidence_ids"]))
            for e in envelopes for c in e.get("claims", [])
        ),
        "no_value_on_unavailable_claim": all(
            c["availability"] == "available" or c["value"] is None for e in envelopes for c in e.get("claims", [])
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}
