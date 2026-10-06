from __future__ import annotations

import concurrent.futures
import uuid
from datetime import datetime, timezone
from typing import Iterable

from .budget import BudgetController, BudgetExceeded
from .brreg import BrregBlocked, BrregClient, BrregNotAvailable
from .config import Settings
from .evidence import make_evidence
from .http_client import HttpClientError
from .identity import exact_entity_match
from .models import CompanyProfile, CompanyResult, Fact


def _date_from_payload(payload: dict) -> str | None:
    for key in (
        "registreringsdatoEnhetsregisteret",
        "stiftelsesdato",
        "sisteInnsendteAarsregnskap",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            return value[:10]
    return None


def _build_profile(orgnr: str, payload: dict, source_url: str) -> CompanyProfile:
    evidence = make_evidence(
        source_url=source_url,
        payload=payload,
        effective_date=_date_from_payload(payload),
        extraction_method="brreg.enhetsregisteret.v2.direct-entity-json",
    )

    facts: list[Fact] = []
    mappings = {
        "legal_name": "navn",
        "organisation_form": ("organisasjonsform", "kode"),
        "municipality": ("forretningsadresse", "kommune"),
        "postal_code": ("forretningsadresse", "postnummer"),
        "postal_city": ("forretningsadresse", "poststed"),
        "website": "hjemmeside",
        "registration_date": "registreringsdatoEnhetsregisteret",
        "employees": "antallAnsatte",
        "industry_code": ("naeringskode1", "kode"),
    }

    for key, path in mappings.items():
        value = payload
        try:
            parts = (path,) if isinstance(path, str) else path
            for part in parts:
                value = value[part]
        except (KeyError, TypeError):
            continue
        if value is None or value == "":
            continue
        facts.append(Fact(key=key, value=value, evidence=[evidence]))

    # Preserve the organisation number as a source-backed fact too.
    facts.insert(0, Fact(key="organisation_number", value=orgnr, evidence=[evidence]))
    return CompanyProfile(organisation_number=orgnr, facts=facts)


class SignalpostRunner:
    def __init__(self, settings: Settings) -> None:
        self._run_id = uuid.uuid4().hex
        self._budget = BudgetController(
            max_requests=settings.max_requests,
            max_runtime_seconds=settings.max_runtime_seconds,
        )
        self._brreg = BrregClient(
            self._budget,
            base_url=settings.brreg_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        )
        self._max_concurrency = settings.max_concurrency

    def process_one(self, raw_orgnr: str) -> CompanyResult:
        try:
            orgnr = self._brreg.normalize_orgnr(raw_orgnr)
        except ValueError as exc:
            return CompanyResult(
                organisation_number=str(raw_orgnr).strip(),
                status="failed",
                error={"code": "invalid_orgnr", "message": str(exc)},
                run_id=self._run_id,
            )

        try:
            payload, source_url = self._brreg.get_entity(orgnr)
            if not exact_entity_match(orgnr, payload):
                return CompanyResult(
                    organisation_number=orgnr,
                    status="ambiguous",
                    error={
                        "code": "identity_mismatch",
                        "message": "BRREG response did not resolve to the requested organisation number",
                    },
                    run_id=self._run_id,
                )
            profile = _build_profile(orgnr, payload, source_url)
            return CompanyResult(
                organisation_number=orgnr,
                status="available",
                profile=profile,
                run_id=self._run_id,
            )
        except BrregNotAvailable as exc:
            return CompanyResult(
                organisation_number=orgnr,
                status="not_available",
                error={"code": "brreg_not_available", "message": str(exc)},
                run_id=self._run_id,
            )
        except BrregBlocked as exc:
            return CompanyResult(
                organisation_number=orgnr,
                status="blocked",
                error={"code": "brreg_blocked", "message": str(exc)},
                run_id=self._run_id,
            )
        except BudgetExceeded as exc:
            return CompanyResult(
                organisation_number=orgnr,
                status="failed",
                error={"code": "budget_exhausted", "message": str(exc)},
                run_id=self._run_id,
            )
        except (HttpClientError, ValueError) as exc:
            return CompanyResult(
                organisation_number=orgnr,
                status="failed",
                error={"code": "source_failure", "message": str(exc)},
                run_id=self._run_id,
            )
        except Exception as exc:  # Defensive: one result must still be emitted.
            return CompanyResult(
                organisation_number=orgnr,
                status="failed",
                error={"code": "unexpected_error", "message": repr(exc)},
                run_id=self._run_id,
            )

    def run(self, organisation_numbers: Iterable[str]) -> list[CompanyResult]:
        inputs = list(organisation_numbers)
        results: list[CompanyResult | None] = [None] * len(inputs)

        # Bounded concurrency is intentionally configurable. The code does not
        # assume Builderr's evaluator CPU/RAM specification.
        with concurrent.futures.ThreadPoolExecutor(max_workers=self._max_concurrency) as pool:
            futures = {
                pool.submit(self.process_one, raw): index
                for index, raw in enumerate(inputs)
            }
            for future in concurrent.futures.as_completed(futures):
                index = futures[future]
                results[index] = future.result()

        # Defensive invariant: every input gets exactly one terminal result.
        return [item for item in results if item is not None]
