#!/usr/bin/env python3
"""Run the trainer and the backtester on imported data, then print what it means.

    python scripts/evaluate_dataset.py --symbol XAUUSD --csv ~/Downloads/XAUUSD_M1.csv --tz Asia/Bangkok
    python scripts/evaluate_dataset.py --symbol XAUUSD            # use an already-imported dataset

The point of this script is the difference between two kinds of number:

* on the simulated feed, "the model is UNVALIDATED" is the *correct* answer and
  says nothing about whether the model works;
* on real bars the same gates produce an answer worth acting on — still divided by
  a fold check that refits the model at every fold, so a lucky week cannot pass it.

Nothing here touches the running dashboard's state: it reads a file, trains a
version, backtests it and writes a JSON report under storage/backtests/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from packages.shared_schemas.models import BacktestRequest, SymbolSpec  # noqa: E402
from packages.shared_schemas.settings import get_settings  # noqa: E402
from services.ai_forecast.trainer import ForecastTrainer  # noqa: E402
from services.backtest_engine.backtester import Backtester  # noqa: E402
from services.market_data.dataset import (DatasetError, describe, import_candles,  # noqa: E402
                                          load_dataset, workspace_dataset_dir)
from services.risk_engine.engine import RiskEngine  # noqa: E402
from services.risk_engine.planner import TradePlanner  # noqa: E402
from packages.persistence.db import Database  # noqa: E402


def spec_for(settings, symbol: str) -> SymbolSpec:
    broker_id = settings.default_broker_id()
    raw = settings.symbol_spec(broker_id, symbol)
    if not raw:
        raise SystemExit(f"symbol {symbol} is not declared on broker {broker_id} in config/brokers.yaml")
    allowed = set(SymbolSpec.model_fields)
    fields = {k: v for k, v in raw.items() if k in allowed and k != "symbol"}
    return SymbolSpec(symbol=symbol, **fields)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--csv", default=None, help="import this file first (optional)")
    parser.add_argument("--tz", default="UTC", help="timezone of --csv timestamps")
    parser.add_argument("--dataset-dir", default=None, help="directory within configured workspace datasets")
    parser.add_argument("--timeframe", default="M1", choices=["M1", "M5", "M15", "M30", "H1", "H4", "D1"])
    parser.add_argument("--bars", type=int, default=0, help="use only the last N bars (0 = all)")
    parser.add_argument("--version", default=None, help="model version tag")
    parser.add_argument("--slippage-points", type=float, default=2.0)
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--skip-backtest", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    try:
        args.dataset_dir = workspace_dataset_dir(settings.paths["datasets"], args.dataset_dir)
        if args.csv:
            meta = import_candles(args.csv, args.symbol, args.dataset_dir, tz=args.tz,
                                  timeframe=args.timeframe)
            print(f"imported {meta['rows']} rows "
                  f"({meta['from_iso']} → {meta['to_iso']}), "
                  f"dropped dupes={meta['dropped_duplicates']} invalid={meta['dropped_invalid']}")
        m1 = load_dataset(args.dataset_dir, args.symbol, args.timeframe)
    except DatasetError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    if args.bars:
        m1 = m1.tail(args.bars).reset_index(drop=True)
    facts = describe(m1)
    print("data:", json.dumps({k: facts[k] for k in
                               ("rows", "from_iso", "to_iso", "span_days", "gaps",
                                "largest_gap_minutes")}, ensure_ascii=False))

    spec = spec_for(settings, args.symbol)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    version = args.version or f"{args.symbol.lower()}-{args.timeframe.lower()}-{stamp}"
    report: dict = {"symbol": args.symbol, "timeframe": args.timeframe, "data": facts,
                    "version": version, "feed": "imported-real-candles"}

    if not args.skip_train:
        trainer = ForecastTrainer(settings)
        print(f"\ntraining {version} …")
        result = trainer.train(m1, version)
        horizons = result.metrics.get("horizons", {})
        print(f"\n{'horizon':>8} {'dir.acc':>8} {'brier Δ':>9} {'fold pass':>10} "
              f"{'method':<28} verdict")
        for horizon, m in horizons.items():
            method = str(m.get("validation_method", "-"))[:28]
            verdict = "APPROVED" if m.get("approved") else "baseline / UNVALIDATED"
            print(f"{horizon + 'm':>8} {m.get('directional_accuracy', 0):>8.3f} "
                  f"{m.get('brier_improvement', 0):>9.3f} {m.get('fold_pass_rate', 0):>10.2f} "
                  f"{method:<28} {verdict}")
        if not horizons:
            print("no horizon trained: this dataset is too short for the configured horizons "
                  "— feed more bars (a few thousand at least) before reading anything into it")
        report["training"] = {"approved": bool(result.metrics.get("approved")),
                              "validation": result.metrics.get("validation"),
                              "horizons": horizons}
        print(f"\nmodel approved: {result.metrics.get('approved')}")
        print(f"validation: {result.metrics.get('validation')}")

    if not args.skip_backtest:
        db = Database(settings.paths["database"])
        risk = RiskEngine(settings, db)
        planner = TradePlanner(settings.risk_cfg(), settings.app.get("scoring"))
        engine = Backtester(settings, risk, planner)
        request = BacktestRequest(symbol=args.symbol, bars=len(m1),
                                  slippage_points=args.slippage_points)
        bt = engine.run(m1, spec, request, broker_id=settings.default_broker_id())
        m = bt.metrics
        print("\nbacktest:", json.dumps({
            "trades": m.trades, "win_rate": round(m.win_rate, 1),
            "net_profit": round(m.net_profit, 2), "profit_factor": round(m.profit_factor, 2),
            "expectancy": round(m.expectancy, 2), "max_drawdown_pct": round(m.max_drawdown_pct, 2),
            "no_trade_rate": round(m.no_trade_rate, 1), "total_costs": round(m.total_costs, 2),
            "total_swap": round(m.total_swap, 2),
        }, ensure_ascii=False))
        report["backtest"] = bt.model_dump()

    out = Path(settings.paths["backtests"]) / f"dataset_eval_{args.symbol}_{stamp}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nreport -> {out}")
    if len(pd.DataFrame(m1)) < 5000:
        print("note: fewer than 5000 bars — fold checks will be thin and the verdict noisy",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
