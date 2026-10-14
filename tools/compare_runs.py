#!/usr/bin/env python3
"""Parity check between two runs of the same companies (live registry anchor vs bulk snapshot anchor). Counts only."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

CORE = {"legal_name", "legal_form", "municipality", "industry", "business_address", "founded", "legal_status", "sector"}


def load(path: str) -> dict[str, dict]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["organisation_number"]: r for r in rows}


def norm(value) -> str:
    return " ".join(str(value).casefold().replace(",", " ").split())


def main() -> int:
    a, b = load(sys.argv[1]), load(sys.argv[2])
    same, differ, only_a, only_b = Counter(), Counter(), Counter(), Counter()
    for org in sorted(set(a) & set(b)):
        ca = {c["field"]: c for c in a[org]["claims"]}
        cb = {c["field"]: c for c in b[org]["claims"]}
        for field in sorted(set(ca) | set(cb)):
            x, y = ca.get(field), cb.get(field)
            xa = bool(x) and x["availability"] == "available"
            ya = bool(y) and y["availability"] == "available"
            if xa and ya:
                (same if norm(x["value"]) == norm(y["value"]) else differ)[field] += 1
            elif xa:
                only_a[field] += 1
            elif ya:
                only_b[field] += 1
    summary = {
        "companies_compared": len(set(a) & set(b)),
        "same": dict(same), "differ": dict(differ), "only_in_first_run": dict(only_a), "only_in_second_run": dict(only_b),
    }
    core_bad = {f: n for f, n in differ.items() if f in CORE and n > max(2, 0.1 * (same[f] + n))}
    summary["core_fields_over_tolerance"] = core_bad
    out = Path(sys.argv[3])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 1 if core_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
