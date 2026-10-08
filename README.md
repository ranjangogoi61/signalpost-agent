# signalpost-agent

Evidence-first agent for Builderr's Signalpost challenge. Give it Norwegian organisation numbers; it returns exactly one terminal envelope per input, with a source, retrieval time and content hash for every published fact and one of six availability states (`available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`) for everything else.

Built on Builderr's published reference agent (`src/norway_company_agent`, kept as the base) with a hardened runner added in `src/norway_company_agent/signalpost_run.py`. The reference kit's connector experiments are kept unchanged for reference only; the official command below imports none of them and sends no request to those services.

## Run command

```bash
uv sync --frozen && uv run python scripts/run_signalpost.py \
  --organisations <batch.jsonl|.json|.txt> \
  --output out/envelopes.jsonl \
  --profiles-output out/profiles.jsonl \
  --report out/run-report.json \
  --run-id <id> \
  --expected-count <N>
```

* `--bulk <brreg-enheter.csv>` is optional. Without it the identity anchor is the live BRREG register (chunked organisation-number query, direct lookup only for numbers the query does not return).
* Refresh: run again with the same `--profiles-output`, or pass `--previous <earlier profiles.jsonl>`; material changes are written to each envelope's `changes`.
* Budget (retries and redirects count): `--max-requests-per-100` (default 1900) and `--max-seconds-per-100` (default 2400) per 100 companies. When the budget is nearly used the optional website phase is skipped and marked `failed` (`budget_exhausted`); the official registry phase always runs first.
* Company count is never assumed: the agent processes whatever batch it is given.

## What it publishes

Official sources only for facts: BRREG entity register, roles (dates of birth discarded), subunits, group links and Regnskapsregisteret accounts. A company website is published only when it is verified as the exact legal entity; otherwise the claim is `ambiguous` and carries no value. No LinkedIn, Meta or Indeed collection; no search-engine scraping; no paid APIs; no LLM calls. Third-party cost per run: $0.

## Rules enforced by tests

* exactly one envelope per input row, in input order, for invalid, duplicate, unknown or deleted numbers;
* only the six availability states; no value on an unavailable claim; every available claim cites evidence with a content hash;
* unverified website is `ambiguous`; request/time guard cannot be exceeded;
* refresh reports changes and no false changes.

## Tests

```bash
uv run --with pytest pytest -q
```

## Declarations

* Models/APIs: none (no LLM). Sources: data.brreg.no (NLOD 2.0) and the company's own registry-linked website, subject to robots.txt.
* Expected third-party cost per 100-company run: $0.
