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
import json
import re
import socket
import time
import unicodedata
import urllib.parse
import urllib.request
from typing import Any, Callable

from bs4 import BeautifulSoup

from .discovery import BLOCKED_DISCOVERY_HOSTS, build_company_search_query, parse_brave_web_results
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
SEARCH_METHOD = "search_candidate_exact_org_number_v1"
EMAIL_METHOD = "registry_email_domain_exact_org_number_v1"
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
MAX_CANDIDATES = 8
GENERIC_TOKENS = {"norge", "norway", "gruppen", "group", "holding", "invest", "eiendom", "service", "services", "consulting", "norden"}
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
    brand = [t for t in tokens if t not in GENERIC_TOKENS] or tokens
    options = [joined, "-".join(tokens), "".join(tokens[:2]), "".join(brand), "-".join(brand)]
    if len(tokens[0]) >= 5 and tokens[0] not in GENERIC_TOKENS:
        options.append(tokens[0])
    slugs: list[str] = []
    for slug in options:
        if 4 <= len(slug) <= 40 and slug not in slugs:
            slugs.append(slug)
    hosts: list[str] = []
    for slug in slugs:
        for tld in ("no", "com"):
            host = f"{slug}.{tld}"
            if host not in hosts and not any(host == b or host.endswith("." + b) for b in BLOCKED_DISCOVERY_HOSTS):
                hosts.append(host)
    return hosts[:MAX_CANDIDATES]


REGISTRY_FREE_MAIL = {"gmail.com", "googlemail.com", "hotmail.com", "hotmail.no", "outlook.com", "outlook.no", "live.com", "live.no", "yahoo.com", "yahoo.no", "icloud.com", "me.com", "online.no", "msn.com", "proton.me", "protonmail.com", "start.no", "frisurf.no", "broadpark.no", "getmail.no", "c2i.net", "lyse.net", "altibox.no", "telia.com", "mac.com"}


def registry_email_host(profile: dict[str, Any]) -> str | None:
    """The domain of the e-mail address the company itself registered in Enhetsregisteret (a strong website candidate)."""
    records = profile.get("evidence") or {}
    for module in ("registry_live", "registry"):
        raw = (records.get(module) or {}).get("value")
        if not isinstance(raw, dict):
            continue
        email = next((str(v) for k, v in raw.items() if str(k).casefold() == "epostadresse" and v), "")
        email = email.strip().casefold()
        if "@" not in email:
            continue
        host = email.rsplit("@", 1)[1].strip(". ")
        if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host) or host in REGISTRY_FREE_MAIL:
            return None
        if any(host == b or host.endswith("." + b) for b in BLOCKED_DISCOVERY_HOSTS):
            return None
        return host.removeprefix("www.")
    return None


def org_number_pattern(org: str) -> re.Pattern[str]:
    digits = re.sub(r"\D", "", org)
    if len(digits) != 9:
        raise ValueError("organisation number must have nine digits")
    sep = r"[\s.\u00a0\u202f]?"
    return re.compile(rf"(?<!\d){digits[:3]}{sep}{digits[3:6]}{sep}{digits[6:]}(?!\d)")


MAX_OTHER_ORGS = 2
ANY_ORG_RE = re.compile(r"(?<!\d)\d{3}[\s.\u00a0\u202f]?\d{3}[\s.\u00a0\u202f]?\d{3}(?!\d)")


def valid_org_number(number: str) -> bool:
    """Norwegian organisation number check digit (modulus 11), so phone numbers and postcodes do not count."""
    digits = re.sub(r"\D", "", number)
    if len(digits) != 9:
        return False
    total = sum(int(d) * w for d, w in zip(digits[:8], (3, 2, 7, 6, 5, 4, 3, 2)))
    check = 11 - (total % 11)
    check = 0 if check == 11 else check
    return check != 10 and check == int(digits[8])


