"""Website discovery for companies whose registry record has no website.

Method (deterministic, no search engine, no paid API, no LLM):
  1. build at most four hostname candidates from the legal name;
  2. skip candidates that do not resolve in DNS;
  3. fetch the homepage (and at most two contact/about pages on the same
     registered domain) with robots.txt respected;
  4. publish only when the company's exact nine-digit organisation number is
     printed on one of those pages. Name similarity alone never publishes.
"""
from __future__ import annotations

import hashlib
import re
import socket
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Any, Callable

from bs4 import BeautifulSoup

from .discovery import BLOCKED_DISCOVERY_HOSTS
from .evidence import evidence
from .identity import apply_website_identity_gate, assess_social_identity
from .website import (
    SAFE_OPENER,
    USER_AGENT,
    _priority_links,
    _registered_domain,
    _robots_allowed,
    assert_public_url,
    fetch_website,
    normalize_homepage,
)

LEGAL_SUFFIXES = {"as", "asa", "ans", "da", "enk", "iks", "sa", "nuf", "ab", "ltd", "limited", "inc", "plc", "stiftelse", "stiftelsen"}
PARKED_MARKERS = ("domain is for sale", "domain for sale", "hugedomains", "parked at", "this domain may be for sale", "domenet er til salgs")
METHOD = "domain_guess_exact_org_number_v1"
MAX_CANDIDATES = 4
MAX_EXTRA_PAGES = 2


