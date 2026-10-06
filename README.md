# Signalpost Agent — v0.1

First vertical slice for the Builderr Signalpost challenge.

## What is implemented

- Arbitrary number of Norwegian organisation numbers.
- BRREG Enhetsregisteret as the identity anchor.
- Exact organisation-number matching before publication.
- BRREG direct entity lookup.
- BRREG batch lookup in chunks of up to 2,000 organisation numbers.
- Evidence attached to every published fact: source URL, retrieval timestamp, effective date when available, content hash, extraction method.
- Exactly one terminal result per input.
- Signalpost terminal states: `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`.
- Configurable request/runtime/concurrency limits.
- No fixed 100/1,000/1,100/1,200-company assumption.
- Standard-library-only runtime dependency.

## Run directly

No package installation is required for the current slice:

```bash
python run.py --input input.sample.txt --output output/results.jsonl
```

Optional environment controls:

```text
SIGNALPOST_MAX_CONCURRENCY
SIGNALPOST_HTTP_TIMEOUT
SIGNALPOST_MAX_REQUESTS
SIGNALPOST_MAX_RUNTIME_SECONDS
SIGNALPOST_BRREG_BASE_URL
```

Exact Builderr runtime/request/cost values are intentionally not hard-coded until the organizer confirms them.

## Tests

```bash
python -m unittest discover -s tests -v
```

A GitHub Actions workflow also runs the unit suite and a live BRREG smoke test using a public company organisation number.

## Architecture boundary

This is **not yet the final Builderr submission schema** and does not yet implement all permitted enrichment sources. The goal of v0.1 is to establish the evaluator-safe batch/result/evidence foundation.

Future source connectors should plug into the same evidence and result model.

## Official references

- Builderr Signalpost: https://builderr.ai/challenges/signalpost
- BRREG Enhetsregisteret API: https://data.brreg.no/enhetsregisteret/api/dokumentasjon/en/index.html
