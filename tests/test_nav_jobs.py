from __future__ import annotations

import json
import unittest
import urllib.error
from datetime import datetime, timezone

from norway_company_agent.nav_jobs import NavJobsIndex, jobs_record
from norway_company_agent.signalpost_run import Budget, run_batch
from norway_company_agent.synthesis import check_synthesis
from test_signalpost_run import MODULES, FakeApi, rows_for, site_ok

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


class Resp:
    def __init__(self, status, body):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def item(uuid, business, status="ACTIVE"):
    return {"id": f"e-{uuid}", "url": f"/api/v1/feedentry/{uuid}", "title": "t", "_feed_entry": {"uuid": uuid, "status": status, "businessName": business, "municipal": "OSLO", "sistEndret": "2026-10-10T00:00:00Z"}}


def entry(uuid, orgnr, status="ACTIVE", expires="2026-11-30T00:00:00Z", title="Barista"):
    return {"uuid": uuid, "status": status, "json": {"uuid": uuid, "title": title, "published": "2026-10-09T08:00:00Z", "expires": expires, "employer": {"name": "x", "orgnr": orgnr}, "workLocations": [{"municipal": "OSLO"}], "description": "SECRET DESCRIPTION", "contactList": [{"name": "Kari", "email": "kari@x.no", "phone": "99999999"}]}}


class FakeNav:
    def __init__(self, pages, entries, token_status=200, extra_page2=True):
        self.pages, self.entries, self.token_status = pages, entries, token_status
        self.calls = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.calls.append(url)
        if url.endswith("/api/publicToken"):
            return Resp(self.token_status, b"PUBLICTOKEN") if self.token_status == 200 else (_ for _ in ()).throw(urllib.error.HTTPError(url, self.token_status, "x", {}, None))
        assert request.get_header("Authorization") == "Bearer PUBLICTOKEN", "feed calls must carry the bearer token"
        if "/feedentry/" in url:
            uuid = url.rsplit("/", 1)[1]
            return Resp(200, self.entries[uuid]) if uuid in self.entries else (_ for _ in ()).throw(urllib.error.HTTPError(url, 404, "x", {}, None))
        key = "p2" if url.endswith("/p2") else "p1"
        return Resp(200, self.pages[key])


def standard():
    pages = {
        "p1": {"next_url": "/api/v1/feed/p2", "items": [item("a1", "Norsk Kaffe AS"), item("a2", "Norsk Kaffe AS"), item("b1", "Annen Bedrift AS"), item("c1", "Equinor ASA")]},
        "p2": {"next_url": None, "items": [item("c1", "Equinor ASA", status="INACTIVE"), item("d1", "Equinor ASA")]},
    }
    entries = {
        "a1": entry("a1", "914778271"),
        "a2": entry("a2", "111111111"),  # same name, different company
        "b1": entry("b1", "222222222"),
        "d1": entry("d1", "923609016", title="Drilling engineer"),
    }
    return pages, entries


PROFILE = {"organisation_number": "914778271", "name": "NORSK KAFFE AS"}


