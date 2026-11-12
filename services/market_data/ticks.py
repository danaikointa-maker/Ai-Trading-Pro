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
import io
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

import numpy as np
import pandas as pd

from services.market_data.tick_store import (TickStore, TickStoreError, Touch, available_days, day_key,
                                             legacy_tick_path, manifest_path, read_manifest, symbol_dir, write_days,
                                             write_manifest)

__all__ = ["TickBook", "TickDataError", "Touch", "import_ticks", "load_tick_csv",
           "tick_layout", "tick_path", "tick_summary", "iter_tick_csv"]

COLUMNS = ["t", "bid", "ask"]
TICK_SUBDIR = "ticks"


class TickDataError(ValueError):
    """Tick data that cannot be used as-is; the message is shown to the operator."""


# --------------------------------------------------------------------- import
def _sniff_separator(path: Path) -> str:
    head = path.read_text("utf-8", errors="replace")[:4096].splitlines()[:5]
    counts = {sep: sum(line.count(sep) for line in head) for sep in (",", ";", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _detect_columns(path: Path, sep: str) -> tuple[str, str, str]:
    header = path.read_text("utf-8", errors="replace").splitlines()[0]
    columns = [c.strip().strip('"') for c in header.split(sep)]
    lower = {c.lower(): c for c in columns}

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
            f"(found: {columns[:8]})")
    return time_col, bid_col, ask_col  # type: ignore[return-value]


def _normalise(chunk: pd.DataFrame, time_col: str, bid_col: str, ask_col: str,
               tz: str) -> tuple[pd.DataFrame, dict[str, int]]:
    """Parse one chunk into `t, bid, ask`, counting every row that had to go."""
    drops: dict[str, int] = {}
    frame = pd.DataFrame({
        "t": pd.to_datetime(chunk[time_col], errors="coerce", utc=False),
        "bid": pd.to_numeric(chunk[bid_col], errors="coerce"),
        "ask": pd.to_numeric(chunk[ask_col], errors="coerce"),
    })
    bad_time = frame["t"].isna()
    if bad_time.any():
        drops["unparsed timestamp"] = int(bad_time.sum())
        frame = frame[~bad_time]
    bad_price = (frame["bid"].isna() | frame["ask"].isna()
                 | (frame["bid"] <= 0) | (frame["ask"] <= 0))
    if bad_price.any():
        drops["missing/zero price"] = int(bad_price.sum())
        frame = frame[~bad_price]
    inverted = frame["ask"] < frame["bid"]
    if inverted.any():
        drops["ask below bid"] = int(inverted.sum())
        frame = frame[~inverted]
    if frame.empty:
        return frame[COLUMNS], drops

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
    return frame[COLUMNS].reset_index(drop=True), drops


def iter_tick_csv(path: str | Path, tz: str = "UTC", chunk_rows: int = 200_000) -> Iterator[tuple[pd.DataFrame, dict[str, int], int]]:
    """Yield (normalised chunk, drops, rows_read) so a multi-GB export stays bounded."""
    src = Path(path).expanduser()
    if not src.exists():
        raise TickDataError(f"tick file not found: {src}")
    sep = _sniff_separator(src)
    time_col, bid_col, ask_col = _detect_columns(src, sep)
    try:
        reader = pd.read_csv(src, sep=sep, chunksize=max(1, int(chunk_rows)),
                             low_memory=False)
    except Exception as exc:  # noqa: BLE001 - the message is the diagnosis
        raise TickDataError(f"cannot read {src}: {exc}") from exc
    for chunk in reader:
        frame, drops = _normalise(chunk, time_col, bid_col, ask_col, tz)
        yield frame, drops, len(chunk)


def load_tick_csv(path: str | Path, tz: str = "UTC") -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read a whole tick export into `t, bid, ask` (UTC epoch seconds), reporting drops."""
    src = Path(path).expanduser()
    frames: list[pd.DataFrame] = []
    drops: dict[str, int] = {}
    total = 0
    for frame, part, rows in iter_tick_csv(src, tz=tz, chunk_rows=5_000_000):
        total += rows
        for reason, count in part.items():
            drops[reason] = drops.get(reason, 0) + count
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise TickDataError(f"{src.name}: no usable ticks ({drops})")
    merged = pd.concat(frames).sort_values("t", kind="stable")
    duplicated = int(merged["t"].duplicated().sum())
    if duplicated:
        drops["duplicate timestamp"] = drops.get("duplicate timestamp", 0) + duplicated
        merged = merged.drop_duplicates(subset="t", keep="last")
    merged = merged.reset_index(drop=True)
    summary = {
        "source": str(src),
        "rows_read": int(total),
        "rows_used": int(len(merged)),
        "dropped": {k: v for k, v in drops.items() if v},
        "first_t": int(merged["t"].iloc[0]),
        "last_t": int(merged["t"].iloc[-1]),
        "tz": tz,
        "sha256": hashlib.sha256(
            merged.to_csv(index=False, float_format="%.5f", lineterminator="\n").encode()
        ).hexdigest(),
    }
    return merged[COLUMNS], summary


def tick_path(out_dir: str | Path, symbol: str) -> Path:
    """Legacy single-file layout (kept so an older import still loads)."""
    return legacy_tick_path(out_dir, symbol)


def _legacy_verified(out_dir: str | Path, symbol: str) -> tuple[dict[str, Any], bytes] | None:
    """Local sidecar integrity only, not authenticated broker provenance."""
    path = tick_path(out_dir, symbol)
    meta = legacy_tick_path(out_dir, symbol, metadata=True)
    if not path.exists() and not meta.exists():
        return None
    try:
        payload = json.loads(meta.read_text('utf-8'))
        if (not isinstance(payload, dict) or type(payload.get('schema')) is not int
                or payload['schema'] != 1 or payload.get('layout') != 'file'
                or payload.get('symbol') != symbol.upper()
                or payload.get('dataset_root') != str(Path(out_dir).resolve())
                or payload.get('path') != str(path)):
            raise ValueError('identity mismatch')
        raw = path.read_bytes()
        if (len(raw) != payload.get('bytes')
                or hashlib.sha256(raw).hexdigest() != payload.get('stored_sha256')):
            raise ValueError('digest mismatch')
        return payload, raw
    except (OSError, ValueError, TypeError, KeyError):
        raise TickStoreError('legacy tick provenance/integrity invalid; refusing artifact') from None


def import_ticks(csv_path: str | Path, symbol: str, out_dir: str | Path, tz: str = "UTC", *,
                 layout: str = "daily", fmt: str | None = None,
                 chunk_rows: int = 200_000) -> dict[str, Any]:
    """Import a broker export into daily files (default) or one legacy file.

    Chunked reading means a multi-GB export never sits in memory: each chunk is
    normalised, buckets are merged per UTC day, and only one day is held at a time
    before it is written out.
    """
    if layout not in ("daily", "file"):
        raise TickDataError(f"unknown layout {layout!r}; use 'daily' or 'file'")
    # Validate both destinations before reading the export or publishing any data.
    if layout == "file":
        _legacy_verified(out_dir, symbol)
    else:
        read_manifest(out_dir, symbol)
    src = Path(csv_path).expanduser()
    buckets: dict[str, list[pd.DataFrame]] = {}
    drops: dict[str, int] = {}
    total = 0
    first_t: int | None = None
    last_t: int | None = None
    for frame, part, rows in iter_tick_csv(src, tz=tz, chunk_rows=chunk_rows):
        total += rows
        for reason, count in part.items():
            drops[reason] = drops.get(reason, 0) + count
        if frame.empty:
            continue
        first_t = int(frame["t"].iloc[0]) if first_t is None else min(first_t, int(frame["t"].iloc[0]))
        last_t = int(frame["t"].iloc[-1]) if last_t is None else max(last_t, int(frame["t"].iloc[-1]))
        for day, part_frame in frame.groupby(frame["t"].map(day_key), sort=True):
            buckets.setdefault(str(day), []).append(part_frame)

    if not buckets:
        raise TickDataError(f"{src.name}: no usable ticks ({drops})")

    days: list[dict[str, Any]] = []
    rows_used = 0
    spread_samples: list[float] = []
    if layout == "file":
        merged = pd.concat([f for parts in buckets.values() for f in parts])
        merged = merged.sort_values("t", kind="stable")
        duplicated = int(merged["t"].duplicated().sum())
        if duplicated:
            drops["duplicate timestamp"] = drops.get("duplicate timestamp", 0) + duplicated
            merged = merged.drop_duplicates(subset="t", keep="last")
        merged = merged.reset_index(drop=True)
        path = tick_path(out_dir, symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(
            merged.to_csv(index=False, float_format="%.5f", lineterminator="\n").encode(),
            mtime=0))
        rows_used = len(merged)
        spread_samples = (merged["ask"] - merged["bid"]).tolist()
        manifest = {
            "schema": 1, "dataset_root": str(Path(out_dir).resolve()),
            "bytes": path.stat().st_size,
            "stored_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            **{k: v for k, v in {
                "source": str(src), "rows_read": total, "rows_used": rows_used,
                "dropped": {k: v for k, v in drops.items() if v},
                "first_t": first_t, "last_t": last_t, "tz": tz,
                "sha256": hashlib.sha256(
                    merged.to_csv(index=False, float_format="%.5f", lineterminator="\n").encode()
                ).hexdigest(),
            }.items()},
            "symbol": symbol.upper(), "layout": "file", "path": str(path),
            "stored_rows": rows_used,
            "spread_points_median": round(float(np.median(spread_samples)), 5),
        }
        legacy_tick_path(out_dir, symbol, metadata=True).write_text(
            json.dumps(manifest, indent=2), "utf-8")
        return manifest

    for day in sorted(buckets):
        merged = pd.concat(buckets[day]).sort_values("t", kind="stable")
        duplicated = int(merged["t"].duplicated().sum())
        if duplicated:
            drops["duplicate timestamp"] = drops.get("duplicate timestamp", 0) + duplicated
            merged = merged.drop_duplicates(subset="t", keep="last")
        merged = merged.reset_index(drop=True)
        spread_samples.extend((merged["ask"] - merged["bid"]).head(5000).tolist())
        days.extend(write_days(out_dir, symbol, merged, fmt=fmt))
        rows_used += len(merged)

    source = {"file": str(src), "tz": tz, "rows_read": total,
              "dropped": {k: v for k, v in drops.items() if v},
              "sha256": hashlib.sha256(
                  json.dumps([{"day": d["day"], "sha256": d["sha256"]} for d in days],
                             sort_keys=True).encode()).hexdigest()}
    manifest = write_manifest(
        out_dir, symbol, source=source, days=days,
        extras={"rows_used": rows_used, "stored_rows": rows_used, "rows_read": total,
                "path": str(symbol_dir(out_dir, symbol)),
                "dropped": {k: v for k, v in drops.items() if v},
                "spread_points_median": round(float(np.median(spread_samples)), 5)
                if spread_samples else None})
    return manifest


def tick_summary(out_dir: str | Path, symbol: str) -> dict[str, Any] | None:
    """Manifest for either layout (daily first, then the legacy single-file one)."""
    daily = manifest_path(out_dir, symbol)
    if daily.exists():
        payload = read_manifest(out_dir, symbol)
        return {**payload, "path": str(symbol_dir(out_dir, symbol))}
    if available_days(out_dir, symbol):
        raise TickStoreError('daily tick manifest missing; refusing unregistered index')
    verified = _legacy_verified(out_dir, symbol)
    return verified[0] if verified else None


def tick_layout(out_dir: str | Path, symbol: str) -> str | None:
    if available_days(out_dir, symbol):
        return "daily"
    if tick_path(out_dir, symbol).exists():
        return "file"
    return None


# ----------------------------------------------------------------- usage side
class TickBook:
    """Ticks for one symbol behind the one query the backtest needs.

    Two backends, same API:
    * daily files (the default) — read lazily, only the days a bar window touches;
    * a single legacy file — loaded whole, for imports made by the first version.

    `used`/`exhausted` count what the backtest did with it: bars settled by ticks, and
    bars where ticks were expected but absent. Those counters live here because they
    are about the *run*, not about the storage.
    """

    def __init__(self, frame: pd.DataFrame | None = None, symbol: str = "", *,
                 store: "TickStore | None" = None) -> None:
        self.symbol = symbol
        self.used = 0
        self.exhausted = 0
        self.store = store
        self.window: tuple[int, int] | None = None
        self.times = np.empty(0, dtype="int64")
        self.bid = np.empty(0)
        self.ask = np.empty(0)
        if store is not None:
            self.layout = "daily"
            return
        if frame is None:
            raise TickDataError("TickBook needs a frame or a store")
        missing = [c for c in COLUMNS if c not in frame.columns]
        if missing:
            raise TickDataError(f"tick frame is missing columns: {missing}")
        ordered = frame[COLUMNS].sort_values("t", kind="stable").reset_index(drop=True)
        self.layout = "memory"
        self.frame = ordered
        self.times = ordered["t"].to_numpy(dtype="int64")
        self.bid = ordered["bid"].to_numpy(dtype=float)
        self.ask = ordered["ask"].to_numpy(dtype=float)

    @classmethod
    def load(cls, out_dir: str | Path, symbol: str, *, cache_days: int = 4) -> "TickBook | None":
        """Daily layout first; falls back to a legacy single file if that is all there is."""
        if available_days(out_dir, symbol):
            return cls(store=TickStore(out_dir, symbol, cache_days=cache_days), symbol=symbol.upper())
        verified = _legacy_verified(out_dir, symbol)
        if verified is None:
            return None
        payload, raw = verified
        try:
            frame = pd.read_csv(io.BytesIO(gzip.decompress(raw)))
            canonical = frame[COLUMNS].to_csv(index=False, float_format='%.5f', lineterminator='\n').encode()
            if (hashlib.sha256(canonical).hexdigest() != payload.get('sha256')
                    or len(frame) != payload.get('stored_rows')
                    or int(frame['t'].iloc[0]) != payload.get('first_t')
                    or int(frame['t'].iloc[-1]) != payload.get('last_t')):
                raise ValueError('content mismatch')
        except (OSError, ValueError, EOFError, KeyError, IndexError):
            raise TickStoreError('legacy tick content integrity invalid') from None
        return cls(frame, symbol)

    # ------------------------------------------------------------- geometry
    def __len__(self) -> int:
        if self.store is not None:
            return len(self.store)
        return len(self.frame)

    def slice(self, start: int, end: int) -> tuple[int, int]:
        """Half-open [start, end) index range, via binary search (no full scan)."""
        lo = int(np.searchsorted(self.times, start, "left"))
        hi = int(np.searchsorted(self.times, end, "left"))
        return lo, hi

    def cover_window(self, start: int, end: int) -> None:
        """Declare the window this run actually tests, so the report can be precise."""
        self.window = (int(start), int(end))

    def ticks_in_window(self) -> int | None:
        """Ticks available inside the declared window (manifest-only for daily files)."""
        if self.window is None:
            return None
        if self.store is not None:
            return self.store.ticks_in(*self.window)
        lo, hi = self.slice(*self.window)
        return hi - lo

    def days_needed(self, start: int, end: int) -> list[str]:
        return self.store.days_for(start, end) if self.store is not None else []

    def first_touch(self, start: int, end: int, direction: str, stop: float,
                    targets: Iterable[tuple[int, float]]) -> Touch | None:
        """Which level traded first inside [start, end): the stop, or a target?

        Returns None when there are no ticks in the window — the caller then keeps
        its conservative assumption instead of inventing an answer.
        """
        if self.store is not None:
            return self.store.first_touch(start, end, direction, stop, targets)
        lo, hi = self.slice(start, end)
        if hi <= lo:
            return None
        exit_prices = self.bid[lo:hi] if direction == "up" else self.ask[lo:hi]
        times = self.times[lo:hi]

        best: Touch | None = None
        stop_hits = exit_prices <= stop if direction == "up" else exit_prices >= stop
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
        out: dict[str, Any] = {
            "symbol": self.symbol,
            "layout": self.layout,
            "bars_settled_by_ticks": self.used,
            "bars_without_ticks": self.exhausted,
        }
        if self.store is not None:
            out.update({"days": len(self.store.days), "days_loaded": self.store.reads,
                        "days_in_window": (len(self.store.days_for(*self.window))
                                           if self.window is not None else None),
                        "ticks_in_window": self.ticks_in_window(),
                        "rows": self.store.rows(),
                        "rows_in_window": self.store.ticks_read,
                        "days_used": sorted(self.store.days_read),
                        "first_t": self.store.first_t, "last_t": self.store.last_t})
        else:
            out.update({"rows": len(self.frame), "days": None,
                        "ticks_in_window": self.ticks_in_window(),
                        "first_t": int(self.times[0]) if len(self.times) else None,
                        "last_t": int(self.times[-1]) if len(self.times) else None})
        return out
