from __future__ import annotations

import unittest

from norway_company_agent.domain_discovery import (
    candidate_hosts,
    discover_website,
    name_tokens,
    org_number_pattern,
    page_prints_org_number,
    verify_host,
)
from norway_company_agent.evidence import evidence

ORG = "914778271"
PROFILE = {"organisation_number": ORG, "name": "NORSK KAFFE AS", "website": "", "evidence": {}}


def page(html: str, url: str = "https://norskkaffe.no/") -> dict:
    return {"ok": True, "url": url, "final_url": url, "html": html, "requests": 2, "bytes": len(html), "latency_ms": 5}


def site(url):
    value = {"requested_url": url, "final_url": url, "title": "Norsk Kaffe", "description": "", "main_text_excerpt": "Kaffe " * 40, "social_links": [{"platform": "facebook", "url": "https://facebook.com/norskkaffe"}], "structured_organisations": [], "pages": []}
    return evidence("website", "available", "registry_linked_company_website", url, value=value, content_sha256="a" * 64), {"requests": 3, "bytes": 10, "latencies_ms": [5]}


class CandidateTests(unittest.TestCase):
    def test_norwegian_letters_and_legal_suffix(self):
        self.assertEqual(name_tokens("Bjørn & Åse Elektro AS"), ["bjorn", "ase", "elektro"])
        hosts = candidate_hosts("NORSK KAFFE AS")
        self.assertEqual(hosts[0], "norskkaffe.no")
        self.assertLessEqual(len(hosts), 4)

    def test_no_usable_name_gives_no_candidates(self):
        self.assertEqual(candidate_hosts("AS"), [])
        self.assertEqual(candidate_hosts("X AS"), [])

    def test_org_number_matching_is_exact(self):
        self.assertTrue(page_prints_org_number("<footer>Org.nr 914 778 271 MVA</footer>", ORG))
        self.assertTrue(page_prints_org_number("<p>914778271</p>", ORG))
        self.assertTrue(page_prints_org_number("<p>914.778.271</p>", ORG))
        self.assertFalse(page_prints_org_number("<p>Tlf 1914778271</p>", ORG))
        self.assertFalse(page_prints_org_number("<p>9147782710</p>", ORG))
        self.assertFalse(page_prints_org_number("<script>var a='914778271'</script><p>hei</p>", ORG))
        self.assertFalse(page_prints_org_number("<p>domain is for sale 914778271</p>", ORG))
        with self.assertRaises(ValueError):
            org_number_pattern("12")


class DiscoveryTests(unittest.TestCase):
    def test_publishes_only_when_org_number_printed(self):
        fetch = lambda url: page("<html><footer>Org.nr 914 778 271</footer></html>")
        record, metrics = discover_website(PROFILE, resolver=lambda h: True, fetch_page=fetch, site_fetcher=site)
        self.assertEqual(record["status"], "available")
        assessment = record["value"]["identity_assessment"]
        self.assertTrue(assessment["publishable"])
        self.assertEqual(assessment["method"], "domain_guess_exact_org_number_v1")
        self.assertEqual(record["source_type"], "company_website_discovered_by_exact_org_number")
        self.assertTrue(metrics["verified"])

    def test_name_match_without_org_number_is_not_published(self):
        fetch = lambda url: page("<html><title>Norsk Kaffe AS</title><p>Norsk Kaffe AS selger kaffe</p></html>")
        record, metrics = discover_website(PROFILE, resolver=lambda h: True, fetch_page=fetch, site_fetcher=site)
        self.assertEqual(record["status"], "not_found")
        self.assertFalse(metrics["verified"])
        self.assertIsNone(record.get("value"))

    def test_other_companys_org_number_is_not_accepted(self):
        fetch = lambda url: page("<footer>Org.nr 923 609 016</footer>")
        record, _ = discover_website(PROFILE, resolver=lambda h: True, fetch_page=fetch, site_fetcher=site)
        self.assertEqual(record["status"], "not_found")

    def test_unresolvable_hosts_cost_no_requests(self):
        calls = []
        record, metrics = discover_website(PROFILE, resolver=lambda h: False, fetch_page=lambda u: calls.append(u) or page(""), site_fetcher=site)
        self.assertEqual(calls, [])
        self.assertEqual(metrics["requests"], 0)
        self.assertEqual(record["status"], "not_found")

    def test_failed_fetch_publishes_nothing(self):
        fetch = lambda url: {"ok": False, "error": "robots.txt disallows this user agent", "requests": 1, "bytes": 0}
        record, _ = discover_website(PROFILE, resolver=lambda h: True, fetch_page=fetch, site_fetcher=site)
        self.assertEqual(record["status"], "not_found")
        self.assertIn("Nothing published", record["note"])

    def test_org_number_on_contact_page_is_found(self):
        def fetch(url):
            if url.endswith("/kontakt"):
                return page("<p>Org.nr 914778271</p>", "https://norskkaffe.no/kontakt")
            return page('<html><a href="/kontakt">Kontakt oss</a></html>')

        result = verify_host("norskkaffe.no", ORG, fetch)
        self.assertTrue(result["verified"])
        self.assertTrue(result["page_url"].endswith("/kontakt"))

    def test_request_cap_stops_candidate_loop(self):
        seen = []

        def fetch(url):
            seen.append(url)
            return page("<p>intet</p>", url)

        _, metrics = discover_website(PROFILE, resolver=lambda h: True, fetch_page=fetch, site_fetcher=site, max_requests=2)
        self.assertEqual(metrics["candidates_tried"], 1)

    def test_social_links_follow_the_kit_identity_rule(self):
        fetch = lambda url: page("<footer>914778271</footer>")
        record, _ = discover_website(PROFILE, resolver=lambda h: True, fetch_page=fetch, site_fetcher=site)
        self.assertEqual(record["value"]["social_links"], [{"platform": "facebook", "url": "https://facebook.com/norskkaffe"}])


if __name__ == "__main__":
    unittest.main()
