from __future__ import annotations

import datetime as dt
import unittest
from urllib.parse import parse_qs, urlparse

from norway_company_agent.http import FetchResult
from norway_company_agent.registry_updates import fetch_registry_updates

A, B = "923609016", "914778271"


def feed(items, status=200):
    calls = []

    def fetcher(url):
        calls.append(url)
        if status != 200:
            return FetchResult(url, status, 5, 0, error=f"HTTP {status}")
        return FetchResult(url, 200, 5, 10, {"_embedded": {"oppdaterteEnheter": items}}, content_sha256="u" * 64, retrieved_at="2026-10-25T00:00:00Z")

    return fetcher, calls


class RegistryUpdatesTests(unittest.TestCase):
    def test_one_request_per_chunk_and_values_never_copied(self):
        items = [
            {"oppdateringsid": 7, "dato": "2026-09-01T10:00:00.000Z", "organisasjonsnummer": A, "endringstype": "Endring", "endringer": [{"op": "replace", "path": "/forretningsadresse/adresse", "value": ["Ny gate 1"]}, {"op": "replace", "path": "/telefon", "value": "99999999"}]},
            {"oppdateringsid": 3, "dato": "2026-02-01T10:00:00.000Z", "organisasjonsnummer": A, "endringstype": "Endring", "endringer": [{"op": "replace", "path": "/navn", "value": "X"}]},
            {"oppdateringsid": 9, "dato": "2026-09-02T10:00:00.000Z", "organisasjonsnummer": "999999999", "endringstype": "Ny"},
        ]
        fetcher, calls = feed(items)
        records, metrics = fetch_registry_updates([A, B], fetcher=fetcher, today=dt.date(2026, 10, 25))
        self.assertEqual(len(calls), 1)
        query = parse_qs(urlparse(calls[0]).query)
        self.assertEqual(query["organisasjonsnummer"][0], f"{A},{B}")
        self.assertTrue(query["dato"][0].startswith("2025-10-25"))
        value = records[A]["value"]
        self.assertEqual(records[A]["status"], "available")
        self.assertEqual(value["update_count"], 2)
        self.assertEqual(value["latest_update"], "2026-09-01")
        self.assertEqual(value["changed_fields"], ["business address", "name"])
        self.assertNotIn("Ny gate", str(value))
        self.assertNotIn("99999999", str(value))
        self.assertEqual(records[B]["status"], "not_found")
        self.assertEqual(metrics["events"], 2)

    def test_failed_feed_marks_only_that_chunk_failed(self):
        fetcher, _ = feed([], status=503)
        records, metrics = fetch_registry_updates([A], fetcher=fetcher)
        self.assertEqual(records[A]["status"], "source_error")
        self.assertEqual(metrics["failed_chunks"], 1)

    def test_contract_claim_synthesis_and_validation(self):
        from test_signalpost_run import MODULES, FakeApi, rows_for, site_ok

        from norway_company_agent.signalpost_run import Budget, run_batch

        class Api(FakeApi):
            def __call__(self, url):
                if "/oppdateringer/" in url:
                    self.calls.append(url)
                    return FetchResult(url, 200, 5, 10, {"_embedded": {"oppdaterteEnheter": [{"oppdateringsid": 1, "dato": "2026-09-01T00:00:00.000Z", "organisasjonsnummer": A, "endringstype": "Endring", "endringer": [{"op": "replace", "path": "/navn"}]}]}}, content_sha256="u" * 64, retrieved_at="2026-10-25T00:00:00Z")
                return super().__call__(url)

        envelopes, _, report = run_batch(rows_for(A, B, "000000000"), run_id="t", modules=MODULES + ["updates"], budget=Budget(10_000, 10_000), workers=1, fetcher=Api(), site_fetcher=site_ok, discovery_fetcher=None, reverifier=None)
        self.assertTrue(report["validation"]["passed"], report["validation"])
        claims = {c["field"]: c for c in envelopes[0]["claims"]}
        self.assertEqual(claims["recent_registry_changes"]["availability"], "available")
        self.assertTrue(claims["recent_registry_changes"]["evidence_ids"])
        text = " ".join(s["text"] for s in envelopes[0]["synthesis"]["sentences"])
        self.assertIn("latest on 2026-09-01", text)
        self.assertEqual({c["field"]: c for c in envelopes[1]["claims"]}["recent_registry_changes"]["availability"], "not_available")
        self.assertEqual(envelopes[2]["modules"]["updates"]["availability"], "not_available")
        self.assertEqual(report["operations"]["requests_by_phase"]["updates"], 1)
