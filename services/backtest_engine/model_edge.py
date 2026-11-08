"""Walk-forward model edge for the backtest.

Until now the backtest scored the rule core: the forecast it fed to the strategy was
a deterministic proxy, so the report measured "structure + risk management" and said
so in its assumptions. This module lets the backtest use the *trained* direction
model instead, without letting it see its own future.

How the look-ahead is kept out
------------------------------
The decision range is cut into segments. A model used inside segment *k* is fitted
on rows that end **one full label horizon before the segment starts**, because the
label at row *j* reads the close ``hb`` bars later: training on row ``start - 1``
would hand the model the answer to the first bars it is asked about. So:

    train rows = [0, start_k - hb)        features are backward-looking only
    predict    = [start_k, end_k)         the model never saw any of these rows

Missing features are imputed with the median **of that model's training rows**, not
of the whole frame — the frame median is a summary of the future.

Approval is earned the same way production earns it: a segment's model is marked
``calibrated`` only when the previous segments' predictions, whose labels had
already completed by the time the segment began, beat the configured directional
accuracy. The first segment therefore always runs unapproved, exactly like a freshly
trained model that has not been validated yet.

Accuracies in :meth:`summary` are hindsight — they are computed after the run for
the report only, and never feed a decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from packages.shared_schemas.settings import Settings
from services.ai_forecast.features import FEATURE_COLUMNS, build_features, build_targets

# Below this a fit is noise fitted to noise; the segment stays on the rule proxy
# and the report says how many decisions that cost.
MIN_TRAIN_ROWS = 300


@dataclass
class Segment:
    index: int
    start_bar: int
    end_bar: int
    train_rows: int = 0
    trained: bool = False
    reason: str = ""
    approved: bool = False          # decided before the segment ran, from past folds
    decisions: int = 0              # decision points this segment answered
    model: Any = None
    median: np.ndarray | None = None


@dataclass
class Prediction:
    p_up: float
    p_side: float
    p_down: float
    approved: bool
    segment: int


@dataclass
class WalkForwardEdge:
    """Fits one model per segment on an expanding, purged window."""

    settings: Settings
    horizon_minutes: int = 30
    segments: int = 4
    min_train_rows: int = MIN_TRAIN_ROWS

    bar_minutes: int = field(default=5, init=False)
    horizon_bars: int = field(default=6, init=False)
    _segments: list[Segment] = field(default_factory=list, init=False)
    _features: pd.DataFrame | None = field(default=None, init=False)
    _labels: np.ndarray | None = field(default=None, init=False)
    _rows: list[dict[str, Any]] = field(default_factory=list, init=False)
    _fit_errors: list[str] = field(default_factory=list, init=False)
    prepared: bool = field(default=False, init=False)
    unavailable: str = field(default="", init=False)

    # --------------------------------------------------------------- preparation
    def prepare(self, m5: pd.DataFrame, first_bar: int) -> None:
        """Build features/labels once and lay out the segments over [first_bar, n)."""
        n = len(m5)
        self.horizon_bars = max(1, int(round(self.horizon_minutes / self.bar_minutes)))
        deadband = float(self.settings.ai.get("forecast", {}).get("deadband_atr", 0.25))
        try:
            feats = build_features(m5)
            targets = build_targets(m5, feats, self.horizon_bars, deadband)
        except Exception as exc:  # noqa: BLE001 - a broken feature frame must not kill the run
            self.unavailable = f"feature build failed: {type(exc).__name__}: {exc}"
            self.prepared = True
            return
        self._features = feats
        self._labels = targets["label"].to_numpy(float)

        bounds = np.linspace(first_bar, n, self.segments + 1).astype(int)
        self._segments = [Segment(index=k + 1, start_bar=int(bounds[k]), end_bar=int(bounds[k + 1]))
                          for k in range(self.segments) if bounds[k + 1] > bounds[k]]
        self.prepared = True

    # ------------------------------------------------------------------ training
    def _training_slice(self, start_bar: int) -> np.ndarray:
        """Row indices usable to train a model that will predict from `start_bar`.

        The purge is the whole label horizon: row j's label reads bar j+hb, so j is
        only safe when j + hb < start_bar.
        """
        assert self._features is not None and self._labels is not None
        cutoff = start_bar - self.horizon_bars
        if cutoff <= 0:
            return np.empty(0, dtype=int)
        X = self._features[FEATURE_COLUMNS].to_numpy(float)[:cutoff]
        y = self._labels[:cutoff]
        ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
        return np.flatnonzero(ok)

    def _fit(self, seg: Segment) -> None:
        from services.ai_forecast.trainer import ForecastTrainer

        rows = self._training_slice(seg.start_bar)
        seg.train_rows = int(rows.size)
        if seg.train_rows < self.min_train_rows:
            seg.reason = (f"only {seg.train_rows} clean training rows before bar "
                          f"{seg.start_bar} (need {self.min_train_rows})")
            return
        assert self._features is not None and self._labels is not None
        X = self._features[FEATURE_COLUMNS].to_numpy(float)[rows]
        y = self._labels[rows]
        if len(np.unique(y)) < 2:
            seg.reason = "training window contains a single class"
            return
        try:
            # Same classifier definition production trains with, so this measures
            # the model the product ships rather than a backtest-only stand-in.
            model = ForecastTrainer(self.settings)._new_classifier()
            model.fit(X, y)
        except Exception as exc:  # noqa: BLE001 - a failed fit degrades to the proxy
            seg.reason = f"fit failed: {type(exc).__name__}: {exc}"
            self._fit_errors.append(seg.reason)
            return
        seg.model = model
        seg.median = np.nanmedian(X, axis=0)
        seg.trained = True
        seg.reason = f"fitted on {seg.train_rows} rows before bar {seg.start_bar}"

    # ---------------------------------------------------------------- prediction
    def _segment_for(self, i: int) -> Segment | None:
        for seg in self._segments:
            if seg.start_bar <= i < seg.end_bar:
                return seg
        return None

    def _known_accuracy(self, before_bar: int) -> tuple[float, int]:
        """Directional accuracy of predictions whose labels completed before `before_bar`."""
        assert self._labels is not None
        hits = total = 0
        for row in self._rows:
            if row["bar"] + self.horizon_bars > before_bar:
                continue
            truth = self._labels[row["bar"]]
            if not np.isfinite(truth) or truth == 0.0:
                continue  # sideways: direction was not the question
            total += 1
            hits += int(np.sign(row["p_up"] - row["p_down"]) == np.sign(truth))
        return (hits / total if total else 0.0), total

    def predict(self, i: int) -> Prediction | None:
        """Model view of bar `i`, or None when this segment has no usable model."""
        if not self.prepared or self.unavailable or self._features is None:
            return None
        seg = self._segment_for(i)
        if seg is None:
            return None
        if seg.model is None and not seg.reason:
            self._fit(seg)
            # Approval is earned on folds that already finished, never on this one.
            min_acc = float(self.settings.ai.get("training", {}).get("min_directional_accuracy", 0.52))
            acc, scored = self._known_accuracy(seg.start_bar)
            seg.approved = bool(scored >= 30 and acc >= min_acc)
        if not seg.trained:
            return None
        x = self._features[FEATURE_COLUMNS].to_numpy(float)[i]
        if not np.isfinite(x).all():
            if seg.median is None or not np.isfinite(seg.median).all():
                return None
            x = np.where(np.isfinite(x), x, seg.median)
        proba = seg.model.predict_proba(x.reshape(1, -1))[0]
        classes = list(getattr(seg.model, "classes_", [-1.0, 0.0, 1.0]))
        p = {float(c): float(proba[j]) for j, c in enumerate(classes)}
        p_down, p_side, p_up = p.get(-1.0, 0.0), p.get(0.0, 0.0), p.get(1.0, 0.0)
        total = p_down + p_side + p_up
        if total <= 0:
            return None
        seg.decisions += 1
        return Prediction(p_up=p_up / total, p_side=p_side / total, p_down=p_down / total,
                          approved=seg.approved, segment=seg.index)

    def observe(self, bar: int, p_up: float, p_down: float, source: str,
                proxy_p_up: float, proxy_p_down: float) -> None:
        """Record what was predicted at a decision point, for the report's scorecard."""
        self._rows.append({"bar": bar, "p_up": float(p_up), "p_down": float(p_down),
                           "source": source, "proxy_p_up": float(proxy_p_up),
                           "proxy_p_down": float(proxy_p_down)})

    # -------------------------------------------------------------------- report
    def _accuracy(self, rows: list[dict[str, Any]], key_up: str, key_down: str) -> tuple[float, int]:
        assert self._labels is not None
        hits = total = 0
        for row in rows:
            truth = self._labels[row["bar"]]
            if not np.isfinite(truth) or truth == 0.0:
                continue
            total += 1
            hits += int(np.sign(row[key_up] - row[key_down]) == np.sign(truth))
        return (round(hits / total, 4) if total else 0.0), total

    def summary(self) -> dict[str, Any]:
        """Hindsight scorecard: model vs the rule proxy on the very same bars."""
        if self.unavailable:
            return {"available": False, "reason": self.unavailable}
        from_model = [r for r in self._rows if r["source"] == "model"]
        model_acc, scored = self._accuracy(from_model, "p_up", "p_down")
        proxy_acc, _ = self._accuracy(from_model, "proxy_p_up", "proxy_p_down")
        all_proxy_acc, all_scored = self._accuracy(self._rows, "proxy_p_up", "proxy_p_down")
        segs = []
        for seg in self._segments:
            rows = [r for r in from_model if seg.start_bar <= r["bar"] < seg.end_bar]
            acc, n = self._accuracy(rows, "p_up", "p_down")
            pacc, _ = self._accuracy(rows, "proxy_p_up", "proxy_p_down")
            note = seg.reason or ("no decision point landed in this segment"
                                  if not seg.decisions else "")
            segs.append({
                "segment": seg.index, "bars": [seg.start_bar, seg.end_bar],
                "train_rows": seg.train_rows, "trained": seg.trained,
                "approved_when_it_ran": seg.approved, "decisions": seg.decisions,
                "scored_decisions": n, "model_dir_accuracy": acc, "proxy_dir_accuracy": pacc,
                "note": note,
            })
        return {
            "available": True,
            "horizon_minutes": self.horizon_minutes,
            "label_purge_bars": self.horizon_bars,
            "segments": segs,
            "decisions_from_model": len(from_model),
            "decisions_from_proxy": len(self._rows) - len(from_model),
            "scored_decisions": scored,
            "model_dir_accuracy": model_acc,
            "proxy_dir_accuracy_same_bars": proxy_acc,
            "proxy_dir_accuracy_all_bars": all_proxy_acc,
            "proxy_scored_decisions": all_scored,
            "edge_vs_proxy": round(model_acc - proxy_acc, 4) if scored else 0.0,
            "fit_errors": self._fit_errors[:3],
            "note": ("Accuracies are measured after the run on bars the model had not seen; "
                     "they are reported, never fed back into a decision. Sideways labels are "
                     "excluded because direction was not the question there."),
        }
