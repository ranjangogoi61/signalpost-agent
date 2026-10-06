import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith("/enheter/923609016"):
            payload = {
                "organisasjonsnummer": "923609016",
                "navn": "EQUINOR ASA",
                "organisasjonsform": {"kode": "ASA"},
                "registreringsdatoEnhetsregisteret": "1995-03-12",
                "forretningsadresse": {"kommune": "Stavanger", "postnummer": "4035", "poststed": "STAVANGER"},
            }
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        pass


class TestCliIntegration(unittest.TestCase):
    def test_run_py_end_to_end(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                input_file = tmp_path / "input.txt"
                output_file = tmp_path / "output.jsonl"
                input_file.write_text("923609016\n", encoding="utf-8")
                env = os.environ.copy()
                env["PYTHONPATH"] = str(ROOT / "src")
                env["SIGNALPOST_BRREG_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
                result = subprocess.run(
                    [sys.executable, str(ROOT / "run.py"), "--input", str(input_file), "--output", str(output_file)],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                self.assertIn('"results": 1', result.stdout)
                row = json.loads(output_file.read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(row["status"], "available")
                self.assertEqual(row["profile"]["organisation_number"], "923609016")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
