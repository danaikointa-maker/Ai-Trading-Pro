"""Offline, read-only outcome study for exact-bar TradingView shadow evidence.

This is an attribution/research helper, not a signal, backtester, RiskEngine, or
execution path. It requires caller-supplied closed-bar timestamps and an explicit
cost model; no API or runtime worker invokes it.
"""
from __future__ import annotations

import math
import re
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd

from integrations.tradingview.normalizer import canonical_no7_timeframe
from packages.shared_schemas.models import SymbolSpec
from packages.shared_schemas.tradingview import ExternalAnalysisEvidence


@dataclass(frozen=True)
class ShadowNo7Decision:
    """Minimal No7 decision projection with an explicit availability time."""

    symbol: str
    timeframe: str
    bar_close_utc: int
    available_at_utc: int
    action: str
    score: float | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.timeframe.strip():
            raise ValueError("No7 decision requires symbol and timeframe")
        if type(self.bar_close_utc) is not int or type(self.available_at_utc) is not int:
            raise ValueError("No7 timestamps must be integer UTC seconds")
        if self.available_at_utc < self.bar_close_utc:
            raise ValueError("No7 decision cannot be available before its closed bar")
        if self.action.strip().upper() not in {"BUY", "SELL", "WAIT", "HOLD"}:
            raise ValueError("unsupported No7 action for shadow comparison")
        if self.score is not None and (
            isinstance(self.score, bool) or not math.isfinite(float(self.score))
            or not 0 <= float(self.score) <= 100
        ):
            raise ValueError("No7 score must be finite and within 0..100")


@dataclass(frozen=True)
class ShadowCostAssumptions:
    """Static round-trip cost inputs, expressed in broker points and lots."""

    spread_points: float
    slippage_points_per_side: float
    reference_lot: float

    def __post_init__(self) -> None:
        values = (self.spread_points, self.slippage_points_per_side, self.reference_lot)
        if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in values):
            raise ValueError("shadow cost assumptions must be finite numbers")
        if self.spread_points < 0 or self.slippage_points_per_side < 0 or self.reference_lot <= 0:
            raise ValueError("shadow costs cannot be negative and reference lot must be positive")


def _timeframe_seconds(value: str) -> int:
    canonical = canonical_no7_timeframe(value)
    match = re.fullmatch(r"([MHDW])(\d+)", canonical)
    if not match:
        raise ValueError(f"unsupported replay timeframe: {value}")
    amount = int(match.group(2))
    multiplier = {"M": 60, "H": 3600, "D": 86400, "W": 604800}[match.group(1)]
    if amount <= 0 or amount > 10080:
        raise ValueError(f"unsupported replay timeframe: {value}")
    return amount * multiplier


def _direction(action: str) -> int:
    action = action.strip().upper()
    return 1 if action == "BUY" else -1 if action == "SELL" else 0


def _lens_direction(evidence: ExternalAnalysisEvidence) -> int:
    long_ready = evidence.long_score >= evidence.score_threshold
    short_ready = evidence.short_score >= evidence.score_threshold
    if long_ready and evidence.long_score > evidence.short_score:
        return 1
    if short_ready and evidence.short_score > evidence.long_score:
        return -1
    return 0


def _validate_bars(bars: pd.DataFrame) -> tuple[list[int], list[float], list[float]]:
    required = {"t", "o", "c"}
    if bars is None or bars.empty or not required.issubset(bars.columns):
        raise ValueError("closed-bar input requires non-empty t/o/c columns")
    timestamps: list[int] = []
    opens: list[float] = []
    closes: list[float] = []
    for row in bars[["t", "o", "c"]].itertuples(index=False, name=None):
        timestamp, open_price, close_price = row
        if isinstance(timestamp, bool) or not math.isfinite(float(timestamp)):
            raise ValueError("bar timestamps must be finite UTC seconds")
        if int(timestamp) != float(timestamp):
            raise ValueError("bar timestamps must be integer UTC seconds")
        if any(isinstance(price, bool) or not math.isfinite(float(price)) or float(price) <= 0
               for price in (open_price, close_price)):
            raise ValueError("bar prices must be finite and positive")
        timestamps.append(int(timestamp))
        opens.append(float(open_price))
        closes.append(float(close_price))
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("closed bars must be strictly time-ordered and unique")
    return timestamps, opens, closes


def _metric(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"samples": 0, "mean_net_points": None, "median_net_points": None,
                "positive_net_pct": None}
    return {
        "samples": len(values),
        "mean_net_points": round(sum(values) / len(values), 4),
        "median_net_points": round(float(pd.Series(values).median()), 4),
        "positive_net_pct": round(sum(value > 0 for value in values) / len(values) * 100, 2),
    }


