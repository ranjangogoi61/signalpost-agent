import unittest
from unittest.mock import patch

from signalpost.config import Settings
from signalpost.http_client import JsonResponse
from signalpost.runner import SignalpostRunner


class TestRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            brreg_base_url="https://example.test/api",
            http_timeout_seconds=1,
            max_concurrency=2,
            max_requests=None,
            max_runtime_seconds=None,
        )

    def test_exact_identity_produces_available(self) -> None:
        payload = {
            "organisasjonsnummer": "123456789",
            "navn": "Example AS",
            "organisasjonsform": {"kode": "AS"},
            "registreringsdatoEnhetsregisteret": "2020-01-02",
            "forretningsadresse": {"kommune": "Testby", "postnummer": "1234", "poststed": "Testby"},
        }
        with patch("signalpost.brreg.JsonHttpClient.get_json") as mocked:
            mocked.return_value = JsonResponse(
                status_code=200,
                url="https://example.test/entity/123456789",
                payload=payload,
            )
            result = SignalpostRunner(self.settings).process_one("123456789")
        self.assertEqual(result.status, "available")
        assert result.profile is not None
        keys = {fact.key for fact in result.profile.facts}
        self.assertIn("legal_name", keys)
        self.assertIn("organisation_number", keys)

    def test_batch_preserves_one_output_per_input(self) -> None:
        payload = {"organisasjonsnummer": "123456789", "navn": "Example AS"}
        with patch("signalpost.brreg.JsonHttpClient.get_json") as mocked:
            mocked.return_value = JsonResponse(
                status_code=200,
                url="https://example.test/entity/123456789",
                payload=payload,
            )
            results = SignalpostRunner(self.settings).run(["123456789", "bad"])
        self.assertEqual(len(results), 2)
        self.assertEqual([r.status for r in results], ["available", "failed"])

    def test_identity_mismatch_is_ambiguous(self) -> None:
        payload = {"organisasjonsnummer": "987654321", "navn": "Wrong Company"}
        with patch("signalpost.brreg.JsonHttpClient.get_json") as mocked:
            mocked.return_value = JsonResponse(
                status_code=200,
                url="https://example.test/entity/123456789",
                payload=payload,
            )
            result = SignalpostRunner(self.settings).process_one("123456789")
        self.assertEqual(result.status, "ambiguous")

    def test_run_uses_one_batch_request_for_many_companies(self) -> None:
        rows = [
            {"organisasjonsnummer": "111111111", "navn": "A AS"},
            {"organisasjonsnummer": "222222222", "navn": "B AS"},
        ]
        with patch("signalpost.brreg.JsonHttpClient.get_json") as mocked:
            mocked.return_value = JsonResponse(
                status_code=200,
                url="https://example.test/api/enheter",
                payload={"_embedded": {"enheter": rows}},
            )
            results = SignalpostRunner(self.settings).run(["111111111", "222222222"])
        self.assertEqual([r.status for r in results], ["available", "available"])
        self.assertEqual(mocked.call_count, 1)

    def test_batch_failure_falls_back_to_direct_lookup(self) -> None:
        from signalpost.http_client import HttpClientError

        entity = {"organisasjonsnummer": "111111111", "navn": "A AS"}

        def fake(url: str):
            if "?organisasjonsnummer=" in url:
                raise HttpClientError("boom", status_code=500)
            return JsonResponse(status_code=200, url=url, payload=entity)

        with patch("signalpost.brreg.JsonHttpClient.get_json", side_effect=fake):
            results = SignalpostRunner(self.settings).run(["111111111"])
        self.assertEqual(results[0].status, "available")

    def test_number_missing_from_batch_is_resolved_directly_as_not_available(self) -> None:
        from signalpost.http_client import HttpClientError

        def fake(url: str):
            if "?organisasjonsnummer=" in url:
                return JsonResponse(status_code=200, url=url, payload={"_embedded": {"enheter": []}})
            raise HttpClientError("HTTP 404", status_code=404)

        with patch("signalpost.brreg.JsonHttpClient.get_json", side_effect=fake):
            results = SignalpostRunner(self.settings).run(["111111111"])
        self.assertEqual(results[0].status, "not_available")


if __name__ == "__main__":
    unittest.main()
