# Signalpost submission: signalpost-agent

* **Participant:** Ranjan Gogoi (individual), gogoi78ranjan@gmail.com
* **Repository (public):** https://github.com/ranjangogoi61/signalpost-agent
* **Exact commit:** the head of `main` on the day of submission (`git rev-parse origin/main`). The commit named in the submission email is the one that passed CI; it is not repeated here so this file never goes stale.
* **Python:** 3.12 (dependencies pinned in `uv.lock`)

## One command

```bash
pip install uv && uv sync --frozen
uv run python scripts/run_signalpost.py \
  --organisations <batch.jsonl|.json|.txt> \
  --output out/envelopes.jsonl \
  --profiles-output out/profiles.jsonl \
  --report out/run-report.json \
  --run-id <id> \
  --expected-count <N>
```

Optional: `--bulk <brreg-enheter.csv>` (frozen BRREG snapshot; the live registry is used without it), `--previous <earlier profiles.jsonl>` (refresh / material changes), `--no-discovery`, `--max-requests-per-100` (default 1900), `--max-seconds-per-100` (default 2400), `--workers` (default 8).

The agent reads whatever batch it is given; it assumes no company count.

## Models, APIs, licences, cost

| Item | Declaration |
|---|---|
| Language models | None |
| Paid or keyed APIs | None |
| Registry data | data.brreg.no (Enhetsregisteret, roles, subunits; Regnskapsregisteret accounts), NLOD 2.0 |
| Company websites | Registry-linked or discovered by exact organisation number; robots.txt respected |
| LinkedIn / Meta / Indeed / search engines / directories | Not accessed |
| Expected third-party cost | $0 per 100-company run |
| Measured on CI (100 companies, live) | about 700 outbound requests (retries and redirects counted) and about 140 s, inside the 2,000 request / 45 minute budget |

## What it publishes

Facts only from an official register or from a company page that prints the company's exact organisation number. Every published claim carries a source URL, retrieval time and content SHA-256. Anything not found, blocked, not applicable, ambiguous or failed is returned as that state with no value. One envelope per input row, in input order, even for invalid, duplicate, unknown or deleted numbers.

Role holders are published by name and role only; dates of birth are discarded.

## Smoke result and report

The 100-company live run and its refresh re-run are produced by the `ci` workflow on every push to `dev`; counts-only summaries are on the `smoke-results` branch (`summary.json`, `summary2.json`, `run-report.json`). They contain no company or person data.

## Known limits (honest list)

* Websites are the weakest field: registry coverage of websites is low, and discovery by exact organisation number finds only a few percent of the rest.
* No news, review, jobs or social collection from third-party platforms.
* The evaluator's exact invocation was not published; `scripts/run_signalpost.py` accepts the reference kit's flags as a superset.

## Tests

```bash
uv run --with pytest pytest -q
```
