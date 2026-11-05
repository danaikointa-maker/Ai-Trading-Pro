"""Empirical "does TP come before SL?" probabilities.

The question a trader actually asks is not "will it go up" but "if I put my stop
here and my target there, which one is touched first inside the horizon?".
This module answers that from the instrument's own history, conditional on the
current volatility (all excursions are expressed in ATR units).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class PathProbabilityTable:
    horizon_bars: dict[int, dict[str, np.ndarray]] = field(default_factory=dict)
    bar_minutes: int = 5
    samples: int = 0
    atr_points_median: dict[int, float] = field(default_factory=dict)

    # ---------------------------------------------------------------- build
    @classmethod
    def build(cls, df: pd.DataFrame, atr: np.ndarray, horizons_bars: list[int],
              bar_minutes: int = 5, max_samples: int = 4000) -> "PathProbabilityTable":
        table = cls(bar_minutes=bar_minutes)
        highs = df["h"].to_numpy(float)
        lows = df["l"].to_numpy(float)
        n = len(df)
        atr_ok = np.nan_to_num(atr, nan=np.nanmedian(atr) if np.isfinite(atr).any() else 1.0)
        atr_ok = np.where(atr_ok <= 0, 1e-9, atr_ok)
        for h in horizons_bars:
            if n <= h + 10:
                continue
            idx = np.arange(0, n - h)
            if len(idx) > max_samples:
                idx = idx[:: max(1, len(idx) // max_samples)][:max_samples]
            ref = df["c"].to_numpy(float)[idx]
            a = atr_ok[idx]
            hi_rel = (highs[idx[:, None] + np.arange(1, h + 1)[None, :]] - ref[:, None]) / a[:, None]
            lo_rel = (lows[idx[:, None] + np.arange(1, h + 1)[None, :]] - ref[:, None]) / a[:, None]
            table.horizon_bars[h] = {
                "high": np.maximum.accumulate(hi_rel, axis=1).astype(np.float32),
                "low": np.minimum.accumulate(lo_rel, axis=1).astype(np.float32),
            }
        table.samples = sum(v["high"].shape[0] for v in table.horizon_bars.values())
        return table

    # --------------------------------------------------------------- persist
    def arrays(self) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        for h, data in self.horizon_bars.items():
            out[f"high_{h}"] = data["high"]
            out[f"low_{h}"] = data["low"]
        return out

    @classmethod
    def from_arrays(cls, arrays: dict[str, np.ndarray], bar_minutes: int = 5) -> "PathProbabilityTable":
        table = cls(bar_minutes=bar_minutes)
        for key in arrays:
            if not key.startswith(("high_", "low_")):
                continue
            h = int(key.split("_")[1])
            table.horizon_bars.setdefault(h, {})[key.split("_")[0]] = arrays[key]
        table.samples = sum(v["high"].shape[0] for v in table.horizon_bars.values())
        return table

    # -------------------------------------------------------------- estimate
    @staticmethod
    def _first_cross(favourable: np.ndarray, adverse: np.ndarray, tp: float, sl: float) -> tuple[np.ndarray, np.ndarray]:
        hit_tp = np.any(favourable >= tp, axis=1)
        hit_sl = np.any(adverse <= -sl, axis=1)
        t_tp = np.where(hit_tp, np.argmax(favourable >= tp, axis=1), np.iinfo(np.int32).max)
        t_sl = np.where(hit_sl, np.argmax(adverse <= -sl, axis=1), np.iinfo(np.int32).max)
        return t_tp, t_sl

    def p_tp_before_sl(self, horizon_minutes: int, tp_atr: float, sl_atr: float,
                       p_up: float = 0.5, direction: int = 1) -> tuple[float, int]:
        """Blend of the long-side and short-side empirical win rates.

        Ties (TP and SL in the same bar) count as a loss — the conservative
        assumption for intrabar ambiguity.
        """
        h = max(1, int(round(horizon_minutes / self.bar_minutes)))
        available = sorted(self.horizon_bars)
        if not available:
            return 0.45, 0
        h = min(available, key=lambda x: abs(x - h))
        data = self.horizon_bars[h]
        high, low = data["high"], data["low"]
        tp_atr = max(0.05, float(tp_atr))
        sl_atr = max(0.05, float(sl_atr))

        t_tp_long, t_sl_long = self._first_cross(high, low, tp_atr, sl_atr)
        t_tp_short, t_sl_short = self._first_cross(-low, -high, tp_atr, sl_atr)
        win_long = (t_tp_long < t_sl_long).mean()
        win_short = (t_tp_short < t_sl_short).mean()

        if direction >= 0:
            p = p_up * win_long + (1.0 - p_up) * win_short
        else:
            p = p_up * win_short + (1.0 - p_up) * win_long
        return float(min(0.95, max(0.02, p))), int(high.shape[0])
