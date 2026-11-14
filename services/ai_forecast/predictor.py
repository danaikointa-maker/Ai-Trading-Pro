"""Forecast service: calibrated probabilities, P10-P90 bands, three scenarios.

If no model has passed its out-of-sample gate the service automatically falls
back to a climatological baseline and labels the output as UNVALIDATED, so the
dashboard never presents a model's opinion as a measured edge.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from services.ai_forecast.approval import APPROVAL_RULE_VERSION
from packages.indicators.pipeline import enrich
from packages.shared_schemas.models import (
    ForecastBundle,
    ForecastPathPoint,
    HorizonForecast,
    ModelInfo,
    Scenario,
    SymbolSpec,
)
from packages.shared_schemas.settings import Settings
from services.ai_forecast.features import FEATURE_COLUMNS, inference_vector
from services.ai_forecast.pathprob import PathProbabilityTable
from services.ai_forecast.registry import ModelRegistry
from services.ai_forecast.trainer import HorizonModel, TrainingResult


class ForecastPredictor:
    def __init__(self, settings: Settings, registry: ModelRegistry) -> None:
        self.settings = settings
        self.registry = registry
        self._generation = 0
        self.horizons = [int(h) for h in settings.ai.get("horizons_minutes", [5, 15, 30, 60, 240])]
        self.deadband = float(settings.ai.get("forecast", {}).get("deadband_atr", 0.25))
        self.fan_points = int(settings.ai.get("forecast", {}).get("fan_points", 24))
        self.models: dict[int, HorizonModel] = {}
        self.path_table: PathProbabilityTable | None = None
        self.version = "baseline-statistical"
        self.symbol = ""
        self.metrics: dict[str, Any] = {}
        self.approved = False
        self.trained_at: int = 0
        self.notes = "Statistical baseline only — no validated ML model loaded."
        self.loading = False
        self.train_progress: dict[str, Any] = {"state": "idle", "message": "", "pct": 0.0}
        self.load_latest()

    # ------------------------------------------------------------------ load
    def load_latest(self) -> bool:
        self._generation += 1
        # Revalidation failure must not retain previously approved model state.
        self.models = {}
        self.path_table = None
        self.version = "baseline-statistical"
        self.symbol = ""
        self.metrics = {}
        self.approved = False
        self.trained_at = 0
        self.notes = "Statistical baseline only — model absent or quarantined by provenance checks."
        # Newest run, not newest approval: an unapproved model is never used for
        # gating (see `approved` checks below), but its metrics are the truth about
        # the current training state and the dashboard should show that, not the
        # metrics of some earlier model that happened to be approved once.
        version = self.registry.latest()
        if not version:
            return False
        loaded = self.registry.load(version)
        if not loaded:
            return False
        payload, arrays = loaded
        self.install_payload(payload, arrays)
        return True

    def install_payload(self, payload: dict[str, Any], arrays: dict[str, np.ndarray]) -> None:
        self._generation += 1
        self.path_table = None
        self.models = {int(k): v for k, v in (payload.get("models") or {}).items()}
        self.version = payload.get("version", "unknown")
        self.symbol = payload.get("symbol", "")
        self.metrics = payload.get("metrics", {})
        self.trained_at = int(payload.get("trained_at", 0))
        self.notes = payload.get("notes", "")
        # An approval measured under an older rule is not evidence under this one.
        stored = bool(payload.get("approved", False))
        rule = int((self.metrics or {}).get("approval_rule") or 0)
        self.approved = stored and rule >= APPROVAL_RULE_VERSION
        if stored and not self.approved:
            self.notes = (f"{self.notes} | stored approval predates approval rule "
                          f"v{APPROVAL_RULE_VERSION} (model v{rule}); retrain to re-evaluate").strip(" |")
        if arrays:
            self.path_table = PathProbabilityTable.from_arrays(arrays, bar_minutes=5)
        for model in self.models.values():
            if not hasattr(model, "predict_proba"):
                continue

    def install(self, result: TrainingResult, symbol: str) -> None:
        self.registry.save(result, symbol)
        # Training is not a privileged installation path: consume registered bytes
        # and persisted approval exactly as on restart, not the in-memory result.
        self.load_latest()

    def status(self) -> ModelInfo | None:
        self.revalidate()
        if not self.models:
            return None
        return ModelInfo(
            version=self.version,
            created_at=self.trained_at,
            method="LightGBM multiclass + isotonic calibration + quantile bands",
            approved=self.approved,
            horizons=sorted(self.models),
            metrics=self.metrics,
            features=len(FEATURE_COLUMNS),
            samples=int(self.metrics.get("samples", 0)),
            notes=self.notes,
        )

    def revalidate(self) -> bool:
        """Demote loaded evidence when persisted authority changes; never reload it."""
        if not self.approved:
            return False
        generation = self._generation
        version = self.version
        self.approved = False
        try:
            valid = self.registry.inference_allowed(version)
        except Exception:  # unavailable authority cannot retain approval
            valid = False
        if generation != self._generation or version != self.version:
            return False
        if valid:
            self.approved = True
        else:
            self.models = {}
            self.path_table = None
            self.notes = "Model authority unavailable, revoked or quarantined; showing baseline."
        return self.approved

    # -------------------------------------------------------------- forecast
    def _baseline(self, m5: pd.DataFrame) -> dict[int, dict[str, float]]:
        """Climatological distribution of forward returns in ATR units."""
        close = m5["c"].to_numpy(float)
        atr = m5["atr"].to_numpy(float)
        out: dict[int, dict[str, float]] = {}
        for minutes in self.horizons:
            h = max(1, int(round(minutes / 5)))
            if len(close) <= h + 60:
                continue
            fwd = (close[h:] - close[:-h]) / atr[:-h]
            fwd = fwd[np.isfinite(fwd)]
            if len(fwd) < 50:
                continue
            out[minutes] = {
                "p_up": float((fwd > self.deadband).mean()),
                "p_down": float((fwd < -self.deadband).mean()),
                "q10": float(np.quantile(fwd, 0.10)),
                "q50": float(np.quantile(fwd, 0.50)),
                "q90": float(np.quantile(fwd, 0.90)),
                "samples": int(len(fwd)),
            }
        return out

    def forecast(self, m5: pd.DataFrame, spec: SymbolSpec, symbol: str) -> ForecastBundle:
        self.revalidate()
        if len(m5) < 260:
            raise ValueError("not enough M5 history for a forecast")
        X, _ = inference_vector(m5)
        price = float(m5["c"].iloc[-1])
        atr_now = float(m5["atr"].iloc[-1]) if np.isfinite(m5["atr"].iloc[-1]) else price * 0.001
        atr_points = atr_now / spec.point if spec.point else 0.0
        baseline = self._baseline(m5)

        rows: list[HorizonForecast] = []
        usable_models = 0
        for minutes in self.horizons:
            model = self.models.get(minutes)
            base = baseline.get(minutes, {"p_up": 0.33, "p_down": 0.33, "q10": -1.0, "q50": 0.0,
                                          "q90": 1.0, "samples": 0})
            calibrated = False
            method = "statistical-baseline"
            accuracy = None
            p_up, p_down, p_side = base["p_up"], base["p_down"], max(0.0, 1 - base["p_up"] - base["p_down"])
            q10, q50, q90 = base["q10"], base["q50"], base["q90"]
            cov_note = "Unconditional distribution — not a validated edge."
            sample = int(base.get("samples", 0))
            if self.approved and model is not None and getattr(model, "approved", False):
                try:
                    probs = model.predict_proba(X.reshape(1, -1))[0]
                    qs = model.predict_quantiles(X.reshape(1, -1))
                    p_down, p_side, p_up = float(probs[0]), float(probs[1]), float(probs[2])
                    q10, q50, q90 = float(qs[0.1][0]), float(qs[0.5][0]), float(qs[0.9][0])
                    # Quantile regressors are fitted independently and can cross;
                    # silently swapping them would misreport the band.
                    q10, q50, q90 = min(q10, q50), q50, max(q90, q50)
                    calibrated = True
                    method = "lightgbm+isotonic"
                    accuracy = model.metrics.get("directional_accuracy")
                    cov = model.metrics.get("coverage_p10_p90", 0.0)
                    cov_note = f"Out-of-sample P10-P90 coverage {cov * 100:.0f}% (target 80%)."
                    sample = int(model.metrics.get("samples_test", 0))
                    usable_models += 1
                except Exception as exc:  # noqa: BLE001 - never break the dashboard
                    cov_note = f"model inference failed ({exc}); showing baseline."
            elif model is not None:
                cov_note = "Model trained but NOT approved: out-of-sample gates failed. Showing baseline."

            p_up, p_down, p_side = _normalise_probs(p_up, p_down, p_side)
            q10, q50, q90 = min(q10, q50), q50, max(q90, q50)
            tp_points, sl_points = self._reference_levels(atr_points)
            p_path, n_path = self.p_tp_before_sl(tp_points, sl_points, minutes, p_up,
                                                 atr_points=atr_points, direction=1)
            if not self.approved or self.path_table is None or self.path_table.samples == 0:
                p_path = 0.5 * p_up + 0.25
            confidence = self._confidence(calibrated, model, p_up, p_side)

            rows.append(HorizonForecast(
                horizon_minutes=minutes,
                p_up=round(p_up, 4),
                p_down=round(p_down, 4),
                p_sideways=round(max(0.0, p_side), 4),
                calibrated=calibrated,
                method=method,
                expected_move_points=round(q50 * atr_points, 1),
                p10_points=round(q10 * atr_points, 1),
                p50_points=round(q50 * atr_points, 1),
                p90_points=round(q90 * atr_points, 1),
                p10_price=round(price + q10 * atr_now, spec.digits),
                p50_price=round(price + q50 * atr_now, spec.digits),
                p90_price=round(price + q90 * atr_now, spec.digits),
                p_tp_before_sl=round(p_path, 4),
                tp_points=round(tp_points, 0),
                sl_points=round(sl_points, 0),
                volatility_points=round(atr_now * np.sqrt(max(1, minutes / 5)) / spec.point, 1),
                confidence=round(confidence, 3),
                coverage_note=cov_note + (f" Path samples: {n_path}." if n_path else ""),
                invalidate_above=round(price + max(q90, 0.6) * atr_now, spec.digits),
                invalidate_below=round(price + min(q10, -0.6) * atr_now, spec.digits),
                directional_accuracy_oos=accuracy,
                sample_size=sample,
            ))

        if not rows:
            raise ValueError("no horizon could be computed")

        scenarios = self._scenarios(price, rows, spec, atr_now)
        confidence = float(np.mean([r.confidence for r in rows]))
        invalidation = [
            f"Forecast invalid if price closes above {rows[0].invalidate_above:.2f} or below "
            f"{rows[0].invalidate_below:.2f} within the next 5 minutes.",
            "Forecast invalid if ATR expands more than 50% inside the horizon (news shock).",
            "Forecast invalid if a new BOS/CHoCH forms against the projected direction.",
        ]
        narrative = self._narrative(symbol, rows, p_usable=usable_models)
        return ForecastBundle(
            symbol=symbol,
            generated_at=int(time.time()),
            price=price,
            model_version=self.version,
            model_approved=bool(self.approved and usable_models),
            method="lightgbm+isotonic" if usable_models else "statistical-baseline",
            confidence=round(confidence, 3),
            horizons=rows,
            scenarios=scenarios,
            invalidation=invalidation,
            narrative=narrative,
            regime="",
            metrics={
                "usable_horizons": usable_models,
                "total_horizons": len(rows),
                "atr_points": round(atr_points, 1),
                "deadband_atr": self.deadband,
                "trained_at": self.trained_at,
                "horizon_metrics": self.metrics.get("horizons", {}),
            },
        )

    # ------------------------------------------------------------- internals
    def _confidence(self, calibrated: bool, model: HorizonModel | None, p_up: float, p_side: float) -> float:
        if not calibrated or model is None:
            return 0.30 + 0.10 * abs(p_up - 0.5) * 2
        acc = float(model.metrics.get("directional_accuracy", 0.5))
        cov = float(model.metrics.get("coverage_p10_p90", 0.5))
        edge = abs(p_up - 0.5) * 2
        side_penalty = 1.0 - 0.35 * p_side
        return float(min(0.92, max(0.15, (0.35 + 0.5 * acc + 0.15 * min(cov, 1.0)) * (0.75 + 0.25 * edge) * side_penalty)))

    def _reference_levels(self, atr_points: float) -> tuple[float, float]:
        cfg = self.settings.risk_cfg().get("targets", {})
        adaptive = cfg.get("adaptive", {})
        base = adaptive.get("atr_multiplier", 2.2) * atr_points
        lo, hi = cfg.get("min_points", 500), cfg.get("max_points", 1000)
        tp = float(min(hi, max(lo, base)))
        sl = float(min(1200, max(150, atr_points * 1.0)))
        return tp, sl

    def p_tp_before_sl(self, tp_points: float, sl_points: float, horizon_minutes: int,
                       p_up: float, atr_points: float, direction: int = 1) -> tuple[float, int]:
        self.revalidate()
        if not self.approved or self.path_table is None or self.path_table.samples == 0 or atr_points <= 0:
            return 0.0, 0
        tp_atr = tp_points / atr_points
        sl_atr = sl_points / atr_points
        return self.path_table.p_tp_before_sl(horizon_minutes, tp_atr, sl_atr, p_up, direction)

    def _scenarios(self, price: float, rows: list[HorizonForecast], spec: SymbolSpec,
                   atr_now: float) -> list[Scenario]:
        primary = max(rows, key=lambda r: r.confidence)
        end_t = int(time.time()) + primary.horizon_minutes * 60
        last_t = int(time.time())

        def path(target: float) -> list[ForecastPathPoint]:
            """Fan for one scenario.

            The median drifts from spot to that scenario's own target, while the
            band is the horizon's P10-P90 width accumulated with sqrt(time). Each
            scenario therefore stays a *range*, never a single promised price.
            """
            half = abs(primary.p90_price - primary.p10_price) / 2.0
            points = []
            for i in range(self.fan_points + 1):
                frac = i / self.fan_points
                t = int(last_t + (end_t - last_t) * frac)
                scale = np.sqrt(frac)  # volatility accumulates with the square root of time
                centre = price + (target - price) * scale
                width = half * scale
                points.append(ForecastPathPoint(
                    t=t,
                    p10=round(min(centre - width, centre), spec.digits),
                    p50=round(centre, spec.digits),
                    p90=round(max(centre + width, centre), spec.digits)))
            return points

        return [
            Scenario(name="bull", probability=round(primary.p_up, 4),
                     target_price=round(primary.p90_price, spec.digits), path=path(primary.p90_price),
                     description="Upside scenario: price reaches the upper band and tests resistance."),
            Scenario(name="base", probability=round(primary.p_sideways, 4),
                     target_price=round(primary.p50_price, spec.digits), path=path(primary.p50_price),
                     description="Base scenario: mean-path drift with normal volatility."),
            Scenario(name="bear", probability=round(primary.p_down, 4),
                     target_price=round(primary.p10_price, spec.digits), path=path(primary.p10_price),
                     description="Downside scenario: price reaches the lower band and tests support."),
        ]

    def _narrative(self, symbol: str, rows: list[HorizonForecast], p_usable: int) -> str:
        if not rows:
            return ""
        r = rows[0]
        direction = "ขึ้น" if r.p_up > max(r.p_down, r.p_sideways) else (
            "ลง" if r.p_down > max(r.p_up, r.p_sideways) else " sideways")
        tag = "โมเดลผ่านการทดสอบ out-of-sample" if p_usable else "ยังไม่มีโมเดลที่ผ่านเกณฑ์ — ใช้ค่าฐานสถิติ"
        return (
            f"{symbol}  horizon {r.horizon_minutes} นาที: โอกาส{direction} "
            f"P(up)={r.p_up:.0%} / P(down)={r.p_down:.0%} / P(sideways)={r.p_sideways:.0%}. "
            f"ช่วงราคาคาดการณ์ P10–P90 = {r.p10_price:.2f}–{r.p90_price:.2f} "
            f"({r.p10_points:+.0f}…{r.p90_points:+.0f} points). "
            f"โอกาสถึง TP ก่อน SL ≈ {r.p_tp_before_sl:.0%} ที่ TP {r.tp_points:.0f} / SL {r.sl_points:.0f} points. "
            f"({tag})"
        )


def _normalise_probs(p_up: float, p_down: float, p_side: float) -> tuple[float, float, float]:
    """Clip to [0,1] and rescale so the three scenarios sum to exactly 1."""
    vals = [max(0.0, float(p_up)), max(0.0, float(p_down)), max(0.0, float(p_side))]
    total = sum(vals)
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    if abs(total - 1.0) > 1e-6:
        vals = [v / total for v in vals]
        # give the rounding residue to the largest bucket so the sum is exact
        idx = max(range(3), key=lambda i: vals[i])
        vals[idx] = max(0.0, 1.0 - sum(v for i, v in enumerate(vals) if i != idx))
    return vals[0], vals[1], vals[2]


__all__ = ["ForecastPredictor", "enrich", "pd"]
