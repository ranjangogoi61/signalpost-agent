from __future__ import annotations

import json
import unittest

from norway_company_agent.domain_discovery import discover_website, make_brave_searcher
from norway_company_agent.evidence import evidence
from norway_company_agent.signalpost_run import Budget, website_page_facts
from test_domain_discovery import PROFILE, page, site


class FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def brave_payload(*urls):
    return {"web": {"results": [{"url": u, "title": "t", "description": "d"} for u in urls]}}


class SearcherTests(unittest.TestCase):
    def test_hosts_only_directories_and_social_dropped_and_deduped(self):
        seen = {}

        def opener(request, timeout=None):
            seen["url"] = request.full_url
            seen["token"] = request.get_header("X-subscription-token")
            return FakeResponse(brave_payload("https://www.proff.no/x", "https://norskkaffe.no/om", "https://norskkaffe.no/kontakt", "https://facebook.com/x", "https://kaffe.example/"))

        searcher = make_brave_searcher("KEY123", opener=opener)
        self.assertEqual(searcher(PROFILE), ["norskkaffe.no", "kaffe.example"])
        self.assertEqual(seen["token"], "KEY123")
        self.assertIn("api.search.brave.com", seen["url"])

    def test_budget_cap_stops_searching(self):
        budget = Budget(100, 100)
        calls = []
        searcher = make_brave_searcher("K", charge=lambda: budget.charge(0.005, 0.01), opener=lambda r, timeout=None: calls.append(1) or FakeResponse(brave_payload("https://a-firma.no/")))
        results = [searcher(PROFILE) for _ in range(4)]
        self.assertEqual(len(calls), 2)
        self.assertEqual(results[2:], [[], []])
        self.assertAlmostEqual(budget.api_cost_usd, 0.01)
        self.assertEqual(budget.api_calls, 2)

    def test_api_failure_returns_no_candidates(self):
        def boom(request, timeout=None):
            raise OSError("down")

        self.assertEqual(make_brave_searcher("K", opener=boom)(PROFILE), [])

    def test_search_candidate_published_only_with_exact_org_number(self):
        searcher = lambda profile: ["helt-annet-navn.com"]
        has_number = lambda url: page("<footer>Org.nr 914 778 271</footer>", url)
        record, metrics = discover_website(PROFILE, resolver=lambda h: h == "helt-annet-navn.com", fetch_page=has_number, site_fetcher=site, searcher=searcher)
        self.assertEqual(record["status"], "available")
        self.assertEqual(record["value"]["identity_assessment"]["method"], "search_candidate_exact_org_number_v1")
        self.assertEqual(record["value"]["discovery"]["candidates"][0]["origin"], "search")
        no_number = lambda url: page("<p>Norsk Kaffe AS</p>", url)
        record, _ = discover_website(PROFILE, resolver=lambda h: h == "helt-annet-navn.com", fetch_page=no_number, site_fetcher=site, searcher=searcher)
        self.assertEqual(record["status"], "not_found")

    def test_searcher_crash_falls_back_to_name_guessing(self):
        def boom(profile):
            raise RuntimeError("x")

        fetch = lambda url: page("<footer>914778271</footer>", url)
        record, _ = discover_website(PROFILE, resolver=lambda h: True, fetch_page=fetch, site_fetcher=site, searcher=boom)
        self.assertEqual(record["status"], "available")
        self.assertEqual(record["value"]["identity_assessment"]["method"], "domain_guess_exact_org_number_v1")


