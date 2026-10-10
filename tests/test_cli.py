from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_signalpost.py"


def load():
    spec = importlib.util.spec_from_file_location("run_signalpost", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


class CliTests(unittest.TestCase):
    def args(self, tmp, rows):
        source = Path(tmp) / "in.txt"
        source.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return ["--organisations", str(source), "--output", f"{tmp}/o/env.jsonl", "--profiles-output", f"{tmp}/o/prof.jsonl", "--report", f"{tmp}/o/rep.json", "--run-id", "t"]

    def test_unknown_and_kit_flags_do_not_break_the_run(self):
        module = load()
        with tempfile.TemporaryDirectory() as tmp:
            argv = self.args(tmp, ["12", "abc", "x"]) + ["--resume", "--checkpoint-every", "5", "--bogus-flag", "1", "--expected-count", "3"]
            with self.assertRaises(SystemExit) as raised:
                module.main(argv)
            self.assertEqual(raised.exception.code, 0)
            envelopes = read(f"{tmp}/o/env.jsonl")
            self.assertEqual([e["organisation_number"] for e in envelopes], ["12", "abc", "x"])
            self.assertTrue(json.loads(Path(f"{tmp}/o/rep.json").read_text())["validation"]["passed"])

    def test_crash_still_writes_one_envelope_per_row(self):
        module = load()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(module, "run_batch", side_effect=RuntimeError("boom")):
                with self.assertRaises(SystemExit) as raised:
                    module.main(self.args(tmp, ["923609016", "914778271"]))
            self.assertEqual(raised.exception.code, 1)
            envelopes = read(f"{tmp}/o/env.jsonl")
            self.assertEqual(len(envelopes), 2)
            for envelope in envelopes:
                self.assertTrue(all(m["availability"] == "failed" for m in envelope["modules"].values()))
                self.assertEqual(envelope["claims"][0]["availability"], "failed")
            report = json.loads(Path(f"{tmp}/o/rep.json").read_text())
            self.assertIn("RuntimeError", report["error"])
            self.assertFalse(report["validation"]["passed"])

    def test_expected_count_mismatch_is_reported_not_hidden(self):
        module = load()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as raised:
                module.main(self.args(tmp, ["1", "2"]) + ["--expected-count", "5"])
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(len(read(f"{tmp}/o/env.jsonl")), 2)


if __name__ == "__main__":
    unittest.main()
