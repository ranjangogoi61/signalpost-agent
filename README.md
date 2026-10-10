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

## Synthesis and viewer

Every envelope carries a deterministic `synthesis` (what the company is, what its latest accounts show, what changed since the previous run, and what was **not** published and why). Each sentence is built only from published claims and cites their evidence ids; a validation check fails the run if a number or citation cannot be traced to a claim. No language model is used.

Every run also writes an offline single-file viewer next to the report (`<report dir>/site/index.html`, or `--site-output`): search by name or organisation number, filter, open a company, compare 2 to 4 companies, and inspect each fact's source URL, retrieval time and SHA-256. It works on mobile and desktop and makes no external requests. `scripts/build_viewer.py` rebuilds it from an envelope file; `--hide-person-names` produces a public demo.

## What it publishes

Official sources only for facts: BRREG entity register, roles (dates of birth discarded), subunits, group links and Regnskapsregisteret accounts. A company website is published only when it is verified as the exact legal entity; otherwise the claim is `ambiguous` and carries no value.

**Missing-website discovery** (companies whose registry record has no website): at most four hostname candidates are built from the legal name (e.g. `norskkaffe.no`), skipped when DNS does not resolve, then the homepage and at most two contact/about pages are fetched with robots.txt respected. The website is published **only if the company's exact nine-digit organisation number is printed on one of those pages**; name similarity alone never publishes. A registry-linked website that the name-based gate leaves `ambiguous` gets one more check: the raw homepage and up to two contact pages are searched for the exact organisation number, and it is upgraded only on a match. Disable both with `--no-discovery`. No LinkedIn, Meta or Indeed collection; no search-engine scraping; no paid APIs; no LLM calls. Third-party cost per run: $0.

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
