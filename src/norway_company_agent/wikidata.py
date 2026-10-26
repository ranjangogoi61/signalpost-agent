"""Candidate website hostnames from Wikidata items that carry a company's exact organisation number.

Wikidata (CC0) links some companies to their Norwegian organisation number (property P2333) and
to an official website (P856). One SPARQL request per chunk of organisation numbers. The result is
only a *candidate*: a website is published only if its own page prints the exact organisation
number, exactly like any other discovery candidate.
"""
from __future__ import annotations

import urllib.parse
from typing import Any, Callable

from .http import FetchResult, fetch_json

SPARQL = "https://query.wikidata.org/sparql"
ORG_PROPERTY = "P2333"
WEBSITE_PROPERTY = "P856"
CHUNK = 100


def build_query(orgs: list[str]) -> str:
    values = " ".join(f'"{org}"' for org in orgs if org.isdigit() and len(org) == 9)
    return f"SELECT ?orgnr ?site WHERE {{ VALUES ?orgnr {{ {values} }} ?item wdt:{ORG_PROPERTY} ?orgnr . ?item wdt:{WEBSITE_PROPERTY} ?site . }}"


def wikidata_websites(orgs: list[str], *, fetcher: Callable[[str], FetchResult] = fetch_json) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """Return ({org: [website urls]}, metrics). Never raises; a failed chunk just yields no candidates."""
    found: dict[str, list[str]] = {}
    metrics = {"requests": 0, "failed_chunks": 0, "matches": 0}
    for start in range(0, len(orgs), CHUNK):
        chunk = [o for o in orgs[start:start + CHUNK] if o.isdigit() and len(o) == 9]
        if not chunk:
            continue
        url = f"{SPARQL}?{urllib.parse.urlencode({'query': build_query(chunk), 'format': 'json'})}"
        metrics["requests"] += 1
        try:
            result = fetcher(url)
        except Exception:
            metrics["failed_chunks"] += 1
            continue
        body = result.body if isinstance(result.body, dict) else None
        if result.status != 200 or body is None:
            metrics["failed_chunks"] += 1
            continue
        wanted = set(chunk)
        for row in (body.get("results") or {}).get("bindings") or []:
            org = str((row.get("orgnr") or {}).get("value") or "").replace(" ", "")
            site = str((row.get("site") or {}).get("value") or "")
            if org in wanted and site.startswith(("http://", "https://")):
                sites = found.setdefault(org, [])
                if site not in sites:
                    sites.append(site)
                    metrics["matches"] += 1
    return found, metrics
