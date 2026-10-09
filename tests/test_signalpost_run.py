from __future__ import annotations

import http.server
import threading
import unittest
import urllib.request
from urllib.parse import parse_qs, urlparse

from norway_company_agent.evidence import evidence
from norway_company_agent.http import FetchResult
from norway_company_agent.signalpost_run import (
    AVAILABILITY_STATES,
    Budget,
    BudgetExceeded,
    read_rows,
    run_batch,
)

MODULES = ["registry", "accounting_obligation", "registry_live", "financials", "roles", "group", "locations", "website"]

ENTITIES = {
    "923609016": {"organisasjonsnummer": "923609016", "navn": "EQUINOR ASA", "organisasjonsform": {"kode": "ASA"}, "antallAnsatte": 21272, "hjemmeside": "www.equinor.com", "naeringskode1": {"kode": "06.100", "beskrivelse": "Utvinning av råolje"}, "forretningsadresse": {"kommune": "STAVANGER", "kommunenummer": "1103"}},
    "914778271": {"organisasjonsnummer": "914778271", "navn": "NORSK KAFFE AS", "organisasjonsform": {"kode": "AS"}, "antallAnsatte": 3, "hjemmeside": "", "naeringskode1": {"kode": "10.830", "beskrivelse": "Kaffe"}, "forretningsadresse": {"kommune": "OSLO", "kommunenummer": "0301"}},
}


