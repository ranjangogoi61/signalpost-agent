from __future__ import annotations

from urllib.parse import quote, urlencode

from .budget import BudgetController
from .http_client import HttpClientError, JsonHttpClient


class BrregNotAvailable(Exception):
    pass


class BrregBlocked(Exception):
    pass


class BrregClient:
    """Minimal Enhetsregisteret client used as the Signalpost identity anchor."""

    def __init__(self, budget: BudgetController, *, base_url: str, timeout_seconds: float) -> None:
        self._http = JsonHttpClient(budget, timeout_seconds=timeout_seconds)
        self._base_url = base_url.rstrip("/")

    @staticmethod
    def normalize_orgnr(value: str) -> str:
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) != 9:
            raise ValueError("organisation number must contain exactly 9 digits")
        return digits


    def get_entities(self, orgnrs: list[str]) -> dict[str, dict]:
        """Batch-fetch entities using BRREG's organisation-number query.

        BRREG documents a maximum of 2,000 organisation numbers per query.
        The runner can therefore process arbitrary N by chunking inputs.
        """
        normalized = [self.normalize_orgnr(value) for value in orgnrs]
        entities: dict[str, dict] = {}
        for start in range(0, len(normalized), 2000):
            chunk = normalized[start:start + 2000]
            query = urlencode({"organisasjonsnummer": ",".join(chunk)})
            url = f"{self._base_url}/enheter?{query}"
            try:
                response = self._http.get_json(url)
            except HttpClientError as exc:
                if exc.status_code in {404, 410}:
                    continue
                if exc.status_code in {401, 403}:
                    raise BrregBlocked(str(exc)) from exc
                raise
            payload = response.payload
            if not isinstance(payload, dict):
                raise ValueError("BRREG batch search returned a non-object payload")
            embedded = payload.get("_embedded", {})
            rows = embedded.get("enheter", []) if isinstance(embedded, dict) else []
            if not isinstance(rows, list):
                raise ValueError("BRREG batch search returned an invalid entity list")
            for row in rows:
                if isinstance(row, dict):
                    key = row.get("organisasjonsnummer")
                    if key is not None:
                        entities[str(key).zfill(9)] = row
        return entities

    def get_entity(self, orgnr: str) -> tuple[dict, str]:
        normalized = self.normalize_orgnr(orgnr)
        url = f"{self._base_url}/enheter/{quote(normalized)}"
        try:
            response = self._http.get_json(url)
        except HttpClientError as exc:
            if exc.status_code in {404, 410}:
                raise BrregNotAvailable(str(exc)) from exc
            if exc.status_code in {401, 403}:
                raise BrregBlocked(str(exc)) from exc
            raise
        if not isinstance(response.payload, dict):
            raise ValueError("BRREG returned a non-object entity payload")
        return response.payload, response.url
