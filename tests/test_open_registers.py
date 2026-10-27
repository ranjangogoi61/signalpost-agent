from __future__ import annotations

import unittest

from norway_company_agent.open_registers import OpenRegisters, parse_arbeidstilsynet, parse_overpass, parse_smilefjes

XML = """<?xml version="1.0" encoding="utf-8"?><Register><Metadata><Registernavn>Renhold</Registernavn></Metadata>
<Virksomhet><Hovedenhet><Organisasjonsnummer>914778271</Organisasjonsnummer><Navn>NORSK KAFFE AS</Navn><Godkjenningsstatus>Godkjent</Godkjenningsstatus>
<Kontaktinformasjon><Telefon>99999999</Telefon><Webadresse>www.norskkaffe.no</Webadresse></Kontaktinformasjon></Hovedenhet>
<Underenheter><Avdeling><Organisasjonsnummer>987654321</Organisasjonsnummer></Avdeling></Underenheter></Virksomhet>
<Virksomhet><Hovedenhet><Organisasjonsnummer>111111111</Organisasjonsnummer><Godkjenningsstatus>Under behandling</Godkjenningsstatus></Hovedenhet></Virksomhet></Register>""".encode()

CSV = """tilsynsobjektid;orgnummer;navn;adrlinje1;adrlinje2;postnr;poststed;tilsynid;sakref;status;dato;total_karakter;tilsynsbesoektype
A;987654321;Kaffebar Løkka;Gate 1;;0550;OSLO;t1;s;1;03092025;0;0
A;987654321;Kaffebar Løkka;Gate 1;;0550;OSLO;t2;s;1;15012026;2;0
B;222222222;Other;;;5000;BERGEN;t3;s;1;01012026;1;0
""".encode()

OSM = b'{"elements":[{"tags":{"ref:NO:orgnr":"987 654 321","website":"kaffebar.no","phone":"1"}},{"tags":{"ref:NO:orgnr":"333333333"}}]}'

PROFILE = {"organisation_number": "914778271", "name": "NORSK KAFFE AS", "evidence": {"locations": {"status": "available", "value": {"locations": [{"organisation_number": "987654321", "name": "KAFFEBAR LØKKA"}]}}}}


def fake_download(payloads):
    def download(url, data=None):
        for key, raw in payloads.items():
            if key in url:
                if raw is None:
                    return {"ok": False, "error": "HTTP Error 503", "url": url}
                return {"ok": True, "raw": raw, "sha256": "s" * 64, "retrieved_at": "2026-10-27T00:00:00Z", "url": url}
        return {"ok": False, "error": "unknown", "url": url}
    return download


class ParserTests(unittest.TestCase):
    def test_arbeidstilsynet_xml_keeps_status_and_website_never_phone(self):
        register = parse_arbeidstilsynet(XML)
        self.assertEqual(register["914778271"]["status"], "Godkjent")
        self.assertEqual(register["914778271"]["subunits"], ["987654321"])
        self.assertEqual(register["914778271"]["website"], "www.norskkaffe.no")
        self.assertNotIn("99999999", str(register))
        self.assertEqual(register["111111111"]["status"], "Under behandling")

    def test_smilefjes_and_osm(self):
        rows = parse_smilefjes(CSV)
        self.assertEqual(rows["987654321"][1]["date"], "2026-01-15")
        self.assertEqual(parse_overpass(OSM), {"987654321": ["https://kaffebar.no"]})


class JoinTests(unittest.TestCase):
    def test_exact_joins_through_registered_subunits(self):
        registers = OpenRegisters(downloader=fake_download({"renhold": XML, "bht": None, "smilefjes": CSV, "overpass": OSM}))
        status = registers.load()
        self.assertTrue(status["renhold"]["ok"])
        self.assertFalse(status["bht"]["ok"])
        self.assertEqual(registers.requests, 4)
        self.assertEqual(registers.approval("renhold", PROFILE), {"status": "Godkjent", "registered_subunits": 1})
        food = registers.inspections(PROFILE)
        self.assertEqual((food["inspection_count"], food["outlet_count"], food["latest_date"], food["latest_grade"]), (2, 1, "2026-01-15", "2"))
        self.assertIn("straight face", food["latest_grade_meaning"])
        self.assertEqual(registers.osm_websites(PROFILE), ["https://kaffebar.no"])
        self.assertIsNone(registers.inspections({"organisation_number": "999999999", "evidence": {}}))

    def test_contract_claims_states_and_synthesis(self):
        from test_signalpost_run import MODULES, FakeApi, rows_for, site_ok

        from norway_company_agent.signalpost_run import Budget, run_batch

        class Api(FakeApi):
            def __call__(self, url):
                if "underenheter" in url:
                    from norway_company_agent.http import FetchResult
                    return FetchResult(url, 200, 5, 10, {"_embedded": {"underenheter": [{"organisasjonsnummer": "987654321", "navn": "KAFFEBAR LØKKA"}]}}, content_sha256="l" * 64, retrieved_at="2026-10-27T00:00:00Z")
                return super().__call__(url)

        registers = OpenRegisters(downloader=fake_download({"renhold": XML, "bht": None, "smilefjes": CSV, "overpass": OSM}))
        modules = MODULES + ["cleaning_register", "ohs_register", "food_inspections"]
        envelopes, profiles, report = run_batch(rows_for("914778271", "923609016"), run_id="t", modules=modules, budget=Budget(10_000, 10_000), workers=1, fetcher=Api(), site_fetcher=site_ok, discovery_fetcher=None, reverifier=None, open_registers=registers)
        self.assertTrue(report["validation"]["passed"], report["validation"])
        claims = {c["field"]: c for c in envelopes[0]["claims"]}
        self.assertEqual(claims["cleaning_approval"]["availability"], "available")
        self.assertEqual(claims["occupational_health_approval"]["availability"], "failed")
        self.assertEqual(claims["food_safety_inspections"]["value"]["inspection_count"], 2)
        self.assertEqual({c["field"]: c for c in envelopes[1]["claims"]}["cleaning_approval"]["availability"], "not_available")
        text = " ".join(s["text"] for s in envelopes[0]["synthesis"]["sentences"])
        self.assertIn("status: Godkjent", text)
        self.assertIn("latest, on 2026-01-15", text)
        self.assertEqual(report["operations"]["requests_by_phase"]["open_registers"], 4)
        self.assertEqual(profiles[0].get("register_websites"), ["www.norskkaffe.no", "https://kaffebar.no"])


class NoDownloadWithoutCompaniesTests(unittest.TestCase):
    def test_batch_without_registered_companies_downloads_nothing(self):
        from test_signalpost_run import MODULES, FakeApi, rows_for, site_ok

        from norway_company_agent.signalpost_run import Budget, run_batch

        calls = []
        registers = OpenRegisters(downloader=lambda url, data=None: calls.append(url) or {"ok": False, "error": "x"})
        envelopes, _, report = run_batch(rows_for("000000000", "x"), run_id="t", modules=MODULES + ["cleaning_register"], budget=Budget(1000, 1000), workers=1, fetcher=FakeApi(), site_fetcher=site_ok, discovery_fetcher=None, reverifier=None, open_registers=registers)
        self.assertEqual(calls, [])
        self.assertTrue(report["validation"]["passed"], report["validation"])
