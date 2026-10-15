from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from norway_company_agent.signalpost_run import Budget, anchor_profiles, run_batch
from test_signalpost_run import MODULES, FakeApi, rows_for, site_ok

HEADER = "organisasjonsnummer;navn;organisasjonsform.kode;antallAnsatte;hjemmeside;forretningsadresse.adresse;forretningsadresse.postnummer;forretningsadresse.poststed;forretningsadresse.kommune;forretningsadresse.kommunenummer;naeringskode1.kode;naeringskode1.beskrivelse;konkurs;underAvvikling;registrertIMvaregisteret;stiftelsesdato;aktivitet;epostadresse"
ROWS = [
    "923609016;EQUINOR ASA;ASA;21272;www.equinor.com;Forusbeen 50;4035;STAVANGER;STAVANGER;1103;06.100;Utvinning av råolje;false;false;true;1972-09-18;Olje og gass;post@equinor.com",
    "914778271;NORSK KAFFE AS;AS;3;;Storgata 1;0155;OSLO;OSLO;0301;10.830;Kaffe;false;false;false;2001-02-03;Kaffe;kari@gmail.com",
]


def write(tmp, name, text, gz):
    path = Path(tmp) / name
    data = (HEADER + "\n" + "\n".join(ROWS) + "\n") if text is None else text
    if gz:
        path.write_bytes(gzip.compress(data.encode("utf-8")))
    else:
        path.write_text(data, encoding="utf-8")
    return str(path)


class BulkTests(unittest.TestCase):
    def test_gzip_and_plain_csv_both_work_and_are_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            for gz in (True, False):
                path = write(tmp, f"b{gz}.csv", None, gz)
                profiles, meta = anchor_profiles(["923609016", "914778271"], bulk_path=path, modules=MODULES, fetcher=FakeApi())
                self.assertEqual(meta["from_bulk"], 2, gz)
                self.assertEqual(len(meta["registry_snapshot_sha256"]), 64)
                self.assertEqual(profiles["923609016"]["anchor"], "bulk")
                self.assertEqual(profiles["923609016"]["employees"], 21272)

    def test_unreadable_snapshot_falls_back_to_the_live_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "bad.csv", "\x00\x01 not a csv at all", False)
            profiles, meta = anchor_profiles(["923609016"], bulk_path=path, modules=MODULES, fetcher=FakeApi())
            self.assertEqual(profiles["923609016"]["anchor"], "live_api")
            self.assertEqual(meta["from_live_batch"] + meta["from_direct"], 1)

    def test_number_missing_from_snapshot_is_resolved_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "b.csv", HEADER + "\n" + ROWS[0] + "\n", True)
            profiles, meta = anchor_profiles(["923609016", "914778271"], bulk_path=path, modules=MODULES, fetcher=FakeApi())
            self.assertEqual(profiles["923609016"]["anchor"], "bulk")
            self.assertEqual(profiles["914778271"]["anchor"], "live_api")
            self.assertEqual((meta["from_bulk"], meta["from_live_batch"]), (1, 1))

    def test_real_csv_column_spellings_are_matched(self):
        from norway_company_agent.signalpost_run import registry_extra_facts

        row = {"registreringsdatoenhetsregisteret": "2003-04-22", "registrertIMvaRegisteret": "true", "underTvangsavviklingEllerTvangsopplosning": "false", "konkurs": "false", "underAvvikling": "false", "stiftelsesdato": "2003-02-05"}
        facts = {f: v for f, v, _ in registry_extra_facts(row, "AS")}
        self.assertEqual(facts["registered_on"], "2003-04-22")
        self.assertIs(facts["vat_registered"], True)
        self.assertEqual(facts["legal_status"], "active")
        flagged = {f: v for f, v, _ in registry_extra_facts({**row, "underTvangsavviklingEllerTvangsopplosning": "true"}, "AS")}
        self.assertEqual(flagged["legal_status"], "under_forced_liquidation")

    def test_flat_csv_columns_produce_the_same_facts_as_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "b.csv", None, True)
            envelopes, _, report = run_batch(rows_for("923609016", "914778271"), run_id="t", modules=MODULES, budget=Budget(10_000, 10_000), bulk_path=path, workers=1, fetcher=FakeApi(), site_fetcher=site_ok, discovery_fetcher=None, reverifier=None)
        claims = {c["field"]: c["value"] for c in envelopes[0]["claims"]}
        self.assertEqual(claims["business_address"], "Forusbeen 50, 4035 STAVANGER")
        self.assertEqual(claims["founded"], "1972-09-18")
        self.assertIs(claims["vat_registered"], True)
        self.assertEqual(claims["legal_status"], "active")
        self.assertEqual(claims["registry_contact_email"], "post@equinor.com")
        other = {c["field"]: c["value"] for c in envelopes[1]["claims"]}
        self.assertNotIn("registry_contact_email", other)  # free-mail address is never published
        self.assertTrue(report["validation"]["passed"], report["validation"])
        self.assertEqual(report["registry_anchor"]["from_bulk"], 2)


if __name__ == "__main__":
    unittest.main()
