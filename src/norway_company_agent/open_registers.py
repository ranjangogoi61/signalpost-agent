"""Bulk open registers joined on the exact organisation number (one download per source per run).

* Arbeidstilsynet renholdsregister (approved cleaning companies) and BHT register (approved
  occupational-health services): XML with Hovedenhet/Organisasjonsnummer and Godkjenningsstatus.
* Mattilsynet smilefjes (food-safety inspections of restaurants/cafés): CSV with `orgnummer`.
* OpenStreetMap (ODbL) objects tagged `ref:NO:orgnr`: used only as *candidate* website hosts;
  a website is still published only when its own page prints the exact organisation number.

A company matches when the register's number equals its own organisation number or the number
of one of its subunits registered in Enhetsregisteret. Phone numbers and person names are never kept.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Callable

RENHOLD_URL = "https://registerdata.arbeidstilsynet.no/renhold_register.xml"
BHT_URL = "https://registerdata.arbeidstilsynet.no/bht_register.xml"
SMILEFJES_URL = "https://smilefjes.mattilsynet.no/api/tilsyn.csv"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = '[out:json][timeout:120];area["ISO3166-1"="NO"][admin_level=2]->.no;nwr["ref:NO:orgnr"](area.no);out tags;'
USER_AGENT = "signalpost-agent/1.0 (+https://github.com/ranjangogoi61/signalpost-agent)"
MAX_BYTES = 80_000_000
GRADE_WORDS = {"0": "smiling face (no remarks)", "1": "smiling face (minor remarks)", "2": "straight face (orders issued)", "3": "sad face (strict orders or closure)"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def download(url: str, *, data: bytes | None = None, timeout: float = 150.0) -> dict[str, Any]:
    """One counted request. Returns {ok, raw, sha256, retrieved_at, error}."""
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return {"ok": False, "error": "file larger than the safety cap", "url": url}
        return {"ok": True, "raw": raw, "sha256": hashlib.sha256(raw).hexdigest(), "retrieved_at": _now(), "url": url}
    except Exception as exc:  # network, HTTP or budget error: the source is reported as failed
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:140]}", "url": url}


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_arbeidstilsynet(raw: bytes) -> dict[str, dict[str, Any]]:
    """{main-unit orgnr: {status, website, subunits: [orgnr]}} from a register XML (renhold/BHT share one schema)."""
    out: dict[str, dict[str, Any]] = {}
    for _event, element in ET.iterparse(io.BytesIO(raw), events=("end",)):
        if _local(element.tag) != "Virksomhet":
            continue
        main = next((child for child in element if _local(child.tag) == "Hovedenhet"), None)
        if main is None:
            element.clear()
            continue
        org = ""
        status = website = name = None
        for node in main.iter():
            tag = _local(node.tag)
            text = (node.text or "").strip()
            if tag == "Organisasjonsnummer" and not org:
                org = _digits(text)
            elif tag == "Godkjenningsstatus" and status is None:
                status = text or None
            elif tag == "Webadresse" and website is None:
                website = text or None
            elif tag == "Navn" and name is None:
                name = text or None
        subunits = []
        for node in element.iter():
            if _local(node.tag) == "Avdeling":
                number = next((_digits(n.text) for n in node.iter() if _local(n.tag) == "Organisasjonsnummer"), "")
                if len(number) == 9:
                    subunits.append(number)
        if len(org) == 9:
            out[org] = {"status": status, "website": website, "name": name, "subunits": subunits}
        element.clear()
    return out


def parse_smilefjes(raw: bytes) -> dict[str, list[dict[str, Any]]]:
    """{orgnummer: [inspection rows]} keeping only outlet name, place, date and grades (no addresses beyond postcode/place)."""
    text = raw.decode("utf-8-sig", errors="replace")
    out: dict[str, list[dict[str, Any]]] = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        org = _digits(row.get("orgnummer"))
        if len(org) != 9:
            continue
        date = str(row.get("dato") or "").strip()
        iso = f"{date[4:8]}-{date[2:4]}-{date[0:2]}" if re.fullmatch(r"\d{8}", date) else None
        out.setdefault(org, []).append({
            "outlet_id": row.get("tilsynsobjektid"),
            "outlet": (row.get("navn") or "").strip(),
            "place": (row.get("poststed") or "").strip().title(),
            "date": iso,
            "grade": str(row.get("total_karakter") or "").strip(),
        })
    return out


def parse_overpass(raw: bytes) -> dict[str, list[str]]:
    """{ref:NO:orgnr: [website urls]} from an Overpass JSON answer."""
    try:
        elements = json.loads(raw).get("elements") or []
    except (ValueError, AttributeError):
        return {}
    out: dict[str, list[str]] = {}
    for element in elements:
        tags = element.get("tags") or {}
        org = _digits(tags.get("ref:NO:orgnr"))
        site = str(tags.get("website") or tags.get("contact:website") or "").strip()
        if len(org) == 9 and site:
            if not site.startswith(("http://", "https://")):
                site = "https://" + site
            sites = out.setdefault(org, [])
            if site not in sites:
                sites.append(site)
    return out


class OpenRegisters:
    """Downloads each register once and answers per-company questions from memory."""

    def __init__(self, *, downloader: Callable[..., dict[str, Any]] = download, include_osm: bool = True) -> None:
        self._download = downloader
        self.include_osm = include_osm
        self.sources: dict[str, dict[str, Any]] = {}
        self.renhold: dict[str, dict[str, Any]] = {}
        self.bht: dict[str, dict[str, Any]] = {}
        self.smilefjes: dict[str, list[dict[str, Any]]] = {}
        self.osm: dict[str, list[str]] = {}
        self.requests = 0

    def load(self) -> dict[str, Any]:
        jobs = [("renhold", RENHOLD_URL, None, parse_arbeidstilsynet), ("bht", BHT_URL, None, parse_arbeidstilsynet), ("smilefjes", SMILEFJES_URL, None, parse_smilefjes)]
        if self.include_osm:
            jobs.append(("osm", OVERPASS_URL, urllib.parse.urlencode({"data": OVERPASS_QUERY}).encode(), parse_overpass))
        for name, url, data, parser in jobs:
            self.requests += 1
            result = self._download(url, data=data) if data is not None else self._download(url)
            meta = {k: v for k, v in result.items() if k != "raw"}
            if result.get("ok"):
                try:
                    setattr(self, name, parser(result["raw"]))
                    meta["entries"] = len(getattr(self, name))
                except Exception as exc:
                    meta.update(ok=False, error=f"parse error: {type(exc).__name__}: {str(exc)[:120]}")
            self.sources[name] = meta
        return {name: {k: meta.get(k) for k in ("ok", "entries", "error")} for name, meta in self.sources.items()}

    def ok(self, name: str) -> bool:
        return bool((self.sources.get(name) or {}).get("ok"))

    @staticmethod
    def _numbers(profile: dict[str, Any]) -> list[str]:
        own = _digits(profile.get("organisation_number"))
        locations = (((profile.get("evidence") or {}).get("locations") or {}).get("value") or {}).get("locations") or []
        units = [_digits((item or {}).get("organisation_number")) for item in locations if isinstance(item, dict)]
        return [own] + [u for u in units if len(u) == 9 and u != own]

    def approval(self, name: str, profile: dict[str, Any]) -> dict[str, Any] | None:
        register = getattr(self, name)
        own = _digits(profile.get("organisation_number"))
        entry = register.get(own)
        if entry is None:
            return None
        return {"status": entry.get("status"), "registered_subunits": len(entry.get("subunits") or [])}

    def register_website(self, profile: dict[str, Any]) -> list[str]:
        own = _digits(profile.get("organisation_number"))
        sites = [e.get("website") for e in (self.renhold.get(own), self.bht.get(own)) if e and e.get("website")]
        return [str(s) for s in sites]

    def inspections(self, profile: dict[str, Any]) -> dict[str, Any] | None:
        rows: list[dict[str, Any]] = []
        for number in self._numbers(profile):
            rows.extend(self.smilefjes.get(number) or [])
        rows = [r for r in rows if r.get("date")]
        if not rows:
            return None
        rows.sort(key=lambda r: r["date"], reverse=True)
        latest_by_outlet: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest_by_outlet.setdefault(str(row.get("outlet_id") or row.get("outlet")), row)
        latest = rows[0]
        return {
            "inspection_count": len(rows),
            "outlet_count": len(latest_by_outlet),
            "latest_date": latest["date"],
            "latest_grade": latest["grade"],
            "latest_grade_meaning": GRADE_WORDS.get(latest["grade"], "not graded"),
            "latest_outlet": latest["outlet"],
            "outlets": [{"outlet": r["outlet"], "place": r["place"], "latest_date": r["date"], "grade": r["grade"]} for r in list(latest_by_outlet.values())[:10]],
        }

    def osm_websites(self, profile: dict[str, Any]) -> list[str]:
        sites: list[str] = []
        for number in self._numbers(profile):
            for site in self.osm.get(number) or []:
                if site not in sites:
                    sites.append(site)
        return sites[:3]
