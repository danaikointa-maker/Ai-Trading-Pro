#!/usr/bin/env python3
"""Does the trained model actually beat the rule proxy? Run both and compare.

    python scripts/model_edge_report.py                         # simulated bars
    python scripts/model_edge_report.py --symbol XAUUSD --dataset   # imported bars
    python scripts/model_edge_report.py --bars 20000 --json out.json

The backtest can score two different forecasts: the deterministic rule proxy it has
always used, and a walk-forward model fitted inside the run on bars that end a full
label horizon before each segment it predicts. Everything else — bars, costs, risk
engine, gates — is identical, so the difference between the two columns is the
model's contribution and nothing else.

Two numbers matter and they answer different questions:

* directional accuracy, on the same decision bars, says whether the model knows
  anything the proxy does not;
* the trading metrics say whether that knowledge survives costs, the gate and
  position sizing. A model can win the first and lose the second.

Exit code 0 = both runs completed, 1 = a run failed, 2 = bad arguments or no data.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.persistence.db import Database  # noqa: E402
from packages.shared_schemas.models import BacktestRequest, SymbolSpec  # noqa: E402
from packages.shared_schemas.settings import get_settings  # noqa: E402
from services.backtest_engine.backtester import MIN_M1_BARS, Backtester  # noqa: E402
from services.risk_engine.engine import RiskEngine  # noqa: E402
from services.risk_engine.planner import TradePlanner  # noqa: E402


def _bars(args, settings):
    """Imported dataset when asked for, otherwise the simulated feed."""
    if args.dataset:
        from services.market_data.dataset import DatasetError, load_dataset

        try:
            return load_dataset(settings.paths["datasets"], args.symbol), "imported dataset"
        except DatasetError as exc:
            print(f"cannot load dataset for {args.symbol}: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    from services.market_data.simulator import SyntheticFeed

    feed = SyntheticFeed({args.symbol: {"digits": 2, "point": 0.01, "contract_size": 100}},
                         history_bars=args.bars, seed=args.seed)
    return feed.warm_history(args.symbol, args.bars), f"simulated feed (seed {args.seed})"


def _spec(settings, symbol: str):
    """Symbol contract straight from config, the same way evaluate_dataset.py reads it."""
    broker_id = settings.default_broker_id()
    raw = settings.symbol_spec(broker_id, symbol)
    if not raw:
        print(f"symbol {symbol} is not declared on broker {broker_id} in config/brokers.yaml",
              file=sys.stderr)
        raise SystemExit(2)
    allowed = set(SymbolSpec.model_fields)
    fields = {k: v for k, v in raw.items() if k in allowed and k != "symbol"}
    return SymbolSpec(symbol=symbol, **fields)


def _row(label: str, left, right, fmt: str = "{:.2f}") -> str:
    def cell(v):
        return fmt.format(v) if isinstance(v, (int, float)) else str(v)
    delta = ""
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        diff = right - left
        delta = f"{diff:+.2f}" if abs(diff) >= 0.005 else "same"
    return f"{label:<26} {cell(left):>14} {cell(right):>14} {delta:>12}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--bars", type=int, default=20000, help="M1 bars (simulated feed only)")
    ap.add_argument("--dataset", action="store_true", help="use an imported dataset instead")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--slippage-points", type=float, default=2.0)
    ap.add_argument("--json", dest="json_out", default="", help="also write the full comparison here")
    args = ap.parse_args()

    if not args.dataset and args.bars < MIN_M1_BARS:
        print(f"--bars {args.bars} is below the engine's minimum of {MIN_M1_BARS}", file=sys.stderr)
        return 2

    settings = get_settings()
    db = Database(settings.paths["database"])
    engine = Backtester(settings, RiskEngine(settings, db),
                        TradePlanner(settings.risk_cfg(), settings.app.get("scoring")))
    m1, source = _bars(args, settings)
    spec = _spec(settings, args.symbol)
    print(f"{args.symbol}: {len(m1)} M1 bars from {source}\n")

    runs = {}
    for mode in ("rule-proxy", "model"):
        started = time.time()
        print(f"running {mode} ...", flush=True)
        try:
            runs[mode] = engine.run(
                m1, spec,
                BacktestRequest(symbol=args.symbol, bars=len(m1), forecast_source=mode,
                                slippage_points=args.slippage_points),
                broker_id=settings.default_broker_id(),
                data_note=f"Bar data: {source}.")
        except Exception as exc:  # noqa: BLE001 - report which side failed, do not traceback
            print(f"  {mode} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(f"  done in {time.time() - started:.1f}s")

    base, model = runs["rule-proxy"].metrics, runs["model"].metrics
    edge = runs["model"].diagnostics.get("model_edge", {})

    print(f"\n{'':<26} {'rule proxy':>14} {'model':>14} {'delta':>12}")
    print("-" * 70)
    print(_row("trades", base.trades, model.trades, "{:.0f}"))
    print(_row("win rate %", base.win_rate, model.win_rate))
    print(_row("net profit", base.net_profit, model.net_profit))
    print(_row("profit factor", base.profit_factor, model.profit_factor))
    print(_row("expectancy / trade", base.expectancy, model.expectancy))
    print(_row("max drawdown %", base.max_drawdown_pct, model.max_drawdown_pct))
    print(_row("no-trade rate %", base.no_trade_rate, model.no_trade_rate))
    print(_row("total costs", base.total_costs, model.total_costs))

    if edge.get("available"):
        print(f"\ndirection, on the {edge['scored_decisions']} decision bars the model answered "
              f"(sideways excluded):")
        print(_row("  directional accuracy", edge["proxy_dir_accuracy_same_bars"],
                   edge["model_dir_accuracy"], "{:.3f}"))
        print(f"\n{'segment':<10}{'bars':>14}{'train rows':>12}{'decisions':>11}"
              f"{'model acc':>11}{'proxy acc':>11}  note")
        for seg in edge["segments"]:
            print(f"{seg['segment']:<10}{str(seg['bars']):>14}{seg['train_rows']:>12}"
                  f"{seg['decisions']:>11}{seg['model_dir_accuracy']:>11.3f}"
                  f"{seg['proxy_dir_accuracy']:>11.3f}  {seg['note'][:48]}")
        print(f"\ndecisions: {edge['decisions_from_model']} from the model, "
              f"{edge['decisions_from_proxy']} fell back to the proxy")
    else:
        print(f"\nthe model never ran: {edge.get('reason', 'unknown')}")

    verdict = "no comparable evidence"
    if edge.get("available") and edge.get("scored_decisions"):
        better_dir = edge["edge_vs_proxy"] > 0
        better_pnl = model.net_profit > base.net_profit
        verdict = {
            (True, True): "the model beat the proxy on direction AND on P&L",
            (True, False): "the model called direction better but did not earn more — "
                           "costs and the gate ate the edge",
            (False, True): "the model earned more without calling direction better — "
                           "most likely noise, not edge",
            (False, False): "no edge: the proxy matched or beat the model on both",
        }[(better_dir, better_pnl)]
    print(f"\nverdict: {verdict}")
    if base.trades < 30 or model.trades < 30:
        print("warning: fewer than 30 trades on one side — this comparison is a smoke test, "
              "not evidence. Feed more bars (or real data) before believing it.", file=sys.stderr)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "symbol": args.symbol, "bars": len(m1), "source": source,
            "rule_proxy": base.model_dump(), "model": model.model_dump(),
            "model_edge": edge, "verdict": verdict,
        }, indent=2, default=str), encoding="utf-8")
        print(f"\nfull comparison -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
