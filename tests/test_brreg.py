import unittest
from unittest.mock import patch

from signalpost.brreg import BrregClient
from signalpost.budget import BudgetController
from signalpost.http_client import JsonResponse


class TestBrreg(unittest.TestCase):
    def setUp(self) -> None:
        self.client = BrregClient(
            BudgetController(),
            base_url="https://example.test/api",
            timeout_seconds=1,
        )

    def test_normalize_allows_spaces(self) -> None:
        self.assertEqual(self.client.normalize_orgnr("923 609 016"), "923609016")

    def test_batch_query_uses_documented_chunk_size(self) -> None:
        rows = [{"organisasjonsnummer": "123456789", "navn": "Example"}]
        with patch("signalpost.brreg.JsonHttpClient.get_json") as mocked:
            mocked.return_value = JsonResponse(
                status_code=200,
                url="https://example.test/api/enheter",
                payload={"_embedded": {"enheter": rows}},
            )
            result = self.client.get_entities(["123456789"])
        self.assertEqual(result["123456789"]["navn"], "Example")
        called_url = mocked.call_args.args[0]
        self.assertIn("organisasjonsnummer=123456789", called_url)


if __name__ == "__main__":
    unittest.main()
