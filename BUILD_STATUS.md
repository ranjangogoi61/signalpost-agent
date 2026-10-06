# Build status — 2026-10-06

## v0.1 vertical slice: COMPLETE

Implemented:

- Arbitrary-N organisation-number input.
- BRREG exact-entity lookup.
- BRREG batch lookup in chunks of up to 2,000 organisation numbers.
- Exact legal-entity match gate.
- Evidence model with source URL, retrieval timestamp, effective date, content hash, and extraction method.
- Six Signalpost terminal states.
- One-result-per-input invariant.
- Configurable runtime/request/concurrency controls.
- Standard-library-only runtime.
- Clean-machine-friendly `python run.py ...` entrypoint.
- Unit + local end-to-end integration tests.
- GitHub Actions CI/smoke workflow.

## Not implemented yet

- Final Builderr evaluator output schema mapping.
- Regnskapsregisteret connector.
- Roles connector.
- Subunit/location connector.
- Company-owned website discovery and identity verification.
- Jobs/public-activity enrichment.
- Refresh/change ledger and persistence.
- Final 100-company submission smoke-test report.
- JBOX bonus integration.

Those remain separate layers and do not require rewriting the v0.1 batch/evidence foundation.