class NavJobsTests(unittest.TestCase):
    def index(self, **kw):
        pages, entries = standard()
        fake = FakeNav(pages, entries, **kw)
        return NavJobsIndex(opener=fake, now=lambda: NOW), fake

    def test_scan_keeps_only_active_ads_with_latest_status(self):
        index, _ = self.index()
        status = index.scan()
        self.assertTrue(status["scanned"])
        self.assertEqual(status["pages"], 2)
        self.assertEqual(status["active_ads"], 4)  # a1, a2, b1, d1 ; c1 became INACTIVE

    def test_exact_org_number_decides_and_contacts_are_never_kept(self):
        index, fake = self.index()
        index.scan()
        record, metrics = jobs_record(PROFILE, index)
        self.assertEqual(record["status"], "available")
        self.assertEqual(record["value"]["active_count"], 1)  # a2 has the same name but another organisation number
        self.assertEqual(metrics["requests"], 2)  # both same-name candidates were checked
        dump = json.dumps(record)
        for forbidden in ("SECRET DESCRIPTION", "kari@x.no", "99999999", "Kari"):
            self.assertNotIn(forbidden, dump)
        self.assertEqual(record["value"]["postings"][0]["url"], "https://arbeidsplassen.nav.no/stillinger/stilling/a1")

    def test_inactive_and_expired_entries_are_not_published(self):
        pages, entries = standard()
        entries["a1"] = entry("a1", "914778271", expires="2026-10-01T00:00:00Z")
        index = NavJobsIndex(opener=FakeNav(pages, entries), now=lambda: NOW)
        index.scan()
        record, _ = jobs_record(PROFILE, index)
        self.assertEqual(record["status"], "not_found")
        entries["a1"] = entry("a1", "914778271", status="INACTIVE")
        record, _ = jobs_record(PROFILE, NavJobsIndex(opener=FakeNav(pages, entries), now=lambda: NOW).__class__(opener=FakeNav(pages, entries), now=lambda: NOW))
        self.assertEqual(record["status"], "source_error")  # unscanned index never claims absence

    def test_token_failure_is_a_source_error_not_a_crash(self):
        index, _ = self.index(token_status=500)
        status = index.scan()
        self.assertFalse(status["scanned"])
        self.assertIn("HTTP 500", status["error"] + "HTTPError")
        record, _ = jobs_record(PROFILE, index)
        self.assertEqual(record["status"], "source_error")

    def test_truncated_scan_never_concludes_absence(self):
        pages, entries = standard()
        index = NavJobsIndex(opener=FakeNav(pages, entries), now=lambda: NOW, max_pages=1)
        index.scan()
        self.assertTrue(index.status["truncated"])
        record, _ = jobs_record({"organisation_number": "000000001", "name": "UKJENT FIRMA AS"}, index)
        self.assertEqual(record["status"], "source_error")
        record, _ = jobs_record(PROFILE, index)
        self.assertEqual(record["status"], "available")  # a positive, confirmed match is still valid

    def test_unknown_company_is_not_available_after_a_complete_scan(self):
        index, _ = self.index()
        index.scan()
        record, metrics = jobs_record({"organisation_number": "000000001", "name": "UKJENT FIRMA AS"}, index)
        self.assertEqual(record["status"], "not_found")
        self.assertEqual(metrics["requests"], 0)


class JobsIntegrationTests(unittest.TestCase):
    def test_jobs_flow_into_claims_summary_and_validation(self):
        pages, entries = standard()
        index = NavJobsIndex(opener=FakeNav(pages, entries), now=lambda: NOW)
        envelopes, _, report = run_batch(rows_for("923609016", "000000000"), run_id="t", modules=MODULES + ["jobs"], budget=Budget(10_000, 10_000), workers=1, fetcher=FakeApi(), site_fetcher=site_ok, discovery_fetcher=None, reverifier=None, jobs_index=index)
        claims = {c["field"]: c for c in envelopes[0]["claims"]}
        self.assertEqual(claims["job_postings"]["availability"], "available")
        self.assertEqual(claims["job_postings"]["value"]["postings"][0]["title"], "Drilling engineer")
        self.assertTrue(claims["job_postings"]["evidence_ids"])
        text = " ".join(s["text"] for s in envelopes[0]["synthesis"]["sentences"])
        self.assertIn("1 active job ad(s) on NAV's Arbeidsplassen", text)
        self.assertEqual(check_synthesis(envelopes[0]), [])
        self.assertTrue(report["validation"]["passed"], report["validation"])
        self.assertEqual(report["jobs_feed"]["active_ads"], 4)
        self.assertEqual(report["operations"]["requests_by_phase"]["jobs_confirm"], 1)
        missing = {c["field"]: c for c in envelopes[1]["claims"]}["job_postings"]
        self.assertEqual(missing["availability"], "not_available")
        self.assertIsNone(missing["value"])

    def test_feed_outage_degrades_to_failed_jobs_only(self):
        pages, entries = standard()
        index = NavJobsIndex(opener=FakeNav(pages, entries, token_status=503), now=lambda: NOW)
        envelopes, _, report = run_batch(rows_for("923609016"), run_id="t", modules=MODULES + ["jobs"], budget=Budget(10_000, 10_000), workers=1, fetcher=FakeApi(), site_fetcher=site_ok, discovery_fetcher=None, reverifier=None, jobs_index=index)
        self.assertEqual(envelopes[0]["modules"]["jobs"]["availability"], "failed")
        self.assertEqual(envelopes[0]["modules"]["financials"]["availability"], "available")
        self.assertTrue(report["validation"]["passed"], report["validation"])


if __name__ == "__main__":
    unittest.main()
