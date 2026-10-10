from __future__ import annotations

import unittest

from norway_company_agent.synthesis import check_synthesis, summarize_envelope
from norway_company_agent.evidence import evidence
from test_signalpost_run import run


def no_site(url):
    return evidence("website", "not_found", "registry_linked_company_website", "https://data.brreg.no/x", note="no website"), {"requests": 0, "bytes": 0, "latencies_ms": []}


class SynthesisTests(unittest.TestCase):
    def envelope(self, org="923609016", **kw):
        envelopes, _, report, _ = run([org], **kw)
        return envelopes[0], report

    def test_every_sentence_cites_existing_evidence_and_numbers_match(self):
        envelope, report = self.envelope()
        self.assertEqual(check_synthesis(envelope), [])
        self.assertTrue(report["validation"]["checks"]["synthesis_cites_existing_evidence"])
        text = " ".join(s["text"] for s in envelope["synthesis"]["sentences"])
        self.assertIn("EQUINOR ASA", text)
        self.assertIn("21272", text)

    def test_unknown_fields_are_listed_with_their_state(self):
        envelope, _ = self.envelope("914778271", site=no_site)
        unknown = {u["field"]: u["availability"] for u in envelope["synthesis"]["unknown"]}
        self.assertEqual(unknown["official_website"], "not_available")
        last = envelope["synthesis"]["sentences"][-1]["text"]
        self.assertTrue(last.startswith("Not published"))
        self.assertEqual(envelope["synthesis"]["sentences"][-1]["evidence_ids"], [])

    def test_unknown_company_has_no_invented_facts(self):
        envelope, _ = self.envelope("000000000")
        texts = [s["text"] for s in envelope["synthesis"]["sentences"]]
        self.assertFalse(any("registered" in t for t in texts if not t.startswith(("Not published", "This is"))))
        self.assertTrue(any(t.startswith("Not published") for t in texts))

    def test_first_run_and_refresh_wording(self):
        first, _ = self.envelope()
        self.assertIn("first run", first["synthesis"]["sentences"][-2]["text"] + first["synthesis"]["sentences"][-1]["text"])
        envelopes, profiles, _, _ = run(["923609016"])
        second, _, _, _ = run(["923609016"], previous={"923609016": profiles[0]})
        joined = " ".join(s["text"] for s in second[0]["synthesis"]["sentences"])
        self.assertIn("no material change", joined)

    def test_real_world_value_shapes_do_not_trigger_false_alarms(self):
        envelope, _ = self.envelope()
        for claim in envelope["claims"]:
            if claim["field"] == "financials_latest":
                claim["value"] = {"period": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"}, "currency": "NOK", "revenue": 1234567.6, "annual_result": -45210.4, "assets": 987654321.0}
            if claim["field"] == "role_holders":
                claim["value"] = [{"name": f"P{i}", "role": "Styremedlem" if i % 3 else "Daglig leder"} for i in range(12)]
            if claim["field"] == "registered_locations":
                claim["value"] = [{"name": f"L{i}"} for i in range(37)]
                claim["availability"] = "available"
                claim["evidence_ids"] = [envelope["evidence"][0]["id"]]
        from norway_company_agent.synthesis import summarize_envelope
        envelope["synthesis"] = summarize_envelope(envelope)
        text = " ".join(s["text"] for s in envelope["synthesis"]["sentences"])
        self.assertIn("1 234 568", text)
        self.assertIn("12 active role holders", text)
        self.assertIn("37 subunit", text)
        self.assertEqual(check_synthesis(envelope), [])

    def test_tampered_synthesis_is_detected(self):
        envelope, _ = self.envelope()
        envelope["synthesis"]["sentences"][0]["text"] += " It employs 99999 people."
        self.assertTrue(check_synthesis(envelope))
        envelope["synthesis"]["sentences"][0]["evidence_ids"].append("ev-999")
        self.assertIn("unknown evidence id ev-999", check_synthesis(envelope))


if __name__ == "__main__":
    unittest.main()
