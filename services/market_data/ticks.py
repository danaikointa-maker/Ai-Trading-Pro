"""Real tick data: import it, then use it to settle what happened *inside* a bar.

The backtester has always had to guess when a bar's range covered both the stop and a
target: it assumes the stop came first ("conservative"). That single assumption can
turn winners into losers, and there is no way to check it without ticks.

This module imports a broker tick export (`time, bid, ask`) and answers the question
properly — walking the ticks of that bar in order and reporting which level was
touched first. When ticks are missing for a bar the backtest keeps the conservative
assumption, but now *says* which bars were settled by ticks and which were guessed.

Conventions (they matter):
* a long exits at the **bid** (you sell into the bid), a short exits at the **ask**;
* a touch is `<=` the stop for longs and `>=` the stop for shorts, i.e. the level is
  considered filled the moment it trades at or through the price.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

import pandas as pd

COLUMNS = ["t", "bid", "ask"]
TICK_SUBDIR = "ticks"


class TickDataError(ValueError):
    """Tick data that cannot be used as-is; the message is shown to the operator."""


@dataclass
class Touch:
    kind: Literal["stop", "tp"]
    index: int          # 0-based index into the target list; 0 for a stop
    price: float
    t: int


# --------------------------------------------------------------------- import
def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, sep=None, engine="python")
    except Exception as exc:  # noqa: BLE001 - the message is the diagnosis
        raise TickDataError(f"cannot read {path}: {exc}") from exc


def _find_columns(frame: pd.DataFrame) -> tuple[str, str, str]:
    lower = {str(c).strip().lower(): c for c in frame.columns}

    def pick(*names: str) -> str | None:
        for name in names:
            if name in lower:
                return lower[name]
        return None

    time_col = pick("time", "timestamp", "datetime", "date", "t")
    bid_col = pick("bid", "bid_price", "b")
    ask_col = pick("ask", "ask_price", "a")
    missing = [label for label, col in (("time", time_col), ("bid", bid_col), ("ask", ask_col))
               if col is None]
    if missing:
        raise TickDataError(
            f"tick file is missing {missing}; expected columns time, bid, ask "
            f"(found: {list(frame.columns)[:8]})")
    return time_col, bid_col, ask_col  # type: ignore[return-value]


def load_tick_csv(path: str | Path, tz: str = "UTC") -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read a tick export into `t, bid, ask` (UTC epoch seconds), reporting drops.

    Nothing is silently discarded: every row that had to go is counted under a
    reason, because a tick file that lost half its rows makes every later number
    wrong in a way you cannot see.
    """
    src = Path(path).expanduser()
    if not src.exists():
        raise TickDataError(f"tick file not found: {src}")
    raw = _read_csv(src)
    time_col, bid_col, ask_col = _find_columns(raw)
    total = len(raw)
    drops: dict[str, int] = {}

    frame = pd.DataFrame({
        "t": pd.to_datetime(raw[time_col], errors="coerce", utc=False),
        "bid": pd.to_numeric(raw[bid_col], errors="coerce"),
        "ask": pd.to_numeric(raw[ask_col], errors="coerce"),
    })
    bad_time = frame["t"].isna()
    drops["unparsed timestamp"] = int(bad_time.sum())
    frame = frame[~bad_time]
    bad_price = frame["bid"].isna() | frame["ask"].isna() | (frame["bid"] <= 0) | (frame["ask"] <= 0)
    drops["missing/zero price"] = int(bad_price.sum())
    frame = frame[~bad_price]
    inverted = frame["ask"] < frame["bid"]
    drops["ask below bid"] = int(inverted.sum())
    frame = frame[~inverted]

    if frame.empty:
        raise TickDataError(f"{src.name}: no usable ticks ({drops})")

    if getattr(frame["t"].dt, "tz", None) is None:
        localised = frame["t"].dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
        naive_drop = int(localised.isna().sum())
        if naive_drop:
            drops["ambiguous local time"] = naive_drop
        frame = frame.assign(t=localised[~localised.isna()])
    # pandas 3 may parse to datetime64[us]; converting via the epoch is unit-safe,
    # whereas astype("int64") would be microseconds and collapse rows onto one second.
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    frame = frame.assign(
        t=((frame["t"].dt.tz_convert("UTC") - epoch) // pd.Timedelta(seconds=1)).astype("int64"))
    frame = frame.sort_values("t", kind="stable")

    duplicated = int(frame["t"].duplicated().sum())
    if duplicated:
        drops["duplicate timestamp"] = duplicated
        frame = frame.drop_duplicates(subset="t", keep="last")

    frame = frame.reset_index(drop=True)
    summary = {
        "source": str(src),
        "rows_read": int(total),
        "rows_used": int(len(frame)),
        "dropped": {k: v for k, v in drops.items() if v},
        "first_t": int(frame["t"].iloc[0]),
        "last_t": int(frame["t"].iloc[-1]),
        "tz": tz,
        "sha256": hashlib.sha256(
            frame.to_csv(index=False, float_format="%.5f", lineterminator="\n").encode()
        ).hexdigest(),
    }
    return frame[COLUMNS], summary


def tick_path(out_dir: str | Path, symbol: str) -> Path:
    return Path(out_dir) / TICK_SUBDIR / f"{symbol.upper()}_ticks.csv.gz"


def import_ticks(csv_path: str | Path, symbol: str, out_dir: str | Path,
                 tz: str = "UTC") -> dict[str, Any]:
    """Convert a broker tick export into the stored form and write a manifest."""
    frame, summary = load_tick_csv(csv_path, tz=tz)
    path = tick_path(out_dir, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(
        frame.to_csv(index=False, float_format="%.5f", lineterminator="\n").encode(), mtime=0))
    manifest = {**summary, "symbol": symbol.upper(), "path": str(path), "stored_rows": len(frame),
                "spread_points_median": round(float((frame["ask"] - frame["bid"]).median()), 5)}
    (path.parent / f"{symbol.upper()}_ticks.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    return manifest


def tick_summary(out_dir: str | Path, symbol: str) -> dict[str, Any] | None:
    path = Path(out_dir) / TICK_SUBDIR / f"{symbol.upper()}_ticks.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return None


# ----------------------------------------------------------------- usage side
class TickBook:
    """Ticks for one symbol, sorted, with the one query the backtest needs."""

    def __init__(self, frame: pd.DataFrame, symbol: str = "") -> None:
        missing = [c for c in COLUMNS if c not in frame.columns]
        if missing:
            raise TickDataError(f"tick frame is missing columns: {missing}")
        ordered = frame[COLUMNS].sort_values("t", kind="stable").reset_index(drop=True)
        self.symbol = symbol
        self.frame = ordered
        self.times = ordered["t"].to_numpy(dtype="int64")
        self.bid = ordered["bid"].to_numpy(dtype=float)
        self.ask = ordered["ask"].to_numpy(dtype=float)
        self.used = 0          # bars settled by ticks
        self.exhausted = 0     # bars with no ticks at all

    @classmethod
    def load(cls, out_dir: str | Path, symbol: str) -> "TickBook | None":
        path = tick_path(out_dir, symbol)
        if not path.exists():
            return None
        frame = pd.read_csv(path)
        return cls(frame, symbol)

    def __len__(self) -> int:
        return len(self.frame)

    def slice(self, start: int, end: int) -> tuple[int, int]:
        """Half-open [start, end) index range, via binary search (no full scan)."""
        import numpy as np

        lo = int(np.searchsorted(self.times, start, "left"))
        hi = int(np.searchsorted(self.times, end, "left"))
        return lo, hi

    def first_touch(self, start: int, end: int, direction: str, stop: float,
                    targets: Iterable[tuple[int, float]]) -> Touch | None:
        """Which level traded first inside [start, end): the stop, or a target?

        Returns None when there are no ticks in the window — the caller then keeps
        its conservative assumption instead of inventing an answer.
        """
        lo, hi = self.slice(start, end)
        if hi <= lo:
            return None
        exit_prices = self.bid[lo:hi] if direction == "up" else self.ask[lo:hi]
        times = self.times[lo:hi]

        best: Touch | None = None
        if direction == "up":
            stop_hits = exit_prices <= stop
        else:
            stop_hits = exit_prices >= stop
        if stop_hits.any():
            i = int(stop_hits.argmax())
            best = Touch("stop", 0, float(stop), int(times[i]))

        for index, level in targets:
            hit = (exit_prices >= level) if direction == "up" else (exit_prices <= level)
            if not hit.any():
                continue
            i = int(hit.argmax())
            candidate = Touch("tp", index, float(level), int(times[i]))
            if best is None or candidate.t < best.t:
                best = candidate
        return best

    def stats(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "rows": len(self.frame),
            "first_t": int(self.times[0]) if len(self.times) else None,
            "last_t": int(self.times[-1]) if len(self.times) else None,
            "bars_settled_by_ticks": self.used,
            "bars_without_ticks": self.exhausted,
        }