def _visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def other_org_numbers(html: str, org: str) -> int:
    """How many distinct valid organisation numbers other than ours the page prints (group sites list many)."""
    found = {re.sub(r"\D", "", m.group(0)) for m in ANY_ORG_RE.finditer(_visible_text(html))}
    return len({n for n in found if n != org and valid_org_number(n)})


def page_prints_org_number(html: str, org: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    lowered = _fold(text)
    if any(marker in lowered for marker in PARKED_MARKERS):
        return False
    return bool(org_number_pattern(org).search(text))


def make_brave_searcher(api_key: str, *, charge: Callable[[], bool] | None = None, timeout: float = 15.0, max_hosts: int = 3, opener: Callable[..., Any] | None = None) -> Callable[[dict[str, Any]], list[str]]:
    """Candidate hostnames from a separately contracted Brave Search API key.

    Search output is transient: only hostnames survive, and a host is published only if the page it
    serves prints the company's exact organisation number. `charge` returns False once the declared
    API budget is spent. Never scrapes a results page.
    """
    open_url = opener or urllib.request.urlopen

    def searcher(profile: dict[str, Any]) -> list[str]:
        try:
            query = build_company_search_query(profile)
        except ValueError:
            return []
        if charge is not None and not charge():
            return []
        params = urllib.parse.urlencode({"q": query, "count": 10, "country": "no", "search_lang": "nb", "safesearch": "moderate", "spellcheck": "0"})
        request = urllib.request.Request(f"{BRAVE_ENDPOINT}?{params}", headers={"Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": USER_AGENT, "X-Subscription-Token": api_key})
        try:
            with open_url(request, timeout=timeout) as response:
                payload = json.loads(response.read())
        except Exception:
            return []
        hosts: list[str] = []
        for item in parse_brave_web_results(payload if isinstance(payload, dict) else {}, query=query):
            host = (urllib.parse.urlparse(str(item.get("url") or "")).hostname or "").casefold().removeprefix("www.")
            blocked = any(host == b or host.endswith("." + b) for b in BLOCKED_DISCOVERY_HOSTS)
            if host and not blocked and host not in hosts:
                hosts.append(host)
        return hosts[:max_hosts]

    return searcher


SOCIAL_SUFFIXES = ("", "as", "asa", "no", "norge", "norway", "official")


def social_slug(url: str) -> str:
    """The page handle of a social profile URL, compacted (company/<slug> on LinkedIn, first segment elsewhere)."""
    parsed = urllib.parse.urlparse(url or "")
    host = (parsed.hostname or "").casefold()
    segments = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    slug = ""
    if "linkedin." in host:
        for marker in ("company", "school"):
            if marker in segments and segments.index(marker) + 1 < len(segments):
                slug = segments[segments.index(marker) + 1]
                break
    elif "facebook." in host and segments and segments[0] in {"pages", "p", "people"} and len(segments) > 1:
        slug = segments[1]
    elif segments:
        slug = segments[0]
    slug = re.sub(r"[-_.]?\d{6,}$", "", slug.lstrip("@"))
    return re.sub(r"[^a-z0-9]", "", _fold(slug))


def assess_social_strict(profile: dict[str, Any], link: dict[str, str]) -> dict[str, Any]:
    """A social profile is the company's own only if its handle IS the company's name (optionally with AS/NO/NORGE).

    Substring matching is not enough: `norskkaffegruppen` contains `norskkaffe` but belongs to the parent group.
    """
    core = "".join(name_tokens(str(profile.get("name") or "")))
    slug = social_slug(link.get("url") or "")
    allowed = {core + suffix for suffix in SOCIAL_SUFFIXES} if len(core) >= 4 else set()
    publishable = bool(slug) and slug in allowed
    return {
        **link,
        "identity_score": 0.98 if publishable else 0.2,
        "publishable": publishable,
        "matched_tokens": name_tokens(str(profile.get("name") or "")) if publishable else [],
        "reason": "social handle equals the legal name" if publishable else "social handle is not exactly this company's name (it may belong to a parent group, an agency or a theme)",
        "method": "strict_social_handle_v1",
    }


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

    def proves_ownership(page: dict[str, Any]) -> bool:
        if not page_prints_org_number(page["html"], org):
            return False
        others = other_org_numbers(page["html"], org)
        if others > MAX_OTHER_ORGS:
            out["error"] = "page prints this organisation number among many others (group site or directory)"
            return False
        out.update(verified=True, page_url=page["final_url"], others=others)
        return True

    if proves_ownership(home):
        return out
    soup = BeautifulSoup(home["html"], "lxml")
    home_domain = _registered_domain(home["final_url"])
    for link in _priority_links(home["final_url"], soup, limit=MAX_EXTRA_PAGES):
        if _registered_domain(link) != home_domain:
            continue
        page = fetch_page(link)
        take(page)
        if page.get("ok") and proves_ownership(page):
            return out
    return out


def discover_website(
    profile: dict[str, Any],
    *,
    resolver: Callable[[str], bool] = dns_resolves,
    fetch_page: Callable[[str], dict[str, Any]] = default_fetch_page,
    site_fetcher: Callable[..., tuple[dict[str, Any], dict[str, Any]]] = fetch_website,
    max_requests: int = 14,
    searcher: Callable[[dict[str, Any]], list[str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (website evidence record, metrics). Never raises for a single company."""
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    metrics = {"requests": 0, "bytes": 0, "latencies_ms": [], "candidates_tried": 0, "verified": False}
    searched: list[str] = []
    if searcher is not None:
        try:
            searched = list(searcher(profile))
        except Exception:
            searched = []
    email_host = registry_email_host(profile)
    leading = ([email_host] if email_host else []) + searched
    hosts = list(dict.fromkeys(leading + candidate_hosts(str(profile.get("name") or ""))))[: MAX_CANDIDATES + 4]
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
        tried.append({"host": host, "origin": "registry_email" if host == email_host else ("search" if host in searched else "name"), "result": "verified" if result["verified"] else (result["error"] or "organisation number not printed on homepage or contact pages")})
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
    method = EMAIL_METHOD if verified["host"] == email_host else (SEARCH_METHOD if verified["host"] in searched else METHOD)
    gated = mark_verified_by_org_number(profile, record, verified["page_url"], method=method, others=int(verified.get("others") or 0))
    gated["value"]["discovery"] = {"method": method, "candidates": tried, "verified_on": verified["page_url"]}
    gated["source_type"] = "company_website_discovered_by_exact_org_number"
    gated["note"] = "Company-controlled page found without a registry link; published only because it prints the exact organisation number. Not an official registry fact."
    return gated, metrics


def mark_verified_by_org_number(profile: dict[str, Any], record: dict[str, Any], page_url: str, *, method: str, others: int = 0) -> dict[str, Any]:
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
        "ownership": "proven",
        "other_org_numbers_on_page": others,
    }
    assessments = [assess_social_strict(profile, link) for link in value.get("discovered_social_links") or []]
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
    """Second look at a registry-linked website whose ownership is not yet proven (the name-based gate cannot tell a company's own site from its parent group's).

    The kit's gate reads boilerplate-stripped text, which usually drops the footer where the
    organisation number is printed. This re-checks the raw homepage and at most two contact
    pages for the exact number. It can only upgrade a record, never downgrade it.
    """
    metrics = {"requests": 0, "bytes": 0, "latencies_ms": []}
    value = record.get("value") or {}
    if record.get("status") != "available" or (value.get("identity_assessment") or {}).get("ownership") == "proven":
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
    upgraded = mark_verified_by_org_number(profile, record, result["page_url"], method=REGISTRY_METHOD, others=int(result.get("others") or 0))
    upgraded["value"]["reverified_by"] = {"method": REGISTRY_METHOD, "verified_on": result["page_url"]}
    return upgraded, metrics
