#!/usr/bin/env python3
"""Aggregate a run into counts only (no company or person data)."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envelopes", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    envelopes = [json.loads(line) for line in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if line.strip()]
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    by_field: dict[str, Counter] = defaultdict(Counter)
    modules: dict[str, Counter] = defaultdict(Counter)
    for envelope in envelopes:
        for claim in envelope.get("claims", []):
            by_field[claim["field"]][claim["availability"]] += 1
        for name, state in envelope.get("modules", {}).items():
            modules[name][state.get("availability", "failed")] += 1
    summary = {
        "envelopes": len(envelopes),
        "validation": report["validation"],
        "operations": report["operations"],
        "budget": report["budget"],
        "registry_anchor": report["registry_anchor"],
        "discovery": report.get("discovery"),
        "availability_totals": report["availability_totals"],
        "claims_by_field": {k: dict(v) for k, v in sorted(by_field.items())},
        "modules": {k: dict(v) for k, v in sorted(modules.items())},
        "changes_total": sum(len(e.get("changes", [])) for e in envelopes),
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
