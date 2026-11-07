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


def split_folds(n: int, folds: int) -> list[tuple[int, int]]:
    """Split `n` chronological rows into `folds` contiguous blocks.

    Boundaries are computed from the index, never from random sampling: the whole
    point of the check is that later data is scored by a model that never saw it.
    """
    if n <= 0:
        return []
    folds = max(1, min(int(folds), n))
    edges = [int(n * i / folds) for i in range(folds + 1)]
    return [(edges[i], edges[i + 1]) for i in range(folds) if edges[i + 1] > edges[i]]


def decide_approval(folds: list[dict[str, Any]], min_dir_accuracy: float,
                    min_brier_improvement: float, min_pass_rate: float = 0.75) -> tuple[bool, dict[str, Any]]:
    """Approve only if the edge shows up in *most* out-of-sample blocks.

    A single split can clear both gates by luck: one good month approves a model
    that is flat the rest of the year. Requiring a majority of chronological
    blocks — plus the median block — to clear the same bar is stricter than the
    old rule, never looser.
    """
    if not folds:
        return False, {"folds_used": 0, "fold_pass_rate": 0.0,
                       "fold_directional_median": 0.0, "fold_brier_improvement_median": 0.0}

    passing = [f for f in folds if f.get("pass")]
    rate = len(passing) / len(folds)
    dirs = sorted(float(f.get("directional_accuracy", 0.0)) for f in folds)
    briers = sorted(float(f.get("brier_improvement", 0.0)) for f in folds)
    median_dir = dirs[len(dirs) // 2] if len(dirs) % 2 else (dirs[len(dirs) // 2 - 1] + dirs[len(dirs) // 2]) / 2
    median_brier = briers[len(briers) // 2] if len(briers) % 2 else (briers[len(briers) // 2 - 1] + briers[len(briers) // 2]) / 2

    approved = bool(rate >= min_pass_rate and median_dir >= min_dir_accuracy
                    and median_brier >= min_brier_improvement)
    return approved, {
        "folds_used": len(folds),
        "fold_pass_rate": round(rate, 3),
        "fold_directional_median": round(median_dir, 4),
        "fold_brier_improvement_median": round(median_brier, 4),
        "fold_directional_min": round(dirs[0], 4),
        "fold_brier_improvement_min": round(briers[0], 4),
    }


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
    # Class-level mirrors of the config gates, so `_fold_row` can stay static.
    MIN_DIR = 0.52
    MIN_BRIER = 0.02

    def __init__(self, settings: Settings) -> None:
        cfg = settings.ai.get("training", {})
        self.max_rows = int(cfg.get("max_rows", 26000))
        self.train_fraction = float(cfg.get("train_fraction", 0.70))
        self.calib_fraction = float(cfg.get("calibration_fraction", 0.15))
        self.min_dir_accuracy = float(cfg.get("min_directional_accuracy", 0.52))
        self.min_brier_improvement = float(cfg.get("min_brier_improvement", 0.02))
        ForecastTrainer.MIN_DIR = self.min_dir_accuracy
        ForecastTrainer.MIN_BRIER = self.min_brier_improvement
        self.quantiles = [float(q) for q in cfg.get("quantiles", [0.1, 0.5, 0.9])]
        self.horizons = [int(h) for h in settings.ai.get("horizons_minutes", [5, 15, 30, 60, 240])]
        self.validation_folds = int(cfg.get("validation_folds", 4))
        self.min_fold_pass_rate = float(cfg.get("min_fold_pass_rate", 0.75))
        # Refit-per-fold walk-forward: the honest version of the fold check, at the
        # cost of one extra classifier fit per fold. 0 disables it and falls back
        # to scoring slices of the single fitted model.
        self.walk_forward_folds = int(cfg.get("walk_forward_folds", 3))
        self.walk_forward_min_train_rows = int(cfg.get("walk_forward_min_train_rows", 900))
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

    def _new_classifier(self) -> Any:
        """One definition of the classifier, so walk-forward folds cannot drift."""
        return LGBMClassifier(
            objective="multiclass", num_class=3, n_estimators=180, learning_rate=0.06,
            num_leaves=31, min_child_samples=40, subsample=0.85, colsample_bytree=0.85,
            reg_lambda=1.0, class_weight="balanced", random_state=7, n_jobs=2, verbose=-1,
        )

    def _walk_forward_scores(self, data: pd.DataFrame, folds: int) -> list[dict[str, Any]]:
        """Refit on an expanding window, then score the block that follows it.

        Unlike slicing the predictions of one model, every fold here is produced by
        a model that never saw the rows it is scored on. Quantile regressors are
        skipped: the approval gate reads classification metrics, so a fold costs a
        single fit.
        """
        out: list[dict[str, Any]] = []
        # folds+1 blocks: the first one is the opening training window, the rest are
        # the folds that actually get scored.
        for lo, hi in split_folds(len(data), folds + 1):
            train_end = int(lo * (1.0 - self.calib_fraction))
            if train_end < self.walk_forward_min_train_rows:
                continue
            block = data.iloc[lo:hi]
            if len(block) < 50:
                continue
            hist = data.iloc[:train_end]
            ytr = hist["y"].to_numpy(float)
            yte = block["y"].to_numpy(float)
            if len(np.unique(ytr)) < 2 or len(np.unique(yte)) < 1:
                continue

            clf = self._new_classifier()
            clf.fit(hist[FEATURE_COLUMNS].to_numpy(float), ytr)
            raw = clf.predict_proba(block[FEATURE_COLUMNS].to_numpy(float))
            classes = list(clf.classes_)
            probs = np.zeros((len(yte), len(CLASSES)))
            for j, cls in enumerate(CLASSES):
                if cls in classes:
                    probs[:, j] = raw[:, classes.index(cls)]

            truth_idx = np.array([int(np.where(CLASSES == v)[0][0]) for v in yte])
            onehot = np.zeros_like(probs)
            onehot[np.arange(len(truth_idx)), truth_idx] = 1.0
            priors = np.array([(ytr == c).mean() for c in CLASSES], dtype=float)
            priors = priors / max(priors.sum(), 1e-9)

            pred = probs.argmax(axis=1)
            nonzero = truth_idx != 1
            dir_acc = float((pred[nonzero] == truth_idx[nonzero]).mean()) if nonzero.any() else 0.0
            brier = float(((probs - onehot) ** 2).sum(axis=1).mean())
            baseline = float(((np.tile(priors, (len(yte), 1)) - onehot) ** 2).sum(axis=1).mean())
            out.append(self._fold_row(len(yte), train_end, dir_acc, baseline - brier))
        return out

    @staticmethod
    def _fold_row(n: int, samples_train: int, dir_acc: float, improvement: float) -> dict[str, Any]:
        return {
            "n": int(n),
            "samples_train": int(samples_train),
            "directional_accuracy": round(float(dir_acc), 4),
            "brier_improvement": round(float(improvement), 4),
            "retrained": True,
            "pass": bool(dir_acc >= ForecastTrainer.MIN_DIR and improvement >= ForecastTrainer.MIN_BRIER),
        }

    def _fold_scores(self, probs: np.ndarray, truth_idx: np.ndarray, onehot: np.ndarray,
                     priors: np.ndarray) -> list[dict[str, Any]]:
        """Score the out-of-sample block in chronological folds."""
        n = len(truth_idx)
        folds = min(max(1, self.validation_folds), max(1, n // 100))
        out: list[dict[str, Any]] = []
        for lo, hi in split_folds(n, folds):
            p, t, oh = probs[lo:hi], truth_idx[lo:hi], onehot[lo:hi]
            pred = p.argmax(axis=1)
            nonzero = t != 1
            dir_acc = float((pred[nonzero] == t[nonzero]).mean()) if nonzero.any() else 0.0
            brier = float(((p - oh) ** 2).sum(axis=1).mean())
            base = float(((np.tile(priors, (len(t), 1)) - oh) ** 2).sum(axis=1).mean())
            improvement = base - brier
            out.append({
                "n": int(len(t)),
                "directional_accuracy": round(dir_acc, 4),
                "brier_improvement": round(improvement, 4),
                "retrained": False,
                "pass": bool(dir_acc >= self.min_dir_accuracy
                            and improvement >= self.min_brier_improvement),
            })
        return out

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

            # A single split can clear both gates by luck, which is why approval
            # kept flipping between runs. Score the same out-of-sample block in
            # chronological folds and demand the edge in most of them.
            # Prefer real walk-forward (refit per fold); fall back to scoring slices
            # of the single fitted model when there is not enough history.
            wf = self._walk_forward_scores(data, self.walk_forward_folds) if self.walk_forward_folds >= 2 else []
            if len(wf) >= 2:
                folds, validation_method = wf, "walk-forward (refit per fold)"
            else:
                folds = self._fold_scores(probs, truth_idx, onehot, prior_model.priors)
                validation_method = "block slices of one fitted model (not refit)"
            fold_ok, fold_summary = decide_approval(
                folds, self.min_dir_accuracy, self.min_brier_improvement, self.min_fold_pass_rate)
            approved = bool(fold_ok and directional >= self.min_dir_accuracy
                            and (baseline_brier - brier) >= self.min_brier_improvement)
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
                "validation_folds": folds,
                "validation_method": validation_method,
                "approved": approved,
                **fold_summary,
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
        methods = sorted({h.get("validation_method", "") for h in overall["horizons"].values() if h})
        methods = [m for m in methods if m]
        if methods:
            overall["validation"] = (
                "chronological folds; " + "; ".join(methods)
                + " — each fold is scored on data the scoring model never saw"
            )
        else:
            # No horizon survived the data check. Saying "no folds" is the honest
            # answer; an empty method list used to render as "chronological folds;  —".
            overall["validation"] = (
                "no horizon was trained — not enough history for the requested horizons; "
                "nothing can be approved"
            )
        overall["walk_forward_folds"] = self.walk_forward_folds
        overall["walk_forward_min_train_rows"] = self.walk_forward_min_train_rows
        overall["validation_folds"] = self.validation_folds
        overall["min_fold_pass_rate"] = self.min_fold_pass_rate
        notes = (
            f"{len(models)}/{len(self.horizons)} horizons trained on {overall['samples']:,} samples; "
            f"{overall['approved_horizons']} passed out-of-sample gates "
            f"(directional accuracy >= {self.min_dir_accuracy:.0%}, Brier improvement >= {self.min_brier_improvement}, "
            f"in at least {self.min_fold_pass_rate:.0%} of {self.validation_folds} chronological folds)."
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
