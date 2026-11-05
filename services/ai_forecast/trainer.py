"""Walk-forward training for the forecast models.

Nothing is promoted to live use automatically: each horizon is validated on a
time-ordered out-of-sample slice against a naive "climatological" baseline, and
the model is only marked approved when it beats that baseline on Brier score by
the configured margin. Otherwise the dashboard shows the baseline forecast and
says so.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.isotonic import IsotonicRegression

from packages.indicators.pipeline import enrich
from packages.shared_schemas.settings import Settings
from services.ai_forecast.features import FEATURE_COLUMNS, build_features, build_targets
from services.ai_forecast.pathprob import PathProbabilityTable

CLASSES = np.array([-1.0, 0.0, 1.0])  # down, sideways, up


@dataclass
class HorizonModel:
    horizon_minutes: int
    horizon_bars: int
    classifier: Any
    calibrators: list[Any]
    quantiles: dict[float, Any]
    metrics: dict[str, Any] = field(default_factory=dict)
    priors: np.ndarray = field(default_factory=lambda: np.array([1 / 3, 1 / 3, 1 / 3]))
    approved: bool = False

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raw = self.classifier.predict_proba(X)
        # Align with CLASSES order (LightGBM sorts the labels it saw).
        classes = list(getattr(self.classifier, "classes_", CLASSES))
        ordered = np.zeros((raw.shape[0], 3))
        for j, cls in enumerate(classes):
            idx = int(np.where(CLASSES == float(cls))[0][0])
            cal = self.calibrators[idx]
            ordered[:, idx] = cal.predict(raw[:, j])
        totals = ordered.sum(axis=1, keepdims=True)
        totals[totals <= 0] = 1.0
        return ordered / totals

    def predict_quantiles(self, X: np.ndarray) -> dict[float, np.ndarray]:
        out = {}
        for q, model in self.quantiles.items():
            out[q] = model.predict(X)
        # enforce monotonicity
        keys = sorted(out)
        stacked = np.vstack([out[k] for k in keys])
        stacked = np.maximum.accumulate(stacked, axis=0)
        return {k: stacked[i] for i, k in enumerate(keys)}


@dataclass
class TrainingResult:
    version: str
    models: dict[int, HorizonModel]
    path_table: PathProbabilityTable
    metrics: dict[str, Any]
    approved: bool
    samples: int
    notes: str
    feature_columns: list[str]
    trained_at: int


class ForecastTrainer:
    def __init__(self, settings: Settings) -> None:
        cfg = settings.ai.get("training", {})
        self.max_rows = int(cfg.get("max_rows", 26000))
        self.train_fraction = float(cfg.get("train_fraction", 0.70))
        self.calib_fraction = float(cfg.get("calibration_fraction", 0.15))
        self.min_dir_accuracy = float(cfg.get("min_directional_accuracy", 0.52))
        self.min_brier_improvement = float(cfg.get("min_brier_improvement", 0.02))
        self.quantiles = [float(q) for q in cfg.get("quantiles", [0.1, 0.5, 0.9])]
        self.horizons = [int(h) for h in settings.ai.get("horizons_minutes", [5, 15, 30, 60, 240])]
        self.deadband = float(settings.ai.get("forecast", {}).get("deadband_atr", 0.25))
        self.bar_minutes = 5

    # ------------------------------------------------------------------ data
    def prepare(self, df_m1: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """M1 -> enriched M5 frame + feature frame (no look-ahead)."""
        from services.market_data.simulator import resample

        m5 = resample(df_m1, "M5")
        m5 = enrich(m5)
        feats = build_features(m5)
        return m5, feats

    # ----------------------------------------------------------------- train
    def train(self, df_m1: pd.DataFrame, version: str,
              progress: Callable[[str, float], None] | None = None) -> TrainingResult:
        t0 = time.time()

        def report(msg: str, pct: float) -> None:
            if progress:
                progress(msg, pct)

        report("building features", 0.05)
        m5, feats = self.prepare(df_m1)
        horizon_bars = {h: max(1, int(round(h / self.bar_minutes))) for h in self.horizons}
        report("building path-probability table", 0.12)
        atr = m5["atr"].to_numpy(float)
        path_table = PathProbabilityTable.build(m5, atr, sorted(horizon_bars.values()),
                                                bar_minutes=self.bar_minutes)
        models: dict[int, HorizonModel] = {}
        overall: dict[str, Any] = {"horizons": {}, "samples": 0, "approved_horizons": 0}
        n_h = len(self.horizons)
        for i, minutes in enumerate(self.horizons):
            report(f"training {minutes}m horizon", 0.15 + 0.8 * i / n_h)
            hb = horizon_bars[minutes]
            targets = build_targets(m5, feats, hb, self.deadband)
            data = feats[FEATURE_COLUMNS].copy()
            data["y"] = targets["label"].to_numpy()
            data["fwd_atr"] = targets["fwd_atr"].to_numpy()
            data = data.replace([np.inf, -np.inf], np.nan).dropna()
            if len(data) > self.max_rows:
                data = data.iloc[-self.max_rows:]
            if len(data) < 400:
                report(f"skipping {minutes}m (only {len(data)} rows)", 0.15 + 0.8 * (i + 1) / n_h)
                continue
            n = len(data)
            n_train = int(n * self.train_fraction)
            n_calib = int(n * self.calib_fraction)
            train = data.iloc[:n_train]
            calib = data.iloc[n_train:n_train + n_calib]
            test = data.iloc[n_train + n_calib:]
            Xtr, ytr = train[FEATURE_COLUMNS].to_numpy(float), train["y"].to_numpy(float)
            Xcal, ycal = calib[FEATURE_COLUMNS].to_numpy(float), calib["y"].to_numpy(float)
            Xte, yte = test[FEATURE_COLUMNS].to_numpy(float), test["y"].to_numpy(float)
            if len(test) < 100:
                continue

            clf = LGBMClassifier(
                objective="multiclass", num_class=3, n_estimators=180, learning_rate=0.06,
                num_leaves=31, min_child_samples=40, subsample=0.85, colsample_bytree=0.85,
                reg_lambda=1.0, class_weight="balanced", random_state=7, n_jobs=2, verbose=-1,
            )
            clf.fit(Xtr, ytr)

            # --- isotonic calibration per class on the held-out calibration slice
            calibrators: list[Any] = []
            raw_cal = clf.predict_proba(Xcal)
            classes = list(clf.classes_)
            for cls in CLASSES:
                idx = classes.index(cls) if cls in classes else None
                iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
                if idx is None:
                    iso.fit(np.zeros_like(ycal), (ycal == cls).astype(float))
                else:
                    iso.fit(raw_cal[:, idx], (ycal == cls).astype(float))
                calibrators.append(iso)

            # --- quantile regressors for the price band (targets in ATR units)
            quantiles: dict[float, Any] = {}
            for q in (0.1, 0.5, 0.9):
                qr = LGBMRegressor(
                    objective="quantile", alpha=q, n_estimators=140, learning_rate=0.06,
                    num_leaves=31, min_child_samples=40, subsample=0.85, colsample_bytree=0.85,
                    reg_lambda=1.0, random_state=7 + int(q * 100), n_jobs=2, verbose=-1,
                )
                qr.fit(pd.concat([train, calib])[FEATURE_COLUMNS].to_numpy(float),
                       pd.concat([train, calib])["fwd_atr"].to_numpy(float))
                quantiles[q] = qr

            prior_model = HorizonModel(minutes, hb, clf, calibrators, quantiles)
            prior_model.priors = np.array([(ytr == c).mean() for c in CLASSES])
            prior_model.priors = prior_model.priors / max(prior_model.priors.sum(), 1e-9)

            # --- out-of-sample evaluation
            probs = prior_model.predict_proba(Xte)
            pred_idx = probs.argmax(axis=1)
            truth_idx = np.array([int(np.where(CLASSES == v)[0][0]) for v in yte])
            accuracy = float((pred_idx == truth_idx).mean())
            nonzero = truth_idx != 1
            directional = float((pred_idx[nonzero] == truth_idx[nonzero]).mean()) if nonzero.any() else 0.0
            onehot = np.zeros_like(probs)
            onehot[np.arange(len(truth_idx)), truth_idx] = 1.0
            brier = float(((probs - onehot) ** 2).sum(axis=1).mean())
            baseline_probs = np.tile(prior_model.priors, (len(yte), 1))
            baseline_brier = float(((baseline_probs - onehot) ** 2).sum(axis=1).mean())
            baseline_acc = float((baseline_probs.argmax(axis=1) == truth_idx).mean())
            logloss = float(-np.log(np.clip(probs[np.arange(len(truth_idx)), truth_idx], 1e-9, 1)).mean())

            qpred = prior_model.predict_quantiles(Xte)
            band_lo, band_hi = qpred[0.1], qpred[0.9]
            truth_fwd = test["fwd_atr"].to_numpy(float)
            coverage = float(((truth_fwd >= band_lo) & (truth_fwd <= band_hi)).mean())
            band_width = float(np.median(band_hi - band_lo))

            approved = bool(directional >= self.min_dir_accuracy and
                            (baseline_brier - brier) >= self.min_brier_improvement)
            prior_model.approved = approved
            prior_model.metrics = {
                "accuracy_3class": round(accuracy, 4),
                "baseline_accuracy": round(baseline_acc, 4),
                "directional_accuracy": round(directional, 4),
                "brier": round(brier, 4),
                "baseline_brier": round(baseline_brier, 4),
                "brier_improvement": round(baseline_brier - brier, 4),
                "log_loss": round(logloss, 4),
                "coverage_p10_p90": round(coverage, 4),
                "median_band_width_atr": round(band_width, 3),
                "samples_train": int(len(train)),
                "samples_test": int(len(test)),
                "approved": approved,
            }
            models[minutes] = prior_model
            overall["horizons"][str(minutes)] = prior_model.metrics
            overall["samples"] += int(len(data))
            overall["approved_horizons"] += int(approved)

        approved_any = overall["approved_horizons"] >= max(1, len(self.horizons) // 2)
        overall["approved"] = approved_any
        overall["train_seconds"] = round(time.time() - t0, 1)
        overall["deadband_atr"] = self.deadband
        overall["method"] = "LightGBM multiclass + isotonic calibration + quantile regression"
        notes = (
            f"{len(models)}/{len(self.horizons)} horizons trained on {overall['samples']:,} samples; "
            f"{overall['approved_horizons']} passed out-of-sample gates "
            f"(directional accuracy >= {self.min_dir_accuracy:.0%}, Brier improvement >= {self.min_brier_improvement})."
        )
        report("done", 1.0)
        return TrainingResult(
            version=version, models=models, path_table=path_table, metrics=overall,
            approved=approved_any, samples=int(overall["samples"]), notes=notes,
            feature_columns=list(FEATURE_COLUMNS), trained_at=int(time.time()),
        )


def baseline_forecast(feats: pd.DataFrame, targets_by_h: dict[int, pd.DataFrame],
                      deadband: float) -> dict[str, Any]:
    """Climatological fallback used when no model has been approved."""
    out: dict[str, Any] = {}
    for minutes, targets in targets_by_h.items():
        fwd = targets["fwd_atr"].dropna().to_numpy(float)
        if len(fwd) < 50:
            continue
        p_up = float((fwd > deadband).mean())
        p_down = float((fwd < -deadband).mean())
        p_side = float(max(0.0, 1.0 - p_up - p_down))
        out[str(minutes)] = {
            "p_up": p_up, "p_down": p_down, "p_sideways": p_side,
            "q10": float(np.quantile(fwd, 0.1)), "q50": float(np.quantile(fwd, 0.5)),
            "q90": float(np.quantile(fwd, 0.9)), "samples": int(len(fwd)),
            "coverage_p10_p90": 0.8,
        }
    return out
