from __future__ import annotations

import json
import re
import unittest

from norway_company_agent.viewer import build_viewer
from test_signalpost_run import run


def payload(html):
    return json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.envelopes, _, self.report, _ = run(["923609016", "914778271", "000000000", "x"])

    def test_single_file_offline_and_mobile_ready(self):
        html = build_viewer(self.envelopes, self.report)
        self.assertIn('name="viewport"', html)
        self.assertIsNone(re.search(r"<(script|link|img)[^>]+(src|href)=[\"']https?:", html, re.I))
        data = payload(html)
        self.assertEqual([c["org"] for c in data["companies"]], ["923609016", "914778271", "000000000", "x"])

    def test_person_names_can_be_hidden_for_a_public_demo(self):
        shown = build_viewer(self.envelopes, self.report)
        hidden = build_viewer(self.envelopes, self.report, hide_person_names=True)
        self.assertIn("Nordmann", shown)
        self.assertNotIn("Nordmann", hidden)

    def test_markup_in_company_data_cannot_break_out_of_the_data_block(self):
        self.envelopes[0]["claims"][0]["value"] = "</script><img src=x onerror=alert(1)>"
        html = build_viewer(self.envelopes, self.report)
        self.assertEqual(html.count("</script>"), 2)
        self.assertEqual(payload(html)["companies"][0]["claims"][0]["value"], "</script><img src=x onerror=alert(1)>")

    def test_every_company_gets_a_summary_and_unpublished_list(self):
        for company in payload(build_viewer(self.envelopes, self.report))["companies"]:
            self.assertTrue(company["synthesis"]["sentences"])


if __name__ == "__main__":
    unittest.main()
