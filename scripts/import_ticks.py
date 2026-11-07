"""Import a broker tick export so backtests can settle intra-bar ambiguity.

    .venv/bin/python scripts/import_ticks.py --csv ~/Downloads/XAUUSD_ticks.csv --symbol XAUUSD
    .venv/bin/python scripts/import_ticks.py --csv ticks.csv --symbol XAUUSD --tz Etc/GMT-3

The file must contain time, bid and ask (any column order, `,` or `;` separated).
Nothing is dropped silently: the summary prints how many rows were unusable and why.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.shared_schemas.settings import reload_settings  # noqa: E402
from services.market_data.ticks import TickDataError, import_ticks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Import tick data (time, bid, ask)")
    parser.add_argument("--csv", required=True, help="tick export to import")
    parser.add_argument("--symbol", required=True, help="symbol these ticks belong to")
    parser.add_argument("--tz", default="UTC",
                       help="timezone of the file's timestamps when they carry none")
    parser.add_argument("--data-dir", default="", help="override the datasets directory")
    args = parser.parse_args()

    settings = reload_settings()
    out_dir = Path(args.data_dir) if args.data_dir else settings.paths["datasets"]
    try:
        summary = import_ticks(args.csv, args.symbol, out_dir, tz=args.tz)
    except TickDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({k: v for k, v in summary.items() if k != "path"}, indent=2,
                     ensure_ascii=False))
    print(f"\nstored: {summary['path']}")
    if summary["dropped"]:
        print("dropped rows (kept nothing questionable): "
              + ", ".join(f"{k}: {v}" for k, v in summary["dropped"].items()))
    print(f"next: backtests for {args.symbol.upper()} will use these ticks automatically")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
