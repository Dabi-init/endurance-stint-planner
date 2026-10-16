"""Update the derived accuracy log. The default source is OpenF1.

``python -m accuracy.update`` is not used: run ``python -m accuracy``.
FastF1 is optional (``--source fastf1``) and its cache stays in a temp directory.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date
from pathlib import Path

from accuracy.publish import PAGES_PATH, build_log, read_log, write_log, write_page
from accuracy.sources import OPENF1_INTERVAL_SEC, collect_fastf1, fetch_openf1
from historical.http import HttpxTransport


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score completed Grands Prix and write the public accuracy log."
    )
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument(
        "--as-of",
        default=date.today().isoformat(),
        help="Include race sessions on or before this YYYY-MM-DD date.",
    )
    parser.add_argument("--source", choices=("openf1", "fastf1"), default="openf1")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Score every completed race again instead of keeping stored rounds.",
    )
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--page", type=Path, default=PAGES_PATH)
    args = parser.parse_args(argv)
    try:
        _check_date(args.as_of)
    except ValueError:
        print("as-of must be YYYY-MM-DD", file=sys.stderr)
        return 2
    if args.season < 1950 or args.season > 2100:
        print("season must be from 1950 to 2100", file=sys.stderr)
        return 2
    try:
        races = _races(args.source, args.season, args.as_of)
    except ModuleNotFoundError:
        print(
            "FastF1 is not installed. The scheduled job uses OpenF1. "
            "Install FastF1 locally to use --source fastf1.",
            file=sys.stderr,
        )
        return 2
    previous = None if args.refresh else read_log(args.season, args.data_dir)
    payload = build_log(
        races,
        season=args.season,
        as_of=args.as_of,
        previous=previous,
        refresh=args.refresh,
    )
    path = write_log(payload, args.data_dir)
    page = write_page(payload, args.page)
    rates = payload["rates"]
    print(
        f"Wrote {path} and {page}. "
        f"{rates['races']} races, pit-lap error {rates['pit_lap_mae']}, "
        f"finish-order error {rates['finish_order_mae']}."
    )
    return 0


def _races(source: str, season: int, as_of: str) -> list[dict[str, object]]:
    if source == "openf1":
        transport = HttpxTransport(min_interval_sec=OPENF1_INTERVAL_SEC)
        try:
            return fetch_openf1(transport, season=season, as_of=as_of)
        finally:
            transport._client.close()
    with tempfile.TemporaryDirectory(prefix="pitwall-fastf1-") as cache:
        import fastf1

        return collect_fastf1(fastf1, season=season, as_of=as_of, cache_dir=Path(cache))


def _check_date(value: str) -> None:
    date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
