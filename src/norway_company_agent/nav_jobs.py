"""Active job ads from NAV's official job vacancy feed (pam-stilling-feed), matched by exact organisation number.

Terms (arbeidsplassen.nav.no/vilkar-api): free to use; inactive ads must not be shown; contact
information must never be exposed. This module therefore publishes only ACTIVE, unexpired ads,
and keeps title, dates, municipality and the public ad URL; never the description or any contact.

Method: scan the feed once per run (employer name + status per ad), then for each company fetch
only the few ads whose employer name equals the company's legal name and publish an ad only if
NAV's own record carries the company's exact nine-digit organisation number.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .domain_discovery import name_tokens
from .evidence import evidence

FEED_BASE = "https://pam-stilling-feed.nav.no"
FEED_FIRST = FEED_BASE + "/api/v1/feed"
TOKEN_URL = FEED_BASE + "/api/publicToken"
AD_PAGE = "https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}"
USER_AGENT = "signalpost-agent/1.0 (+https://github.com/ranjangogoi61/signalpost-agent)"
MAX_CANDIDATES_PER_COMPANY = 4
MAX_POSTINGS_PUBLISHED = 8


JWT_RE = re.compile(r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")


def _open(url: str, headers: dict[str, str], timeout: float = 30.0, opener: Callable[..., Any] | None = None, attempts: int = 2) -> tuple[int, bytes]:
    """GET with one retry for timeouts and 5xx; HTTP errors become (status, b"")."""
    last: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
        try:
            with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
                return int(getattr(response, "status", 200) or 200), response.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == attempts - 1:
                return exc.code, b""
            last = exc
        except (TimeoutError, OSError) as exc:
            if "BudgetExceeded" in type(exc).__name__ or attempt == attempts - 1:
                raise
            last = exc
        time.sleep(1.0 + attempt)
    raise last or RuntimeError("request failed")


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class NavJobsIndex:
    """One feed scan per run. Thread-safe for concurrent per-company lookups."""

    def __init__(self, *, token: str | None = None, opener: Callable[..., Any] | None = None, now: Callable[[], datetime] | None = None, max_pages: int = 400, deadline: Callable[[], bool] | None = None, lookback_days: int = 45) -> None:
        self._token = token
        self._opener = opener
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._max_pages = max_pages
        self._lookback_days = lookback_days
        self._deadline = deadline or (lambda: False)
        self._ads: dict[str, dict[str, Any]] = {}
        self._by_name: dict[tuple[str, ...], list[str]] = {}
        self._lock = threading.Lock()
        self.status: dict[str, Any] = {"scanned": False, "pages": 0, "items": 0, "active_ads": 0, "truncated": False, "error": None, "lookback_days": lookback_days}

    # ------------------------------------------------------------------ scan
    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Authorization": f"Bearer {self._token}"}

    def _fetch_token(self) -> str:
        status, body = _open(TOKEN_URL, {"Accept": "application/json, text/plain"}, opener=self._opener)
        if status != 200 or not body:
            raise RuntimeError(f"public token request returned HTTP {status}")
        text = body.decode("utf-8", "replace")
        if text.lstrip().startswith("{"):
            data = json.loads(text)
            text = str(data.get("token") or data.get("access_token") or text)
        match = JWT_RE.search(text)
        if not match:
            raise RuntimeError("public token response did not contain a token")
        return match.group(0)

    def scan(self) -> dict[str, Any]:
        try:
            if not self._token:
                self._token = self._fetch_token()
            since = email.utils.formatdate((self._now() - timedelta(days=self._lookback_days)).timestamp(), usegmt=True)
            url = FEED_FIRST
            seen_ads: dict[str, dict[str, Any]] = {}
            while url and self.status["pages"] < self._max_pages:
                if self._deadline():
                    self.status["truncated"] = True
                    break
                headers = {**self._headers(), "If-Modified-Since": since}
                status, body = _open(url if url.startswith("http") else FEED_BASE + url, headers, opener=self._opener)
                if status == 304:
                    break
                if status != 200:
                    raise RuntimeError(f"feed page returned HTTP {status}")
                page = json.loads(body)
                self.status["pages"] += 1
                for item in page.get("items") or []:
                    entry = item.get("_feed_entry") or {}
                    uuid = str(entry.get("uuid") or item.get("id") or "")
                    if not uuid:
                        continue
                    self.status["items"] += 1
                    seen_ads[uuid] = {"uuid": uuid, "status": str(entry.get("status") or ""), "business": str(entry.get("businessName") or ""), "url": item.get("url"), "modified": entry.get("sistEndret") or item.get("date_modified")}
                url = page.get("next_url")
            else:
                if url:
                    self.status["truncated"] = True
            with self._lock:
                self._ads = {k: v for k, v in seen_ads.items() if v["status"] == "ACTIVE"}
                self._by_name = {}
                for uuid, ad in self._ads.items():
                    key = tuple(name_tokens(ad["business"]))
                    if key:
                        self._by_name.setdefault(key, []).append(uuid)
            self.status.update(scanned=True, active_ads=len(self._ads))
        except Exception as exc:
            self.status.update(scanned=False, error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return self.status

    # --------------------------------------------------------------- lookup
    def candidates(self, legal_name: str) -> list[dict[str, Any]]:
        key = tuple(name_tokens(legal_name))
        with self._lock:
            uuids = list(self._by_name.get(key, [])) if key else []
        return [self._ads[u] for u in uuids[:MAX_CANDIDATES_PER_COMPANY]]

    def fetch_entry(self, ad: dict[str, Any]) -> dict[str, Any] | None:
        url = ad.get("url") or f"/api/v1/feedentry/{ad['uuid']}"
        status, body = _open(url if str(url).startswith("http") else FEED_BASE + str(url), self._headers(), opener=self._opener)
        if status != 200:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None


def jobs_record(profile: dict[str, Any], index: NavJobsIndex | None) -> tuple[dict[str, Any], dict[str, int]]:
    """Evidence record for the `jobs` module of one company, plus request metrics."""
    org = str(profile.get("organisation_number") or "")
    url = f"{FEED_FIRST}"
    metrics = {"requests": 0}
    if index is None or not index.status.get("scanned"):
        note = "NAV job feed not scanned" + (f": {index.status.get('error')}" if index is not None and index.status.get("error") else "")
        return evidence("jobs", "source_error", "official_nav_job_feed", url, note=note), metrics
    now = index._now()
    postings: list[dict[str, Any]] = []
    for ad in index.candidates(str(profile.get("name") or "")):
        entry = index.fetch_entry(ad)
        metrics["requests"] += 1
        data = (entry or {}).get("json") or {}
        employer = data.get("employer") or {}
        if "".join(ch for ch in str(employer.get("orgnr") or "") if ch.isdigit()) != org:
            continue
        if str((entry or {}).get("status") or "") != "ACTIVE":
            continue
        expires = _parse_dt(data.get("expires"))
        if expires is not None and expires <= now:
            continue
        locations = data.get("workLocations") or []
        city = (locations[0].get("municipal") or locations[0].get("city")) if locations and isinstance(locations[0], dict) else None
        postings.append({
            "title": str(data.get("title") or data.get("jobtitle") or "").strip()[:200],
            "published": str(data.get("published") or "")[:10] or None,
            "expires": str(data.get("expires") or "")[:10] or None,
            "municipality": city,
            "url": AD_PAGE.format(uuid=ad["uuid"]),
        })
    if index.status.get("truncated"):
        note = "NAV job feed scan was cut short by the run budget; absence of ads cannot be concluded"
        if not postings:
            return evidence("jobs", "source_error", "official_nav_job_feed", url, note=note), metrics
    if not postings:
        return evidence("jobs", "not_found", "official_nav_job_feed", url, note="No active NAV job ad carries this organisation number."), metrics
    postings.sort(key=lambda p: p["published"] or "", reverse=True)
    value = {"active_count": len(postings), "postings": postings[:MAX_POSTINGS_PUBLISHED], "scan": {"pages": index.status["pages"], "active_ads_in_feed": index.status["active_ads"]}}
    digest = hashlib.sha256(json.dumps(value["postings"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return evidence("jobs", "available", "official_nav_job_feed", postings[0]["url"], value=value, content_sha256=digest, note="Active ads only, matched by the organisation number in NAV's own record; contact details are never published."), metrics