class FakeApi:
    def __init__(self, entities=None, omit_from_batch=()):
        self.entities = entities or ENTITIES
        self.omit = set(omit_from_batch)
        self.calls: list[str] = []

    def __call__(self, url: str) -> FetchResult:
        self.calls.append(url)
        parsed = urlparse(url)
        if parsed.path.endswith("/enheter") and "organisasjonsnummer" in parse_qs(parsed.query):
            orgs = parse_qs(parsed.query)["organisasjonsnummer"][0].split(",")
            rows = [self.entities[o] for o in orgs if o in self.entities and o not in self.omit]
            return FetchResult(url, 200, 5, 10, {"_embedded": {"enheter": rows}, "page": {"totalPages": 1}}, content_sha256="b" * 64, retrieved_at="2026-10-08T00:00:00Z")
        if "/enheter/" in parsed.path and parsed.path.count("/") == 4:
            org = parsed.path.rsplit("/", 1)[1]
            if org in self.entities:
                return FetchResult(url, 200, 5, 10, self.entities[org], content_sha256="c" * 64, retrieved_at="2026-10-08T00:00:00Z")
            return FetchResult(url, 404, 5, 0, error="HTTP 404", retrieved_at="2026-10-08T00:00:00Z")
        if "regnskap" in parsed.path:
            return FetchResult(url, 200, 5, 10, [{"id": 1, "regnskapstype": "SELSKAP", "valuta": "NOK", "regnskapsperiode": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"}, "resultatregnskapResultat": {"aarsresultat": 5}, "eiendeler": {"sumEiendeler": 10}}], content_sha256="d" * 64, retrieved_at="2026-10-08T00:00:00Z")
        if "roller" in parsed.path:
            return FetchResult(url, 200, 5, 10, {"rollegrupper": [{"type": {"kode": "STYR", "beskrivelse": "Styre"}, "roller": [{"type": {"kode": "LEDE", "beskrivelse": "Styrets leder"}, "person": {"navn": {"fornavn": "Kari", "etternavn": "Nordmann"}, "fodselsdato": "1970-01-01"}, "avregistrert": False}]}]}, content_sha256="e" * 64, retrieved_at="2026-10-08T00:00:00Z")
        return FetchResult(url, 404, 5, 0, error="HTTP 404", retrieved_at="2026-10-08T00:00:00Z")


def site_ok(url):
    value = {"requested_url": "https://equinor.com/", "final_url": "https://equinor.com/", "title": "Equinor ASA energy company", "description": "", "main_text_excerpt": "Equinor ASA is an energy company. " * 10, "social_links": [], "structured_organisations": [], "pages": []}
    return evidence("website", "available", "registry_linked_company_website", "https://equinor.com/", value=value, content_sha256="f" * 64), {"requests": 2, "bytes": 100, "latencies_ms": [10]}


def site_wrong(url):
    value = {"requested_url": "https://other.example/", "final_url": "https://other.example/", "title": "A completely different business", "description": "", "main_text_excerpt": "Totally unrelated shop selling shoes. " * 10, "social_links": [], "structured_organisations": [], "pages": []}
    return evidence("website", "available", "registry_linked_company_website", "https://other.example/", value=value, content_sha256="a" * 64), {"requests": 2, "bytes": 100, "latencies_ms": [10]}


def rows_for(*raw):
    out = []
    for item in raw:
        digits = "".join(ch for ch in item if ch.isdigit())
        out.append({"raw": item, "organisation_number": digits if len(digits) == 9 else None})
    return out


def run(raw, *, api=None, site=site_ok, budget=None, previous=None, workers=1, discovery=None, reverify=None):
    api = api or FakeApi()
    budget = budget or Budget(10_000, 10_000)
    envelopes, profiles, report = run_batch(rows_for(*raw), run_id="t", modules=MODULES, budget=budget, previous=previous, workers=workers, fetcher=api, site_fetcher=site, discovery_fetcher=discovery, reverifier=reverify)
    return envelopes, profiles, report, api


class BadInputTests(unittest.TestCase):
    def test_one_envelope_per_row_in_order_for_bad_duplicate_and_unknown(self):
        envelopes, _, report, _ = run(["923609016", "923609016", "12", "000000000", "914778271"])
        self.assertEqual([e["organisation_number"] for e in envelopes], ["923609016", "923609016", "12", "000000000", "914778271"])
        self.assertTrue(report["validation"]["passed"], report["validation"])
        by_org = {e["organisation_number"]: e for e in envelopes}
        self.assertEqual(by_org["12"]["modules"]["registry"]["availability"], "failed")
        self.assertEqual(by_org["000000000"]["modules"]["financials"]["availability"], "not_available")
        self.assertEqual(by_org["923609016"]["modules"]["registry"]["availability"], "available")

    def test_unknown_org_has_no_invented_values(self):
        envelopes, _, _, _ = run(["000000000"])
        for claim in envelopes[0]["claims"]:
            self.assertIsNone(claim["value"])
            self.assertNotEqual(claim["availability"], "available")

    def test_all_states_are_the_six_contract_states(self):
        envelopes, _, report, _ = run(["923609016", "914778271", "000000000", "x"])
        for e in envelopes:
            for state in e["modules"].values():
                self.assertIn(state["availability"], AVAILABILITY_STATES)
        self.assertEqual(sum(report["availability_totals"].values()), 4 * len(MODULES))


class AnchorTests(unittest.TestCase):
    def test_batch_lookup_used_and_direct_only_for_missing(self):
        api = FakeApi(omit_from_batch={"914778271"})
        _, _, report, api = run(["923609016", "914778271"], api=api)
        batch_calls = [c for c in api.calls if "?organisasjonsnummer=" in c]
        self.assertEqual(len(batch_calls), 1)
        self.assertIn("size=2", batch_calls[0])
        self.assertEqual(report["registry_anchor"]["from_live_batch"], 1)
        self.assertEqual(report["registry_anchor"]["from_direct"], 1)

    def test_live_anchor_does_not_refetch_registry_live(self):
        api = FakeApi()
        run(["923609016"], api=api)
        direct = [c for c in api.calls if c.endswith("/enheter/923609016")]
        self.assertEqual(direct, [])

    def test_missing_bulk_file_falls_back_to_live(self):
        envelopes, _, report = run_batch(rows_for("923609016"), run_id="t", modules=MODULES, budget=Budget(1000, 1000), bulk_path="/does/not/exist.csv", workers=1, fetcher=FakeApi(), site_fetcher=site_ok, discovery_fetcher=None, reverifier=None)
        self.assertEqual(envelopes[0]["modules"]["registry"]["availability"], "available")
        self.assertFalse(report["registry_anchor"]["bulk_used"] and report["registry_anchor"]["from_bulk"])


class WebsiteTests(unittest.TestCase):
    def test_unverified_website_is_ambiguous_and_unpublished(self):
        envelopes, _, _, _ = run(["923609016"], site=site_wrong)
        self.assertEqual(envelopes[0]["modules"]["website"]["availability"], "ambiguous")
        claim = next(c for c in envelopes[0]["claims"] if c["field"] == "official_website")
        self.assertEqual(claim["availability"], "ambiguous")
        self.assertIsNone(claim["value"])

    def test_verified_website_is_published_with_evidence(self):
        envelopes, _, report, _ = run(["923609016"], site=site_ok)
        claim = next(c for c in envelopes[0]["claims"] if c["field"] == "official_website")
        self.assertEqual(claim["availability"], "available")
        self.assertEqual(claim["value"], "https://equinor.com/")
        ids = {ev["id"] for ev in envelopes[0]["evidence"]}
        self.assertTrue(set(claim["evidence_ids"]) <= ids and claim["evidence_ids"])
        self.assertTrue(report["validation"]["passed"], report["validation"])

    def test_website_phase_degrades_before_official_phase(self):
        budget = Budget(100, 10_000)
        budget.requests = 95
        envelopes, _, _, _ = run(["923609016"], budget=budget)
        self.assertEqual(envelopes[0]["modules"]["website"]["availability"], "failed")
        self.assertEqual(envelopes[0]["modules"]["financials"]["availability"], "available")


class BudgetTests(unittest.TestCase):
    def test_guard_counts_requests_and_refuses_after_limit(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/"
        budget = Budget(2, 100)
        uninstall = budget.install()
        try:
            urllib.request.urlopen(url).read()
            urllib.request.urlopen(url).read()
            with self.assertRaises(BudgetExceeded):
                urllib.request.urlopen(url)
        finally:
            uninstall()
            server.shutdown()
        self.assertEqual(budget.requests, 2)
        self.assertEqual(budget.refused, 1)

    def test_time_limit_refuses(self):
        clock = iter([0.0, 5.0, 5.0, 5.0])
        budget = Budget(100, 1.0, clock=lambda: next(clock))
        with self.assertRaises(BudgetExceeded):
            budget.acquire()


class RefreshAndInputTests(unittest.TestCase):
    def test_changes_reported_against_previous_profile(self):
        _, profiles, _, _ = run(["923609016"])
        previous = {"923609016": {**profiles[0], "employees": 1}}
        envelopes, _, _, _ = run(["923609016"], previous=previous)
        fields = [c["field"] for c in envelopes[0]["changes"]]
        self.assertIn("registry.employees", fields)

    def test_no_changes_when_identical(self):
        _, profiles, _, _ = run(["923609016"])
        envelopes, _, _, _ = run(["923609016"], previous={"923609016": profiles[0]})
        self.assertEqual([c for c in envelopes[0]["changes"] if c["field"].startswith("registry.")], [])

    def test_read_rows_never_raises_on_bad_lines(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "in.jsonl"
            path.write_text('{"organisation_number":"923 609 016"}\nnot json\n{"organisation_number":"12"}\n', encoding="utf-8")
            rows = read_rows(path)
        self.assertEqual([r["organisation_number"] for r in rows], ["923609016", None, None])


class DiscoveryIntegrationTests(unittest.TestCase):
    @staticmethod
    def found(profile):
        record = evidence("website", "available", "company_website_discovered_by_exact_org_number", "https://norskkaffe.no/", value={"final_url": "https://norskkaffe.no/", "title": "Norsk Kaffe", "social_links": [], "identity_assessment": {"publishable": True, "score": 1.0, "status": "exact", "method": "domain_guess_exact_org_number_v1"}}, content_sha256="9" * 64)
        return record, {"requests": 5, "bytes": 50, "latencies_ms": [5], "candidates_tried": 1, "verified": True}

    @staticmethod
    def missed(profile):
        return evidence("website", "not_found", "domain_discovery", "https://data.brreg.no/x", note="none verified"), {"requests": 2, "bytes": 0, "latencies_ms": [], "candidates_tried": 1, "verified": False}

    def test_company_without_registry_website_is_discovered_and_cited(self):
        envelopes, _, report, _ = run(["914778271"], discovery=self.found)
        claim = next(c for c in envelopes[0]["claims"] if c["field"] == "official_website")
        self.assertEqual(claim["availability"], "available")
        self.assertEqual(claim["value"], "https://norskkaffe.no/")
        self.assertTrue(claim["evidence_ids"])
        self.assertEqual(report["discovery"], {"attempted": 1, "verified": 1, "method": "domain_guess_exact_org_number_v1"})
        self.assertEqual(report["operations"]["requests_by_phase"]["discovery"], 5)
        self.assertTrue(report["validation"]["passed"], report["validation"])

    def test_undiscovered_website_is_not_available_with_no_value(self):
        envelopes, _, _, _ = run(["914778271"], discovery=self.missed)
        claim = next(c for c in envelopes[0]["claims"] if c["field"] == "official_website")
        self.assertEqual(claim["availability"], "not_available")
        self.assertIsNone(claim["value"])

    def test_company_with_registry_website_does_not_use_discovery(self):
        calls = []
        envelopes, _, _, _ = run(["923609016"], discovery=lambda p: calls.append(p) or self.found(p))
        self.assertEqual(calls, [])
        self.assertEqual(envelopes[0]["modules"]["website"]["availability"], "available")

    def test_discovery_is_skipped_when_budget_is_tight(self):
        budget = Budget(100, 10_000)
        budget.requests = 75
        calls = []
        envelopes, _, _, _ = run(["914778271"], budget=budget, discovery=lambda p: calls.append(p) or self.found(p))
        self.assertEqual(calls, [])
        self.assertEqual(envelopes[0]["modules"]["website"]["availability"], "not_available")

    def test_discovery_crash_never_breaks_the_batch(self):
        def boom(profile):
            raise RuntimeError("dns exploded")

        envelopes, _, report, _ = run(["914778271", "923609016"], discovery=boom)
        self.assertEqual(len(envelopes), 2)
        self.assertEqual(envelopes[0]["modules"]["website"]["availability"], "failed")
        self.assertTrue(report["validation"]["passed"], report["validation"])


class ReverifyIntegrationTests(unittest.TestCase):
    def test_unverified_registry_website_is_upgraded_when_footer_prints_org_number(self):
        from norway_company_agent.domain_discovery import reverify_registry_website

        fetch = lambda url: {"ok": True, "url": url, "final_url": url, "html": "<footer>Org.nr 923 609 016</footer>", "requests": 2, "bytes": 30, "latency_ms": 4}
        envelopes, _, report, _ = run(["923609016"], site=site_wrong, reverify=lambda p, r: reverify_registry_website(p, r, fetch_page=fetch))
        claim = next(c for c in envelopes[0]["claims"] if c["field"] == "official_website")
        self.assertEqual(claim["availability"], "available")
        self.assertTrue(report["validation"]["passed"], report["validation"])

    def test_registry_website_stays_ambiguous_without_the_number(self):
        from norway_company_agent.domain_discovery import reverify_registry_website

        fetch = lambda url: {"ok": True, "url": url, "final_url": url, "html": "<p>Shoes for sale</p>", "requests": 2, "bytes": 20, "latency_ms": 4}
        envelopes, _, _, _ = run(["923609016"], site=site_wrong, reverify=lambda p, r: reverify_registry_website(p, r, fetch_page=fetch))
        self.assertEqual(envelopes[0]["modules"]["website"]["availability"], "ambiguous")

    def test_already_verified_website_is_not_refetched(self):
        from norway_company_agent.domain_discovery import reverify_registry_website

        calls = []
        fetch = lambda url: calls.append(url) or {"ok": False, "requests": 1}
        run(["923609016"], site=site_ok, reverify=lambda p, r: reverify_registry_website(p, r, fetch_page=fetch))
        self.assertEqual(calls, [])

    def test_reverify_failure_cannot_break_or_downgrade(self):
        def boom(p, r):
            raise RuntimeError("network down")

        envelopes, _, report, _ = run(["923609016"], site=site_wrong, reverify=boom)
        self.assertEqual(envelopes[0]["modules"]["website"]["availability"], "ambiguous")
        self.assertTrue(report["validation"]["passed"], report["validation"])


if __name__ == "__main__":
    unittest.main()