def replay_tradingview_shadow(
    *,
    symbol: str,
    timeframe: str,
    evidence: Iterable[ExternalAnalysisEvidence | dict[str, Any]],
    no7_decisions: Iterable[ShadowNo7Decision | dict[str, Any]],
    closed_bars: pd.DataFrame,
    spec: SymbolSpec,
    costs: ShadowCostAssumptions,
    horizons_bars: tuple[int, ...] = (1, 3, 6, 12),
) -> dict[str, Any]:
    """Compare exact-bar directions and measure later cost-adjusted price moves.

    ``closed_bars.t`` is the UTC close timestamp for each candle. The entry is
    priced at the open of the first later bar whose open time (close minus the
    timeframe duration) is at or after the evidence/decision availability time.
    Outcomes use only a subsequent bar close. This avoids using the signal bar or
    any candle that began before the decision became available.

    The report is predictive price-move research in points at ``reference_lot``;
    it does not simulate SL/TP, margin, fills, swaps, or broker execution.
    """
    canonical_symbol = symbol.strip().upper()
    canonical_tf = canonical_no7_timeframe(timeframe)
    if not canonical_symbol or canonical_symbol != spec.symbol.strip().upper():
        raise ValueError("analysis symbol must match the supplied broker specification")
    interval = _timeframe_seconds(canonical_tf)
    horizons = tuple(sorted(set(horizons_bars)))
    if (not horizons or any(type(horizon) is not int or horizon <= 0 for horizon in horizons)):
        raise ValueError("horizons must be positive integer bar counts")
    if spec.source != "broker" or spec.sizing_blocked or not spec.lot_is_valid(costs.reference_lot):
        raise ValueError("a complete broker spec and legal reference lot are required")
    if not math.isfinite(spec.commission_per_lot_round_turn) or spec.commission_per_lot_round_turn < 0:
        raise ValueError("broker commission must be finite and non-negative")

    times, opens, closes = _validate_bars(closed_bars)
    time_to_index = {timestamp: index for index, timestamp in enumerate(times)}

    evidence_by_key: dict[tuple[str, str, int], list[ExternalAnalysisEvidence]] = defaultdict(list)
    filtered_evidence = 0
    for item in evidence:
        parsed = (item if isinstance(item, ExternalAnalysisEvidence)
                  else ExternalAnalysisEvidence.model_validate(item))
        key = (parsed.mapped_symbol.strip().upper(),
               canonical_no7_timeframe(parsed.timeframe), parsed.bar_close_utc)
        if key[:2] != (canonical_symbol, canonical_tf):
            filtered_evidence += 1
            continue
        evidence_by_key[key].append(parsed)

    decisions_by_key: dict[tuple[str, str, int], list[ShadowNo7Decision]] = defaultdict(list)
    filtered_decisions = 0
    for item in no7_decisions:
        parsed = item if isinstance(item, ShadowNo7Decision) else ShadowNo7Decision(**item)
        key = (parsed.symbol.strip().upper(), canonical_no7_timeframe(parsed.timeframe),
               parsed.bar_close_utc)
        if key[:2] != (canonical_symbol, canonical_tf):
            filtered_decisions += 1
            continue
        decisions_by_key[key].append(parsed)

    duplicate_evidence = sum(len(rows) - 1 for rows in evidence_by_key.values() if len(rows) > 1)
    duplicate_decisions = sum(len(rows) - 1 for rows in decisions_by_key.values() if len(rows) > 1)
    cost_money = (
        (costs.spread_points + 2 * costs.slippage_points_per_side)
        * spec.value_per_point_per_lot * costs.reference_lot
        + spec.commission_per_lot_round_turn * costs.reference_lot
    )
    cost_points = cost_money / (spec.value_per_point_per_lot * costs.reference_lot)

    unique_evidence = {key: rows[0] for key, rows in evidence_by_key.items() if len(rows) == 1}
    unique_decisions = {key: rows[0] for key, rows in decisions_by_key.items() if len(rows) == 1}
    quality_counts: dict[str, int] = defaultdict(int)
    for item in unique_evidence.values():
        quality_counts[item.quality] += 1
    comparison_keys = sorted(set(unique_evidence) & set(unique_decisions))
    agreement = disagreement = neutral_comparisons = 0
    score_gaps: list[float] = []
    for key in comparison_keys:
        external = _lens_direction(unique_evidence[key])
        internal = _direction(unique_decisions[key].action)
        if external == internal:
            agreement += 1
            if external == 0:
                neutral_comparisons += 1
        else:
            disagreement += 1
        no7_score = unique_decisions[key].score
        if no7_score is not None:
            signed_internal = no7_score * internal
            signed_external = float(unique_evidence[key].long_score - unique_evidence[key].short_score)
            score_gaps.append(abs(signed_external - signed_internal))

    outcome_lists: dict[int, dict[str, list[float]]] = {
        horizon: {"tradingview": [], "no7": []} for horizon in horizons
    }
    missing_bar = 0
    no_future_entry = 0
    incomplete_horizons = 0
    used_evidence = 0
    for key, external in unique_evidence.items():
        close_index = time_to_index.get(external.bar_close_utc)
        if close_index is None:
            missing_bar += 1
            continue
        used_evidence += 1
        entry_available_at = external.received_at_utc
        for system_name, decision, direction in (
            ("tradingview", external, _lens_direction(external)),
            ("no7", unique_decisions.get(key),
             _direction(unique_decisions[key].action) if key in unique_decisions else 0),
        ):
            if decision is None or direction == 0:
                continue
            available_at = (decision.available_at_utc if isinstance(decision, ShadowNo7Decision)
                            else entry_available_at)
            available_at = max(available_at, external.bar_close_utc)
            entry_index = bisect_left(times, available_at + interval, lo=close_index + 1)
            if entry_index >= len(times):
                no_future_entry += 1
                continue
            for horizon in horizons:
                exit_index = entry_index + horizon - 1
                if exit_index >= len(times):
                    incomplete_horizons += 1
                    continue
                price_move = direction * (closes[exit_index] - opens[entry_index])
                gross_money = spec.pnl_in_account_currency(price_move, costs.reference_lot)
                net_money = gross_money - cost_money
                net_points = net_money / (spec.value_per_point_per_lot * costs.reference_lot)
                outcome_lists[horizon][system_name].append(net_points)

    return {
        "kind": "tradingview_shadow_outcome_study",
        "mode": "offline_read_only",
        "symbol": canonical_symbol,
        "timeframe": canonical_tf,
        "bar_timestamp_semantics": "closed_bar_utc",
        "source": "tradingview_ai_agent_lens",
        "decision_influence": False,
        "execution_simulated": False,
        "comparison": {
            "exact_unique_matches": len(comparison_keys),
            "agreements": agreement,
            "disagreements": disagreement,
            "neutral_agreements": neutral_comparisons,
            "mean_absolute_signed_score_gap": (
                round(sum(score_gaps) / len(score_gaps), 4) if score_gaps else None
            ),
            "score_gap_samples": len(score_gaps),
        },
        "coverage": {
            "unique_evidence": len(unique_evidence),
            "evidence_quality_counts": dict(sorted(quality_counts.items())),
            "evidence_with_exact_closed_bar": used_evidence,
            "evidence_without_exact_bar": missing_bar,
            "duplicate_evidence_excluded": duplicate_evidence,
            "duplicate_no7_decisions_excluded": duplicate_decisions,
            "filtered_evidence_symbol_or_timeframe": filtered_evidence,
            "filtered_no7_symbol_or_timeframe": filtered_decisions,
            "no_future_entry_bar": no_future_entry,
            "incomplete_horizon_samples": incomplete_horizons,
        },
        "cost_assumptions": {
            "spread_points_round_trip": costs.spread_points,
            "slippage_points_per_side": costs.slippage_points_per_side,
            "commission_per_lot_round_turn_account_currency": spec.commission_per_lot_round_turn,
            "reference_lot": costs.reference_lot,
            "estimated_total_cost_points": round(cost_points, 6),
            "symbol_spec_source": spec.source,
            "currency_conversion_source": spec.rate_source,
            "swap_included": False,
            "spread_is_time_varying": False,
        },
        "horizons": {
            str(horizon): {
                "tradingview": _metric(outcome_lists[horizon]["tradingview"]),
                "no7": _metric(outcome_lists[horizon]["no7"]),
            }
            for horizon in horizons
        },
        "limitations": [
            "Predictive price-move study only; it does not simulate stop/target, margin, fills, or orders.",
            "Entry is the first later bar open after the evidence was available; no intrabar ticks are modeled.",
            "Costs are static assumptions; actual historical spread/slippage and swaps are not reconstructed.",
            "Results are advisory research and cannot affect a No7 signal, Risk Engine, Auto mode, or MT5.",
        ],
    }
