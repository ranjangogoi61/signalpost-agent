#!/usr/bin/env python3
"""Build a single-file offline HTML viewer from a Signalpost envelope JSONL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from norway_company_agent.viewer import build_viewer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envelopes", required=True)
    parser.add_argument("--report", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--hide-person-names", action="store_true", help="Replace role-holder names for a public demo")
    args = parser.parse_args()
    envelopes = [json.loads(line) for line in Path(args.envelopes).read_text(encoding="utf-8").splitlines() if line.strip()]
    report = json.loads(Path(args.report).read_text(encoding="utf-8")) if args.report and Path(args.report).exists() else None
    html = build_viewer(envelopes, report, hide_person_names=args.hide_person_names)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"wrote {args.out} ({len(html):,} bytes, {len(envelopes)} companies)")


if __name__ == "__main__":
    main()
