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

Optional: `--bulk <brreg snapshot, gzip or plain CSV>` (frozen BRREG snapshot, verified live against the API run on the same 100 companies; an unreadable snapshot falls back to the live registry; the live registry is used without it), `--previous <earlier profiles.jsonl>` (refresh / material changes), `--no-discovery`, `--max-requests-per-100` (default 1900), `--max-seconds-per-100` (default 2400), `--workers` (default 8).

The agent reads whatever batch it is given; it assumes no company count. The reference kit's flags (`--resume`, `--checkpoint-every`) are accepted and unknown flags are ignored with a warning. If the run aborts unexpectedly it still writes one `failed` envelope per input row and exits 1 with the error in the report.

## Models, APIs, licences, cost

| Item | Declaration |
|---|---|
| Language models | None |
| Paid or keyed APIs | None by default. Optional: Brave Search API, used only if the operator sets `BRAVE_SEARCH_API_KEY`; about $0.005 per query, at most one query per company without a registry website, capped at $8 per 100 companies and reported in the run report |
| Registry data | data.brreg.no (Enhetsregisteret, roles, subunits; Regnskapsregisteret accounts), NLOD 2.0 |
| Job ads | NAV Arbeidsplassen job vacancy feed (pam-stilling-feed.nav.no), NAV's public experiment token or an operator-supplied `NAV_FEED_TOKEN`; free under NAV's terms; active ads only, matched by exact organisation number, no descriptions or contact details kept |
| Company websites | Registry-linked or discovered by exact organisation number; robots.txt respected |
| LinkedIn / Meta / Indeed / search engines / directories | Not accessed |
| Expected third-party cost | $0 per 100-company run without a key; at most about $0.5 per 100 companies with one |
| Measured on CI (100 companies, live) | about 920 outbound requests (retries and redirects counted, about 95 of them the NAV feed scan) and about 410 s, inside the 2,000 request / 45 minute budget. The `--bulk` snapshot path on the same 100 companies: 643 requests, about 235 s |

## What it publishes

Facts only from an official register (identity, legal status, business address, registered business activity and purpose, a corporate contact email (never free-mail or sole-proprietorship addresses, never phone numbers), founding and registration dates, VAT registration, sector, industries, annual accounts and the years of filed account copies, active job ads from NAV's open feed, role holders, subunits, parent unit, Foretaksregisteret registration, last submitted accounts year, VAT registration date, recent register updates from the open update feed with the names of changed fields only, Arbeidstilsynet cleaning-company and occupational-health approvals, and Mattilsynet food-safety inspection grades) or from a company page that prints the company's exact organisation number. Every published claim carries a source URL, retrieval time and content SHA-256. Anything not found, blocked, not applicable, ambiguous or failed is returned as that state with no value. One envelope per input row, in input order, even for invalid, duplicate, unknown or deleted numbers.

Role holders are published by name and role only; dates of birth are discarded.

## Source rights, secrets and safe URL handling

* **Source rights:** the register data is open (NLOD 2.0). Company pages are fetched only when robots.txt allows it, at most a homepage plus a handful of the company's own pages, and are published only with the company's exact organisation number as proof. Search-engine output (only if an operator key is set) is transient; only hostnames are kept.
* **Secrets:** none in the repository. The optional `BRAVE_SEARCH_API_KEY` is read from the environment only, is never printed or written to any output, and the agent runs fully without it.
* **Safe URL handling:** every URL is checked against private, loopback and link-local addresses before and after redirects (`assert_public_url`); redirects off the company's registered domain are not followed for page content; responses are size-limited.

## Verification

CI runs on every push to `dev`: unit tests (no network allowed), a live 100-company run, a same-input refresh run (0 false changes), a live `--bulk` snapshot run with a field-by-field parity check against the live run (`parity.json` on the `smoke-results` branch), and a headless-browser check of the viewer.

## Precision rules (from Builderr's audit)

* A website's social profiles, news, careers and contact facts are withheld (`ambiguous`) unless the page prints the company's exact organisation number and lists at most two other organisations, so a parent group's or directory's site is never attributed to a subsidiary.
* A social profile is published only if its handle equals the company's name.
* The agent returns a result for every company without any search key; Builderr's official runs are keyless.

## Synthesis and UX

Each envelope has a deterministic, source-cited `synthesis` (facts plus a plain-language assessment such as profit or loss, negative equity, winding-down flags and public activity, which never states a number that is not in a cited claim), and each run writes an offline mobile-ready viewer (`site/index.html`) to find, compare (with a source link on every compared value and a "show only differences" filter) and verify companies. A public demo built from the 100-company smoke batch (person names hidden) is `index.html` on the `smoke-results` branch.

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
