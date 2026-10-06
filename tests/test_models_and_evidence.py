import unittest

from signalpost.evidence import content_hash
from signalpost.models import CompanyResult


class TestEvidence(unittest.TestCase):
    def test_hash_is_stable(self) -> None:
        first = content_hash({"b": 2, "a": 1})
        second = content_hash({"a": 1, "b": 2})
        self.assertEqual(first, second)
        self.assertEqual(len(first[0]), 64)
        self.assertEqual(first[1], "sha256")

    def test_terminal_state_serializes(self) -> None:
        result = CompanyResult(organisation_number="123456789", status="not_available")
        payload = result.to_dict()
        self.assertEqual(payload["status"], "not_available")
        self.assertEqual(payload["organisation_number"], "123456789")


if __name__ == "__main__":
    unittest.main()