def _fold(value: str) -> str:
    text = value.translate(str.maketrans({"ø": "o", "Ø": "O", "å": "a", "Å": "A", "æ": "ae", "Æ": "AE", "é": "e", "É": "E"}))
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def name_tokens(name: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", _fold(name))
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return [t for t in tokens if t not in LEGAL_SUFFIXES]


def candidate_hosts(name: str) -> list[str]:
    tokens = name_tokens(name)
    if not tokens:
        return []
    joined = "".join(tokens)
    slugs: list[str] = []
    for slug in (joined, "-".join(tokens), "".join(tokens[:2])):
        if 4 <= len(slug) <= 40 and slug not in slugs:
            slugs.append(slug)
    hosts: list[str] = []
    for slug in slugs:
        for tld in ("no", "com"):
            host = f"{slug}.{tld}"
            if host not in hosts and not any(host == b or host.endswith("." + b) for b in BLOCKED_DISCOVERY_HOSTS):
                hosts.append(host)
    return hosts[:MAX_CANDIDATES]


def org_number_pattern(org: str) -> re.Pattern[str]:
    digits = re.sub(r"\D", "", org)
    if len(digits) != 9:
        raise ValueError("organisation number must have nine digits")
    sep = r"[\s.\u00a0\u202f]?"
    return re.compile(rf"(?<!\d){digits[:3]}{sep}{digits[3:6]}{sep}{digits[6:]}(?!\d)")


def page_prints_org_number(html: str, org: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    lowered = _fold(text)
    if any(marker in lowered for marker in PARKED_MARKERS):
        return False
    return bool(org_number_pattern(org).search(text))


def dns_resolves(host: str) -> bool:
    try:
        return bool(socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
    except OSError:
        return False


def default_fetch_page(url: str, *, timeout: float = 12.0, max_bytes: int = 1_500_000) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "url": url, "final_url": None, "html": "", "requests": 0, "bytes": 0, "latency_ms": 0, "error": None}
    try:
        assert_public_url(url)
        result["requests"] += 1
        if not _robots_allowed(url, timeout):
            result["error"] = "robots.txt disallows this user agent"
            return result
        started = time.monotonic()
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
        result["requests"] += 1
        with SAFE_OPENER.open(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            final_url = response.geturl()
            content_type = response.headers.get("content-type", "")
        result["latency_ms"] = int((time.monotonic() - started) * 1000)
        result["bytes"] = len(raw)
        if len(raw) > max_bytes or "html" not in content_type.lower():
            result["error"] = "unsupported or oversized page"
            return result
        assert_public_url(final_url)
        result.update(ok=True, final_url=final_url, html=raw.decode("utf-8", errors="replace"), sha256=hashlib.sha256(raw).hexdigest())
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:140]}"
    return result


def verify_host(host: str, org: str, fetch_page: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
    stats = {"requests": 0, "bytes": 0, "latencies_ms": []}
    out: dict[str, Any] = {"host": host, "verified": False, "page_url": None, "final_url": None, "error": None, "stats": stats}

    def take(page: dict[str, Any]) -> None:
        stats["requests"] += int(page.get("requests") or 0)
        stats["bytes"] += int(page.get("bytes") or 0)
        if page.get("latency_ms"):
            stats["latencies_ms"].append(int(page["latency_ms"]))

    home = fetch_page(f"https://{host}/")
    take(home)
    if not home.get("ok"):
        home = fetch_page(f"https://www.{host}/")
        take(home)
    if not home.get("ok"):
        out["error"] = home.get("error")
        return out
    out["final_url"] = home["final_url"]
    if page_prints_org_number(home["html"], org):
        out.update(verified=True, page_url=home["final_url"])
        return out
    soup = BeautifulSoup(home["html"], "lxml")
    home_domain = _registered_domain(home["final_url"])
    for link in _priority_links(home["final_url"], soup, limit=MAX_EXTRA_PAGES):
        if _registered_domain(link) != home_domain:
            continue
        page = fetch_page(link)
        take(page)
        if page.get("ok") and page_prints_org_number(page["html"], org):
            out.update(verified=True, page_url=page["final_url"])
            return out
    return out


def discover_website(
    profile: dict[str, Any],
    *,
    resolver: Callable[[str], bool] = dns_resolves,
    fetch_page: Callable[[str], dict[str, Any]] = default_fetch_page,
    site_fetcher: Callable[..., tuple[dict[str, Any], dict[str, Any]]] = fetch_website,
    max_requests: int = 14,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (website evidence record, metrics). Never raises for a single company."""
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    metrics = {"requests": 0, "bytes": 0, "latencies_ms": [], "candidates_tried": 0, "verified": False}
    hosts = candidate_hosts(str(profile.get("name") or ""))
    tried: list[dict[str, Any]] = []
    verified: dict[str, Any] | None = None
    for host in hosts:
        if metrics["requests"] >= max_requests:
            break
        if not resolver(host) and not resolver(f"www.{host}"):
            tried.append({"host": host, "result": "does not resolve"})
            continue
        metrics["candidates_tried"] += 1
        result = verify_host(host, org, fetch_page)
        metrics["requests"] += result["stats"]["requests"]
        metrics["bytes"] += result["stats"]["bytes"]
        metrics["latencies_ms"].extend(result["stats"]["latencies_ms"])
        tried.append({"host": host, "result": "verified" if result["verified"] else (result["error"] or "organisation number not printed on homepage or contact pages")})
        if result["verified"]:
            verified = result
            break
    if verified is None:
        note = "No registry website. Domain discovery tried: " + ("; ".join(f"{t['host']} ({t['result']})" for t in tried) if tried else "no usable candidate hostname") + ". Nothing published."
        return evidence("website", "not_found", "domain_discovery", "https://data.brreg.no/enhetsregisteret/api/enheter", note=note), metrics

    record, site_metrics = site_fetcher(verified["final_url"])
    metrics["requests"] += int(site_metrics.get("requests") or 0)
    metrics["bytes"] += int(site_metrics.get("bytes") or 0)
    metrics["latencies_ms"].extend(site_metrics.get("latencies_ms") or [])
    metrics["verified"] = True
    if record.get("status") != "available":
        record["note"] = f"{record.get('note') or ''} Exact organisation number was printed on {verified['page_url']} but the full crawl failed.".strip()
        return record, metrics
    gated = mark_verified_by_org_number(profile, record, verified["page_url"], method=METHOD)
    gated["value"]["discovery"] = {"method": METHOD, "candidates": tried, "verified_on": verified["page_url"]}
    gated["source_type"] = "company_website_discovered_by_exact_org_number"
    gated["note"] = "Company-controlled page found without a registry link; published only because it prints the exact organisation number. Not an official registry fact."
    return gated, metrics


def mark_verified_by_org_number(profile: dict[str, Any], record: dict[str, Any], page_url: str, *, method: str) -> dict[str, Any]:
    """Mark a fetched website as the exact legal entity because it prints the organisation number."""
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    gated = apply_website_identity_gate(profile, record)["website"]
    value = gated.get("value") or {}
    value["identity_assessment"] = {
        "status": "exact",
        "score": 1.0,
        "publishable": True,
        "legal_name_tokens": name_tokens(str(profile.get("name") or "")),
        "matched_tokens": [],
        "reasons": [f"exact organisation number {org} is printed on {page_url}"],
        "method": method,
    }
    assessments = [assess_social_identity(profile, link) for link in value.get("discovered_social_links") or []]
    value["social_link_assessments"] = assessments
    value["social_links"] = [{"platform": a["platform"], "url": a["url"]} for a in assessments if a["publishable"]]
    gated["value"] = value
    return gated


REGISTRY_METHOD = "registry_website_exact_org_number_v1"


def reverify_registry_website(
    profile: dict[str, Any],
    record: dict[str, Any],
    *,
    fetch_page: Callable[[str], dict[str, Any]] = default_fetch_page,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Second look at a registry-linked website the name-based gate left unverified.

    The kit's gate reads boilerplate-stripped text, which usually drops the footer where the
    organisation number is printed. This re-checks the raw homepage and at most two contact
    pages for the exact number. It can only upgrade a record, never downgrade it.
    """
    metrics = {"requests": 0, "bytes": 0, "latencies_ms": []}
    value = record.get("value") or {}
    if record.get("status") != "available" or (value.get("identity_assessment") or {}).get("publishable"):
        return record, metrics
    host = urllib.parse.urlparse(value.get("final_url") or "").hostname
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    if not host or len(org) != 9:
        return record, metrics
    result = verify_host(host, org, fetch_page)
    metrics["requests"] += result["stats"]["requests"]
    metrics["bytes"] += result["stats"]["bytes"]
    metrics["latencies_ms"].extend(result["stats"]["latencies_ms"])
    if not result["verified"]:
        return record, metrics
    upgraded = mark_verified_by_org_number(profile, record, result["page_url"], method=REGISTRY_METHOD)
    upgraded["value"]["reverified_by"] = {"method": REGISTRY_METHOD, "verified_on": result["page_url"]}
    return upgraded, metrics
