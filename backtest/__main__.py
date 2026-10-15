"""Offline back-test. The default fixture does not use the network."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backtest.harness import render, run_fixture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare an F1 plan with one recorded race. No network."
    )
    parser.add_argument(
        "--fixture",
        default="2024-r01-bahrain-verstappen",
        help="Bundled fixture id, or a path to a recorded JSON file.",
    )
    args = parser.parse_args(argv)
    candidate = Path(args.fixture)
    try:
        if candidate.is_file():
            report = run_fixture(path=candidate)
        else:
            report = run_fixture(args.fixture)
    except (OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
