"""Reconstruct a tick file from M1 bars — for testing the pipeline, never for decisions.

A bar only says OHLC: it cannot say whether the high or the low came first. This script
walks each bar in the classic "open -> (low|high) -> (high|low) -> close" order chosen by
the close's direction, so the tick path at least agrees with the bar. That makes it a
*reconstruction*, not data: the manifest is tagged `"reconstruction": true` and the
intra-bar order it produces is a guess dressed as ticks.

Use it to exercise import/backtest plumbing. For numbers you would trade on, import the
broker's own tick export with `scripts/import_ticks.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.shared_schemas.settings import reload_settings  # noqa: E402
from services.market_data.tick_store import manifest_path  # noqa: E402
from services.market_data.ticks import import_ticks, tick_summary  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconstruct ticks from M1 bars (testing only)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--bars", type=int, default=2000)
    parser.add_argument("--points-per-bar", type=int, default=4)
    parser.add_argument("--spread", type=float, default=0.25, help="bid/ask spread in price")
    parser.add_argument("--out", default="/tmp/reconstructed_ticks.csv")
    parser.add_argument("--data-dir", default="", help="datasets directory to store into")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    settings = reload_settings()
    from services.api_gateway.state import TradingRuntime  # local import: heavy

    runtime = TradingRuntime(settings)
    adapter = runtime.registry.get(settings.default_broker_id())
    bars = adapter.candles(args.symbol, "M1", args.bars)
    step = 60 // max(1, args.points_per_bar)
    rows: list[tuple[str, float, float]] = []
    for bar in bars.itertuples(index=False):
        o, h, l, c = float(bar.o), float(bar.h), float(bar.l), float(bar.c)
        path = [o, l, h, c] if c >= o else [o, h, l, c]
        for i, price in enumerate(path[: args.points_per_bar]):
            ts = pd.Timestamp(int(bar.t) + i * step, unit="s", tz="UTC")
            rows.append((ts.strftime("%Y-%m-%d %H:%M:%S"),
                         round(price - args.spread / 2, 5),
                         round(price + args.spread / 2, 5)))
    Path(args.out).write_text("time,bid,ask\n" + "\n".join(f"{t},{b},{a}" for t, b, a in rows),
                              "utf-8")
    out_dir = Path(args.data_dir) if args.data_dir else settings.paths["datasets"]
    summary = import_ticks(args.out, args.symbol, out_dir, tz="UTC")
    manifest = tick_summary(out_dir, args.symbol) or {}
    manifest.update({"reconstruction": True,
                     "warning": "reconstructed from M1 bars: the intra-bar order is a guess"})
    path = manifest_path(out_dir, args.symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), "utf-8")
    print(json.dumps({k: summary[k] for k in ("rows_used", "first_t", "last_t")}, indent=2))
    print(f"stored: {summary['path']}  (reconstruction — testing only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
