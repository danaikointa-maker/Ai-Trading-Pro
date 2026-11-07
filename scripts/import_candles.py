#!/usr/bin/env python3
"""Import a broker candle export so the platform can be measured on real data.

    python scripts/import_candles.py --csv ~/Downloads/XAUUSD_M1.csv --symbol XAUUSD --tz Asia/Bangkok

Accepts MT5 exports (`<DATE> <TIME> <OPEN> ...`, tab or comma) and generic CSVs
(time/datetime + open/high/low/close/volume). Naive timestamps are interpreted in
`--tz`, which is why the flag has no default you can forget: MT5 writes broker
server time, and treating it as UTC shifts every bar by the offset.

Writes `storage/datasets/{SYMBOL}_M1.csv` plus a `.meta.json` sidecar with the row
counts, gaps and every row the importer had to drop.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.market_data.dataset import DatasetError, import_candles  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="path to the broker export")
    parser.add_argument("--symbol", required=True, help="instrument, e.g. XAUUSD")
    parser.add_argument("--tz", default="UTC",
                        help="timezone of the file's timestamps (MT5 exports server time)")
    parser.add_argument("--timeframe", default="M1", choices=["M1", "M5", "M15", "M30", "H1", "H4", "D1"])
    parser.add_argument("--digits", type=int, default=None, help="round prices to this many decimals")
    parser.add_argument("--out-dir", default="storage/datasets")
    args = parser.parse_args()

    try:
        meta = import_candles(args.csv, args.symbol, args.out_dir, tz=args.tz,
                              digits=args.digits, timeframe=args.timeframe)
    except DatasetError as exc:
        print(f"import rejected: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(meta, indent=2, ensure_ascii=False))
    if meta["dropped_invalid"]:
        print(f"warning: dropped {meta['dropped_invalid']} row(s) with broken OHLC geometry",
              file=sys.stderr)
    if meta["gaps"]:
        print(f"note: {meta['gaps']} gap(s) larger than one bar "
              f"(largest {meta['largest_gap_minutes']} min — weekends/holidays are normal)",
              file=sys.stderr)
    print(f"\nimported -> {Path(args.out_dir) / meta['csv']}")
    print(f"now run:  python scripts/evaluate_dataset.py --symbol {meta['symbol']} "
          f"--timeframe {meta['timeframe']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
