"""Import a broker tick export so backtests can settle intra-bar ambiguity.

    .venv/bin/python scripts/import_ticks.py --csv ~/Downloads/XAUUSD_ticks.csv --symbol XAUUSD
    .venv/bin/python scripts/import_ticks.py --csv ticks.csv --symbol XAUUSD --tz Etc/GMT-3
    .venv/bin/python scripts/import_ticks.py --csv big.csv --symbol XAUUSD --chunk-rows 100000

The file must contain time, bid and ask (any column order, `,` or `;` separated).
Nothing is dropped silently: the summary prints how many rows were unusable and why.

Ticks are written one file per UTC day (`datasets/ticks/XAUUSD/2026-11-07.parquet`), so a
backtest reads only the days its window touches instead of the whole history. Reading is
streamed in `--chunk-rows` blocks: peak memory is one day of ticks, not the whole export.
Use `--single-file` only to reproduce the first version's layout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.shared_schemas.settings import reload_settings  # noqa: E402
from services.market_data.tick_store import coverage, default_format, pyarrow_available  # noqa: E402
from services.market_data.ticks import TickDataError, import_ticks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Import tick data (time, bid, ask)")
    parser.add_argument("--csv", required=True, help="tick export to import")
    parser.add_argument("--symbol", required=True, help="symbol these ticks belong to")
    parser.add_argument("--tz", default="UTC",
                        help="timezone of the file's timestamps when they carry none")
    parser.add_argument("--data-dir", default="", help="override the datasets directory")
    parser.add_argument("--chunk-rows", type=int, default=200_000,
                        help="rows per read (smaller = less memory, more passes)")
    parser.add_argument("--single-file", action="store_true",
                        help="write the legacy one-file-per-symbol layout instead of daily files")
    parser.add_argument("--format", default="", choices=["", "parquet", "csv.gz"],
                        help=f"daily file format (default: {default_format()})")
    args = parser.parse_args()

    settings = reload_settings()
    out_dir = Path(args.data_dir) if args.data_dir else settings.paths["datasets"]
    if args.format and not args.single_file and args.format == "parquet" and not pyarrow_available():
        print("error: --format parquet needs pyarrow (pip install pyarrow)", file=sys.stderr)
        return 1
    try:
        summary = import_ticks(args.csv, args.symbol, out_dir, tz=args.tz,
                               layout="file" if args.single_file else "daily",
                               fmt=(args.format or None), chunk_rows=args.chunk_rows)
    except TickDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({k: v for k, v in summary.items() if k not in ("path", "days")},
                     indent=2, ensure_ascii=False))
    if summary.get("days"):
        print("\nday            rows      bytes  first tick (UTC)")
        for day in summary["days"]:
            stamp = pd.Timestamp(int(day["first_t"]), unit="s", tz="UTC")
            print(f"{day['day']}  {day['rows']:>7}  {day['bytes']:>9}  "
                  f"{stamp.strftime('%Y-%m-%d %H:%M:%S')}")
        cov = coverage(out_dir, args.symbol)
        print(f"\n{len(summary['days'])} day files, {cov['rows']} rows total")
    print(f"\nstored: {summary['path']}")
    if summary.get("dropped"):
        print("dropped rows (kept nothing questionable): "
              + ", ".join(f"{k}: {v}" for k, v in summary["dropped"].items()))
    if args.single_file:
        print(f"next: backtests for {args.symbol.upper()} will use these ticks, but this "
              f"layout loads the whole file into memory — prefer the daily layout")
    else:
        print(f"next: backtests for {args.symbol.upper()} will use these ticks automatically; "
              f"a window loads only the days it touches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