class PageFactTests(unittest.TestCase):
    VALUE = {"registered_domain": "norskkaffe.no", "pages": [
        {"url": "https://norskkaffe.no/", "title": "Home", "main_text_excerpt": "Velkommen"},
        {"url": "https://norskkaffe.no/karriere", "title": "Jobb hos oss", "main_text_excerpt": ""},
        {"url": "https://norskkaffe.no/nyheter", "title": "Nyheter", "main_text_excerpt": ""},
        {"url": "https://norskkaffe.no/kontakt", "title": "Kontakt", "main_text_excerpt": "Skriv til post@norskkaffe.no eller tredjepart@gmail.com"},
    ]}

    def test_careers_news_contact_and_on_domain_email(self):
        facts = {f: v for f, v, _ in website_page_facts(self.VALUE, "AS")}
        self.assertEqual(facts["careers_page"], "https://norskkaffe.no/karriere")
        self.assertEqual(facts["news_page"], "https://norskkaffe.no/nyheter")
        self.assertEqual(facts["contact_page"], "https://norskkaffe.no/kontakt")
        self.assertEqual(facts["contact_email"], "post@norskkaffe.no")

    def test_no_email_for_sole_proprietorships_and_none_off_domain(self):
        self.assertNotIn("contact_email", {f for f, _, _ in website_page_facts(self.VALUE, "ENK")})
        other = {"registered_domain": "annet.no", "pages": self.VALUE["pages"]}
        self.assertNotIn("contact_email", {f for f, _, _ in website_page_facts(other, "AS")})

    def test_nothing_invented_without_pages(self):
        self.assertEqual(website_page_facts({"registered_domain": "x.no", "pages": []}, "AS"), [])


class PageFactsEndToEnd(unittest.TestCase):
    def test_page_facts_flow_into_claims_summary_and_validation(self):
        from test_signalpost_run import run

        def site_with_pages(url):
            value = {"requested_url": url, "final_url": "https://equinor.com/", "registered_domain": "equinor.com", "title": "Equinor ASA energy company", "description": "", "main_text_excerpt": "Equinor ASA is an energy company. " * 10, "social_links": [], "structured_organisations": [], "pages": [{"url": "https://equinor.com/careers", "title": "Careers", "main_text_excerpt": ""}, {"url": "https://equinor.com/contact", "title": "Contact", "main_text_excerpt": "press@equinor.com"}]}
            return evidence("website", "available", "registry_linked_company_website", "https://equinor.com/", value=value, content_sha256="f" * 64), {"requests": 2, "bytes": 1, "latencies_ms": [1]}

        from norway_company_agent.domain_discovery import reverify_registry_website

        own = lambda url: {"ok": True, "url": url, "final_url": url, "html": "<footer>Org.nr 923 609 016</footer>", "requests": 2, "bytes": 30, "latency_ms": 4}
        envelopes, _, report, _ = run(["923609016"], site=site_with_pages, reverify=lambda p, r: reverify_registry_website(p, r, fetch_page=own))
        claims = {c["field"]: c for c in envelopes[0]["claims"]}
        self.assertEqual(claims["careers_page"]["value"], "https://equinor.com/careers")
        self.assertEqual(claims["contact_email"]["value"], "press@equinor.com")
        self.assertTrue(claims["careers_page"]["evidence_ids"])
        text = " ".join(x["text"] for x in envelopes[0]["synthesis"]["sentences"])
        self.assertIn("a careers page", text)
        self.assertTrue(report["validation"]["passed"], report["validation"])


def make_valid(prefix8: str) -> str:
    total = sum(int(d) * w for d, w in zip(prefix8, (3, 2, 7, 6, 5, 4, 3, 2)))
    check = 11 - (total % 11)
    check = 0 if check == 11 else check
    return prefix8 + str(check)


