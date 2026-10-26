from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlparse

from norway_company_agent.domain_discovery import discover_website, subunit_hosts
from norway_company_agent.evidence import evidence
from norway_company_agent.http import FetchResult
from norway_company_agent.official import normalize_locations
from norway_company_agent.wikidata import build_query, wikidata_websites

ORG = "914778271"


def page(html, url):
    return {"ok": True, "url": url, "final_url": url, "html": html, "requests": 2, "bytes": len(html), "latency_ms": 5}


def site(url):
    value = {"requested_url": url, "final_url": url, "title": "T", "description": "", "main_text_excerpt": "x " * 40, "social_links": [], "structured_organisations": [], "pages": []}
    return evidence("website", "available", "registry_linked_company_website", url, value=value, content_sha256="a" * 64), {"requests": 1, "bytes": 1, "latencies_ms": [1]}


class WikidataTests(unittest.TestCase):
    def test_one_query_per_chunk_and_only_requested_orgs_kept(self):
        calls = []

        def fetcher(url):
            calls.append(url)
            body = {"results": {"bindings": [
                {"orgnr": {"value": ORG}, "site": {"value": "https://www.norskkaffe.no/"}},
                {"orgnr": {"value": "999999999"}, "site": {"value": "https://other.no/"}},
                {"orgnr": {"value": ORG}, "site": {"value": "ftp://bad"}},
            ]}}
            return FetchResult(url, 200, 5, 10, body)

        found, metrics = wikidata_websites([ORG, "923609016"], fetcher=fetcher)
        self.assertEqual(len(calls), 1)
        query = parse_qs(urlparse(calls[0]).query)["query"][0]
        self.assertIn('"914778271"', query)
        self.assertIn("wdt:P2333", query)
        self.assertEqual(found, {ORG: ["https://www.norskkaffe.no/"]})
        self.assertEqual(metrics["matches"], 1)

    def test_failure_yields_no_candidates(self):
        found, metrics = wikidata_websites([ORG], fetcher=lambda u: FetchResult(u, 500, 1, 0, None))
        self.assertEqual(found, {})
        self.assertEqual(metrics["failed_chunks"], 1)
        self.assertNotIn('"12"', build_query(["12", ORG]))


class SubunitAndWikidataCandidateTests(unittest.TestCase):
    def test_subunit_registry_hosts(self):
        body = {"_embedded": {"underenheter": [{"organisasjonsnummer": "1", "navn": "A", "hjemmeside": "www.kaffebar.no", "epostadresse": "post@kaffebar.no"}, {"organisasjonsnummer": "2", "epostadresse": "ola@gmail.com"}]}}
        locations = normalize_locations(body)
        self.assertEqual(locations["locations"][0]["email_domain"], "kaffebar.no")
        profile = {"organisation_number": ORG, "name": "NORSK KAFFE AS", "evidence": {"locations": {"status": "available", "value": locations}}}
        self.assertEqual(subunit_hosts(profile), ["kaffebar.no"])

    def test_wikidata_candidate_is_tried_first_and_still_needs_org_number(self):
        profile = {"organisation_number": ORG, "name": "NORSK KAFFE AS", "evidence": {}, "wikidata_websites": ["https://www.kaffe-group.no/"]}
        seen = []

        def fetch(url):
            seen.append(url)
            return page("<footer>Org.nr 914 778 271</footer>", url)

        record, _ = discover_website(profile, resolver=lambda h: True, fetch_page=fetch, site_fetcher=site)
        self.assertTrue(seen[0].startswith("https://kaffe-group.no/"))
        self.assertEqual(record["value"]["identity_assessment"]["method"], "wikidata_candidate_exact_org_number_v1")
        record, _ = discover_website(profile, resolver=lambda h: True, fetch_page=lambda u: page("<p>no number</p>", u), site_fetcher=site)
        self.assertNotEqual(record["status"], "available")
