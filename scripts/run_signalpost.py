#!/usr/bin/env python3
"""One-command Signalpost run: JSONL/JSON/text batch of organisation numbers in, one terminal envelope per input out."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.domain_discovery import discover_website, reverify_registry_website  # noqa: E402
from norway_company_agent.evidence import utc_now  # noqa: E402
from norway_company_agent.viewer import build_viewer  # noqa: E402
from norway_company_agent.signalpost_run import AVAILABILITY_STATES, Budget, _failed_row_envelope, read_rows, run_batch, validate  # noqa: E402

DEFAULT_MODULES = "registry,accounting_obligation,registry_live,financials,roles,group,locations,website"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def read_previous(path: str | None) -> dict[str, dict]:
    if not path or not Path(path).exists():
        return {}
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["organisation_number"]: row for row in rows if row.get("organisation_number")}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Signalpost agent: one terminal envelope per input organisation number")
    parser.add_argument("--organisations", required=True, help="JSON, JSONL or text list of organisation numbers")
    parser.add_argument("--bulk", default=None, help="Optional frozen BRREG entity CSV snapshot; the live registry API is used when absent")
    parser.add_argument("--output", required=True, help="Terminal envelope JSONL")
    parser.add_argument("--profiles-output", required=True, help="Profile JSONL; reuse as --previous on the next run for refresh")
    parser.add_argument("--report", required=True, help="Machine-readable run report")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-count", type=int, default=None, help="Fail validation when the input row count differs")
    parser.add_argument("--previous", default=None, help="Previous profiles JSONL for material-change output")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-requests-per-100", type=int, default=1900, help="Outbound request cap per 100 companies, retries and redirects included")
    parser.add_argument("--max-seconds-per-100", type=int, default=2400, help="Wall-clock cap per 100 companies")
    parser.add_argument("--modules", default=DEFAULT_MODULES)
    parser.add_argument("--checkpoint-every", type=int, default=25, help="Accepted for compatibility with the reference kit; runs are short and always finish in one pass")
    parser.add_argument("--resume", action="store_true", help="Accepted for compatibility with the reference kit; every run recomputes all rows")
    parser.add_argument("--site-output", default=None, help="Offline HTML viewer path (default: <report dir>/site/index.html); pass an empty string to skip")
    parser.add_argument("--no-discovery", action="store_true", help="Do not look for websites of companies whose registry record has none")
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        print(f"warning: ignoring unknown arguments {unknown}", file=sys.stderr)

    rows = read_rows(args.organisations)
    shards = max(1, math.ceil(len(rows) / 100))
    budget = Budget(args.max_requests_per_100 * shards, args.max_seconds_per_100 * shards)
    uninstall = budget.install()
    modules = [item.strip() for item in args.modules.split(",") if item.strip()]
    crashed: str | None = None
    try:
        previous = read_previous(args.previous)
        if not previous and Path(args.profiles_output).exists():
            previous = read_previous(args.profiles_output)
        envelopes, profiles, report = run_batch(
            rows, run_id=args.run_id, modules=modules, budget=budget, bulk_path=args.bulk, previous=previous, workers=args.workers,
            discovery_fetcher=None if args.no_discovery else discover_website,
            reverifier=None if args.no_discovery else reverify_registry_website,
        )
    except Exception as exc:  # last line of defence: still emit exactly one envelope per input row
        crashed = f"{type(exc).__name__}: {str(exc)[:200]}"
        now = utc_now()
        envelopes = [_failed_row_envelope(row, args.run_id, now, now, modules, f"run aborted: {crashed}") for row in rows]
        profiles = []
        report = {
            "run_id": args.run_id,
            "started_at": now,
            "completed_at": now,
            "expected_count": len(rows),
            "emitted_envelopes": len(envelopes),
            "modules": modules,
            "error": crashed,
            "operations": {"requests": budget.requests, "third_party_cost_usd": 0},
            "availability_totals": {state: 0 for state in AVAILABILITY_STATES},
            "validation": validate(rows, envelopes),
        }
        report["validation"]["passed"] = False
    finally:
        uninstall()
    if args.expected_count is not None:
        report["validation"]["checks"]["matches_expected_count"] = len(rows) == args.expected_count
        report["validation"]["passed"] = all(report["validation"]["checks"].values())
    write_jsonl(Path(args.profiles_output), profiles)
    write_jsonl(Path(args.output), envelopes)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    site_path = args.site_output if args.site_output is not None else str(Path(args.report).parent / "site" / "index.html")
    if site_path:
        try:
            Path(site_path).parent.mkdir(parents=True, exist_ok=True)
            Path(site_path).write_text(build_viewer(envelopes, report), encoding="utf-8")
        except Exception as exc:  # the viewer must never break the run
            print(f"warning: viewer not written: {exc}", file=sys.stderr)
    print(json.dumps({k: report.get(k) for k in ("run_id", "expected_count", "emitted_envelopes", "operations", "discovery", "availability_totals", "validation", "error")}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["validation"]["passed"] else 1)


if __name__ == "__main__":
    main()