class OwnershipTests(unittest.TestCase):
    def test_check_digit_validation(self):
        from norway_company_agent.domain_discovery import valid_org_number

        self.assertTrue(valid_org_number("923609016"))
        self.assertTrue(valid_org_number("923 609 016"))
        self.assertFalse(valid_org_number("923609017"))
        self.assertFalse(valid_org_number("12345"))

    def group_page(self, others):
        listed = " ".join(f"Org.nr {make_valid(str(10000000 + i * 37))}" for i in range(others))
        return lambda url: page(f"<footer>Org.nr 914 778 271 {listed}</footer>", url)

    def test_site_listing_many_organisations_is_not_taken_as_the_companys_own(self):
        record, _ = discover_website(PROFILE, resolver=lambda h: True, fetch_page=self.group_page(3), site_fetcher=site)
        self.assertEqual(record["status"], "not_found")
        record, _ = discover_website(PROFILE, resolver=lambda h: True, fetch_page=self.group_page(2), site_fetcher=site)
        self.assertEqual(record["status"], "available")
        self.assertEqual(record["value"]["identity_assessment"]["ownership"], "proven")
        self.assertEqual(record["value"]["identity_assessment"]["other_org_numbers_on_page"], 2)

    def test_phone_numbers_and_postcodes_are_not_counted_as_other_companies(self):
        html = "<footer>Org.nr 914 778 271. Tlf 22 33 44 55, mobil 900 12 345, 0155 Oslo, 123 456 789 kr</footer>"
        from norway_company_agent.domain_discovery import other_org_numbers

        self.assertEqual(other_org_numbers(html, "914778271"), 0)

    def test_unproven_website_withholds_social_news_jobs_and_contact(self):
        from test_signalpost_run import run

        def group_like(url):
            value = {"requested_url": url, "final_url": "https://equinor.com/", "registered_domain": "equinor.com", "title": "Equinor ASA energy company", "description": "", "main_text_excerpt": "Equinor ASA is an energy company. " * 10, "social_links": [{"platform": "facebook", "url": "https://facebook.com/equinor"}], "discovered_social_links": [], "structured_organisations": [], "pages": [{"url": "https://equinor.com/careers", "title": "Careers", "main_text_excerpt": ""}]}
            return evidence("website", "available", "registry_linked_company_website", "https://equinor.com/", value=value, content_sha256="f" * 64), {"requests": 1, "bytes": 1, "latencies_ms": [1]}

        envelopes, _, report, _ = run(["923609016"], site=group_like)
        claims = {c["field"]: c for c in envelopes[0]["claims"]}
        for field in ("social_links", "careers_page", "news_page", "contact_page", "contact_email"):
            self.assertEqual(claims[field]["availability"], "ambiguous", field)
            self.assertIsNone(claims[field]["value"])
        self.assertEqual(claims["official_website"]["availability"], "available")
        self.assertLessEqual(claims["official_website"]["confidence"], 0.6)
        self.assertTrue(any(e["field"] == "website_facts" for e in envelopes[0]["errors"]))
        self.assertTrue(report["validation"]["passed"], report["validation"])

    def test_reverify_does_not_upgrade_a_group_page(self):
        from norway_company_agent.domain_discovery import reverify_registry_website

        record = site("https://equinor.com/")[0]
        record["value"]["identity_assessment"] = {"publishable": False}
        listed = " ".join(f"Org.nr {make_valid(str(20000000 + i * 41))}" for i in range(4))
        fetch = lambda url: page(f"<p>Org.nr 914 778 271 {listed}</p>", url)
        upgraded, _ = reverify_registry_website(PROFILE, record, fetch_page=fetch)
        self.assertNotEqual(upgraded["value"]["identity_assessment"].get("ownership"), "proven")


class StrictSocialTests(unittest.TestCase):
    def assess(self, url, name="NORSK KAFFE AS"):
        from norway_company_agent.domain_discovery import assess_social_strict

        return assess_social_strict({"name": name}, {"platform": "x", "url": url})["publishable"]

    def test_exact_handles_are_accepted(self):
        for url in ("https://facebook.com/norskkaffe", "https://www.instagram.com/norsk_kaffe/", "https://linkedin.com/company/norsk-kaffe-as", "https://x.com/NorskKaffeNorge", "https://facebook.com/pages/Norsk-Kaffe-AS/100064123456789", "https://facebook.com/norskkaffe-100064123456"):
            self.assertTrue(self.assess(url), url)

    def test_parent_group_agency_and_substring_handles_are_rejected(self):
        for url in ("https://facebook.com/norskkaffegruppen", "https://linkedin.com/company/norsk-kaffe-group", "https://instagram.com/kaffe", "https://facebook.com/webbyraa/norskkaffe", "https://twitter.com/themeforest", "https://facebook.com/sharer/sharer.php"):
            self.assertFalse(self.assess(url), url)

    def test_short_or_generic_names_are_never_matched(self):
        self.assertFalse(self.assess("https://facebook.com/ark", "ARK AS"))
        self.assertFalse(self.assess("https://facebook.com/arkitekter", "ARK AS"))


if __name__ == "__main__":
    unittest.main()
