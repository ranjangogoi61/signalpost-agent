from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .runner import SignalpostRunner


def read_orgnrs(path: Path) -> list[str]:
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        # Accept one organisation number per line in v0.1.
        values.append(value)
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Signalpost research agent")
    parser.add_argument("--input", required=True, type=Path, help="text file: one organisation number per line")
    parser.add_argument("--output", required=True, type=Path, help="JSONL result file")
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"input file not found: {args.input}", file=sys.stderr)
        return 2

    settings = Settings.from_env()
    runner = SignalpostRunner(settings)
    results = runner.run(read_orgnrs(args.input))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.to_dict(), ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")

    status_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
    print(json.dumps({"run_id": results[0].run_id if results else None, "results": len(results), "status_counts": status_counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
