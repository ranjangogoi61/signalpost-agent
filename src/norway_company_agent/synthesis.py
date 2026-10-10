"""Deterministic company synthesis built only from an envelope's published claims.

No language model. Every sentence is assembled from claim values and cites the evidence ids of
the claims it uses; anything not published is listed as unknown with its availability state.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

FIELD_LABELS = {
    "legal_name": "legal name",
    "legal_form": "legal form",
    "employees": "employee count",
    "industry": "industry",
    "municipality": "municipality",
    "registered_website": "website listed in the registry",
    "financials_latest": "annual accounts",
    "role_holders": "role holders",
    "registered_locations": "registered subunits",
    "official_website": "official website",
    "website_title": "website title",
    "social_links": "social profiles",
}
STATE_WORDS = {
    "not_available": "not found",
    "blocked": "blocked by the source",
    "ambiguous": "could not be confirmed as this company",
    "failed": "the lookup failed",
    "not_applicable": "does not apply",
}
LEGAL_FORMS = {"AS": "private limited company (AS)", "ASA": "public limited company (ASA)", "ENK": "sole proprietorship (ENK)", "NUF": "Norwegian-registered foreign enterprise (NUF)", "ANS": "general partnership (ANS)", "DA": "partnership with shared liability (DA)", "SA": "cooperative (SA)", "STI": "foundation (STI)", "FLI": "association (FLI)", "BA": "co-operative with limited liability (BA)"}


def _money(value: Any, currency: str | None) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return f"{currency or 'NOK'} {int(round(value)):,}".replace(",", " ")


def _claims(envelope: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["field"]: c for c in envelope.get("claims", [])}


def _have(claim: dict[str, Any] | None) -> bool:
    return bool(claim) and claim.get("availability") == "available" and claim.get("value") not in (None, "", [], {})


def summarize_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    claims = _claims(envelope)
    sentences: list[dict[str, Any]] = []

    def add(text: str, fields: list[str]) -> None:
        ids: list[str] = []
        for field in fields:
            for evidence_id in (claims.get(field) or {}).get("evidence_ids", []):
                if evidence_id not in ids:
                    ids.append(evidence_id)
        sentences.append({"text": text, "fields": fields, "evidence_ids": ids})

    name = claims.get("legal_name")
    if _have(name):
        parts = [f"{name['value']}"]
        used = ["legal_name"]
        form = claims.get("legal_form")
        if _have(form):
            parts.append(f"is a {LEGAL_FORMS.get(str(form['value']).upper(), str(form['value']) + ' entity')}")
            used.append("legal_form")
        else:
            parts.append("is a Norwegian registered entity")
        place = claims.get("municipality")
        text = " ".join(parts)
        if _have(place):
            text += f" registered in {str(place['value']).title()}"
            used.append("municipality")
        industry = claims.get("industry")
        if _have(industry):
            text += f", operating in {str(industry['value']).lower()}"
            used.append("industry")
        employees = claims.get("employees")
        if _have(employees):
            text += f", with {employees['value']} registered employees"
            used.append("employees")
        add(text + ".", used)

    fin = claims.get("financials_latest")
    if _have(fin):
        record = fin["value"]
        period = record.get("period") or {}
        currency = record.get("currency")
        bits = []
        for key, label in (("revenue", "revenue of"), ("annual_result", "an annual result of"), ("assets", "total assets of")):
            money = _money(record.get(key), currency)
            if money:
                bits.append(f"{label} {money}")
        span = f" for {period.get('fraDato')} to {period.get('tilDato')}" if period.get("fraDato") and period.get("tilDato") else ""
        if bits:
            add(f"Its latest filed annual accounts{span} report " + ", ".join(bits) + ".", ["financials_latest"])

    roles = claims.get("role_holders")
    if _have(roles):
        counts = Counter(str(r.get("role") or "role") for r in roles["value"])
        top = ", ".join(f"{n} {role.lower()}" for role, n in counts.most_common(3))
        add(f"The register lists {len(roles['value'])} active role holders ({top}).", ["role_holders"])

    locations = claims.get("registered_locations")
    if _have(locations):
        add(f"The register records {len(locations['value'])} subunit location(s).", ["registered_locations"])

    site = claims.get("official_website")
    if _have(site):
        add(f"Its official website, confirmed as this exact company, is {site['value']}.", ["official_website"])

    refresh = envelope.get("refresh") or {}
    changes = envelope.get("changes") or []
    if refresh.get("compared_with_previous"):
        if changes:
            fields = ", ".join(sorted({str(c.get("field")) for c in changes})[:5])
            sentences.append({"text": f"Compared with the previous run, {len(changes)} material change(s) were found: {fields}.", "fields": [], "evidence_ids": []})
        else:
            sentences.append({"text": "Compared with the previous run, no material change was found.", "fields": [], "evidence_ids": []})
    else:
        sentences.append({"text": "This is the first run for this company, so there is no earlier snapshot to compare with.", "fields": [], "evidence_ids": []})

    unknown = []
    for field in FIELD_LABELS:
        claim = claims.get(field)
        if claim and claim.get("availability") != "available":
            unknown.append({"field": field, "label": FIELD_LABELS[field], "availability": claim["availability"], "meaning": STATE_WORDS.get(claim["availability"], claim["availability"])})
    if unknown:
        listing = "; ".join(f"{u['label']} ({u['meaning']})" for u in unknown)
        sentences.append({"text": f"Not published: {listing}.", "fields": [u["field"] for u in unknown], "evidence_ids": []})

    return {"method": "deterministic_template_v1", "sentences": sentences, "unknown": unknown}


def _numbers(value: Any, out: set[str] | None = None) -> set[str]:
    """Every number a sentence may legitimately state about a claim value (values and counts)."""
    out = set() if out is None else out
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, (int, float)):
        out.update({str(abs(int(round(value)))), str(abs(int(value))), str(abs(value)), str(int(round(value))), str(int(value)), str(value)})
    elif isinstance(value, str):
        out.update(re.findall(r"\d+", value))
        out.add(re.sub(r"\D", "", value))
    elif isinstance(value, list):
        out.add(str(len(value)))
        if all(isinstance(item, dict) and "role" in item for item in value):
            out.update(str(n) for n in Counter(str(item.get("role") or "role") for item in value).values())
        for item in value:
            _numbers(item, out)
    elif isinstance(value, dict):
        for item in value.values():
            _numbers(item, out)
    out.discard("")
    return out


def check_synthesis(envelope: dict[str, Any]) -> list[str]:
    """Return problems: cited evidence must exist and every number must come from a cited claim."""
    problems: list[str] = []
    known = {e["id"] for e in envelope.get("evidence", [])}
    claims = _claims(envelope)
    for sentence in (envelope.get("synthesis") or {}).get("sentences", []):
        for evidence_id in sentence["evidence_ids"]:
            if evidence_id not in known:
                problems.append(f"unknown evidence id {evidence_id}")
        text = sentence["text"]
        if text.startswith(("Compared", "This is the first", "Not published")):
            continue
        if sentence["fields"] and not sentence["evidence_ids"]:
            problems.append("claim sentence without evidence")
        allowed: set[str] = set()
        for field in sentence["fields"]:
            _numbers((claims.get(field) or {}).get("value"), allowed)
        for number in re.findall(r"\d+(?: \d{3})*", text):
            if number not in allowed and number.replace(" ", "") not in allowed:
                problems.append(f"number {number.replace(' ', '')} not found in cited claims")
    return problems
