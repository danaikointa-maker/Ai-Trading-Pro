"""Tick storage split by UTC day, read lazily.

A real XAUUSD tick export is 1–2 million rows per day. Loading a month of that to settle
a handful of ambiguous bars is what made the first version impossible to use with real
data: memory grew with the *file*, not with the question being asked.

So ticks are stored one file per UTC day (`ticks/XAUUSD/2026-11-07.parquet`) and the
backtester reads only the days its window overlaps, keeping a small LRU of loaded days.
The query stays the same — `first_touch()` — because who reads the ticks should not be
the backtester's problem.

Two formats, chosen by what is installed:
* `parquet` when pyarrow is available (much smaller, typed, fast column reads);
* `csv.gz` otherwise. The extension on disk is the truth; nothing guesses.

Nothing here decides trading: it answers "which level traded first in this window".
"""
from __future__ import annotations

import gzip
import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

import numpy as np
import pandas as pd

COLUMNS = ["t", "bid", "ask"]
DAILY_FORMATS = ("parquet", "csv.gz")


class TickStoreError(ValueError):
    """Storage that cannot be used; the message is shown to the operator."""


def pyarrow_available() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - optional dependency
        return False


def default_format() -> str:
    return "parquet" if pyarrow_available() else "csv.gz"


def day_key(epoch: int) -> str:
    """UTC date of a tick — the partition key, which is also the swap/rollover basis."""
    return pd.Timestamp(int(epoch), unit="s", tz="UTC").strftime("%Y-%m-%d")


def symbol_dir(root: str | Path, symbol: str) -> Path:
    return Path(root) / "ticks" / symbol.upper()


def day_path(root: str | Path, symbol: str, day: str, fmt: str) -> Path:
    return symbol_dir(root, symbol) / f"{day}.{fmt}"


# --------------------------------------------------------------------- writing
def _write_day(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    if path.suffix == ".parquet":
        # Monotonic `t` packs to almost nothing as a delta and dictionary-encoding it
        # would be the opposite; with that one change parquet is as small as the gzip
        # CSV and reads roughly ten times faster.
        frame.to_parquet(tmp, index=False, compression="zstd", compression_level=9,
                         use_dictionary=False,
                         column_encoding={"t": "DELTA_BINARY_PACKED"})
    else:
        tmp.write_bytes(gzip.compress(
            frame.to_csv(index=False, float_format="%.5f", lineterminator="\n").encode(),
            mtime=0))
    tmp.replace(path)


def read_day(root: str | Path, symbol: str, day: str) -> tuple[pd.DataFrame, str] | None:
    """Read one day, preferring parquet when both exist (a re-import upgrades)."""
    for fmt in DAILY_FORMATS:
        path = day_path(root, symbol, day, fmt)
        if not path.exists():
            continue
        if fmt == "parquet":
            frame = pd.read_parquet(path, columns=COLUMNS)
        else:
            frame = pd.read_csv(path)
        frame = frame[COLUMNS].sort_values("t", kind="stable").reset_index(drop=True)
        frame["t"] = frame["t"].astype("int64")
        return frame, fmt
    return None


def available_days(root: str | Path, symbol: str) -> list[str]:
    folder = symbol_dir(root, symbol)
    if not folder.is_dir():
        return []
    days = {p.name.rsplit(".", 1)[0] if p.suffix == ".gz" else p.stem
            for p in folder.iterdir()
            if p.name.endswith((".parquet", ".csv.gz")) and not p.name.endswith(".tmp")}
    return sorted(days)


def manifest_path(root: str | Path, symbol: str) -> Path:
    return symbol_dir(root, symbol) / "manifest.json"


def write_manifest(root: str | Path, symbol: str, *, source: dict[str, Any],
                   days: list[dict[str, Any]], extras: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge this import into the existing index instead of replacing it.

    Importing October today and November next week must not make October disappear from
    the inventory — and a day whose file was pruned must not linger claiming rows.
    """
    previous = {}
    path = manifest_path(root, symbol)
    if path.exists():
        try:
            previous = {d["day"]: d for d in json.loads(path.read_text("utf-8")).get("days", [])
                        if d.get("day")}
        except (json.JSONDecodeError, KeyError, TypeError):
            previous = {}
    on_disk = set(available_days(root, symbol))
    merged = {**previous, **{d["day"]: d for d in days}}
    days = [merged[k] for k in sorted(merged) if k in on_disk]
    payload = {
        "symbol": symbol.upper(),
        "layout": "daily",
        "source": source,
        "days": days,
        "rows": sum(int(d["rows"]) for d in days),
        "first_t": min((int(d["first_t"]) for d in days), default=None),
        "last_t": max((int(d["last_t"]) for d in days), default=None),
        "days_covered": len(days),
        **(extras or {}),
    }
    path = manifest_path(root, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), "utf-8")
    return payload


def write_days(root: str | Path, symbol: str, frame: pd.DataFrame, *,
               fmt: str | None = None) -> list[dict[str, Any]]:
    """Split a normalised tick frame into one file per UTC day."""
    fmt = fmt or default_format()
    if fmt not in DAILY_FORMATS:
        raise TickStoreError(f"unknown tick format {fmt!r}; use one of {DAILY_FORMATS}")
    if frame.empty:
        raise TickStoreError("refusing to write an empty tick frame")
    out: list[dict[str, Any]] = []
    days = frame.assign(_day=[day_key(t) for t in frame["t"]])
    for day, part in days.groupby("_day", sort=True):
        rows = part[COLUMNS].sort_values("t", kind="stable").reset_index(drop=True)
        path = day_path(root, symbol, day, fmt)
        _write_day(path, rows)
        digest = hashlib.sha256(rows.to_csv(index=False, float_format="%.5f",
                                           lineterminator="\n").encode()).hexdigest()
        out.append({"day": day, "rows": int(len(rows)), "first_t": int(rows["t"].iloc[0]),
                    "last_t": int(rows["t"].iloc[-1]), "format": fmt,
                    "bytes": path.stat().st_size, "sha256": digest,
                    "path": str(path)})
    return out


def coverage(root: str | Path, symbol: str) -> dict[str, Any]:
    """What tick data exists for this symbol, day by day, without loading any of it."""
    days = available_days(root, symbol)
    rows = []
    for day in days:
        for fmt in DAILY_FORMATS:
            path = day_path(root, symbol, day, fmt)
            if not path.exists():
                continue
            rows.append({"day": day, "format": fmt, "bytes": path.stat().st_size})
            break
    manifest = None
    path = manifest_path(root, symbol)
    if path.exists():
        try:
            manifest = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            manifest = None
    by_day = {d["day"]: d for d in (manifest or {}).get("days", [])}
    out = []
    for row in rows:
        known = by_day.get(row["day"], {})
        out.append({**row, "rows": known.get("rows"), "first_t": known.get("first_t"),
                    "last_t": known.get("last_t")})
    return {
        "symbol": symbol.upper(),
        "layout": "daily" if rows else None,
        "days": out,
        "days_covered": len(out),
        "rows": sum(int(d["rows"] or 0) for d in out) if out else 0,
        "first_t": min((d["first_t"] for d in out if d["first_t"]), default=None),
        "last_t": max((d["last_t"] for d in out if d["last_t"]), default=None),
        "manifest": manifest,
    }


def known_days(root: str | Path, symbol: str) -> list[str]:
    """Day list from the manifest — used to answer 'is this day covered?' cheaply."""
    manifest = coverage(root, symbol)["manifest"] or {}
    return [d["day"] for d in manifest.get("days", [])]


# --------------------------------------------------------------------- reading
@dataclass
class Touch:
    kind: Literal["stop", "tp"]
    index: int
    price: float
    t: int


class TickStore:
    """Lazy, day-partitioned ticks for one symbol.

    `reads` counts how many day files were opened, which is the property that matters:
    a backtest over two days must not read thirty.
    """

    def __init__(self, root: str | Path, symbol: str, *, cache_days: int = 4) -> None:
        self.root = Path(root)
        self.symbol = symbol.upper()
        self.cache_days = max(1, int(cache_days))
        self._cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self.days = available_days(self.root, self.symbol)
        self.reads = 0
        self.ticks_read = 0
        self.days_read: set[str] = set()
        self.missing_days = 0
        self._total_rows = self._rows_from_manifest()
        self._rows_by_day = self._rows_by_day_from_manifest()
        self._bounds: dict[str, tuple[int, int]] = self._bounds_from_manifest()
        # A day with no manifest entry (files copied in by hand) has to be read once to
        # learn its range; everything the importer wrote is answered from the manifest,
        # so constructing a book over 30 days reads zero files.
        for day in self.days:
            if day in self._bounds:
                continue
            loaded = read_day(self.root, self.symbol, day)
            if loaded is None:
                continue
            frame, _ = loaded
            self.reads += 1
            if not frame.empty:
                self._bounds[day] = (int(frame["t"].iloc[0]), int(frame["t"].iloc[-1]))

    def _manifest(self) -> dict[str, Any]:
        path = manifest_path(self.root, self.symbol)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _rows_by_day_from_manifest(self) -> dict[str, int]:
        return {str(d["day"]): int(d.get("rows") or 0)
                for d in self._manifest().get("days", []) if d.get("day")}

    def _rows_from_manifest(self) -> int:
        payload = self._manifest()
        if payload.get("rows"):
            return int(payload["rows"])
        return 0

    def _bounds_from_manifest(self) -> dict[str, tuple[int, int]]:
        path = manifest_path(self.root, self.symbol)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            return {}
        out: dict[str, tuple[int, int]] = {}
        for entry in payload.get("days", []):
            if entry.get("day") and entry.get("first_t") is not None:
                out[str(entry["day"])] = (int(entry["first_t"]), int(entry["last_t"]))
        return out

    # ------------------------------------------------------------ inventory
    def __len__(self) -> int:
        return len(self.days)

    @property
    def available(self) -> bool:
        return bool(self.days)

    @property
    def first_t(self) -> int | None:
        return min((b[0] for b in self._bounds.values()), default=None)

    @property
    def last_t(self) -> int | None:
        return max((b[1] for b in self._bounds.values()), default=None)

    def rows(self) -> int:
        """Rows stored for this symbol (inventory, from the manifest — no files read)."""
        if self._total_rows:
            return self._total_rows
        return int(coverage(self.root, self.symbol)["rows"] or 0)

    def day_frame(self, day: str) -> pd.DataFrame | None:
        if day in self._cache:
            self._cache.move_to_end(day)
            return self._cache[day]
        loaded = read_day(self.root, self.symbol, day)
        self.reads += 1
        if loaded is None:
            return None
        frame, _ = loaded
        self.days_read.add(day)
        self._cache[day] = frame
        while len(self._cache) > self.cache_days:
            self._cache.popitem(last=False)
        return frame

    def days_for(self, start: int, end: int) -> list[str]:
        """Days whose file can contain ticks in [start, end) — from cached bounds."""
        out = []
        for day in self.days:
            bounds = self._bounds.get(day)
            if bounds is None:
                continue
            if bounds[1] < start or bounds[0] >= end:
                continue
            out.append(day)
        return out

    def ticks_in(self, start: int, end: int) -> int | None:
        """How many ticks exist inside [start, end) — from the manifest, no file reads.

        This is what lets a report say "ticks exist but not for this window" instead of
        quietly implying ticks were consulted.
        """
        if not self._rows_by_day:
            return None
        days = self.days_for(start, end)
        if not days:
            return 0
        total = 0
        for day in days:
            rows = self._rows_by_day.get(day)
            if rows is None:
                return None       # a hand-copied day: can't answer without reading it
            total += rows
        return total

    def window(self, start: int, end: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Ticks in [start, end) as (times, bid, ask), reading only the needed days."""
        frames = []
        for day in self.days_for(start, end):
            frame = self.day_frame(day)
            if frame is None or frame.empty:
                continue
            mask = (frame["t"] >= start) & (frame["t"] < end)
            if mask.any():
                frames.append(frame[mask])
        if not frames:
            self.missing_days += 1
            return (np.empty(0, dtype="int64"), np.empty(0), np.empty(0))
        merged = pd.concat(frames).sort_values("t", kind="stable")
        times = merged["t"].to_numpy(dtype="int64")
        self.ticks_read += int(len(times))
        return (times, merged["bid"].to_numpy(dtype=float),
                merged["ask"].to_numpy(dtype=float))

    def first_touch(self, start: int, end: int, direction: str, stop: float,
                    targets: Iterable[tuple[int, float]]) -> Touch | None:
        times, bid, ask = self.window(start, end)
        if len(times) == 0:
            return None
        exit_prices = bid if direction == "up" else ask
        best: Touch | None = None
        stop_hits = exit_prices <= stop if direction == "up" else exit_prices >= stop
        if stop_hits.any():
            i = int(stop_hits.argmax())
            best = Touch("stop", 0, float(stop), int(times[i]))
        for index, level in targets:
            hit = exit_prices >= level if direction == "up" else exit_prices <= level
            if not hit.any():
                continue
            i = int(hit.argmax())
            candidate = Touch("tp", index, float(level), int(times[i]))
            if best is None or candidate.t < best.t:
                best = candidate
        return best

    def stats(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "layout": "daily", "days": len(self.days),
                "days_read": sorted(self.days_read), "days_loaded": self.reads,
                "rows": self.rows(), "rows_in_window": self.ticks_read,
                "cache_days": self.cache_days}


def prune_days(root: str | Path, symbol: str, keep_days: int) -> dict[str, Any]:
    """Delete all but the newest `keep_days` day files (operator housekeeping)."""
    days = available_days(root, symbol)
    if keep_days <= 0:
        raise TickStoreError("keep_days must be > 0")
    drop = days[:-keep_days] if len(days) > keep_days else []
    removed = []
    for day in drop:
        for fmt in DAILY_FORMATS:
            path = day_path(root, symbol, day, fmt)
            if path.exists():
                path.unlink()
                removed.append({"day": day, "format": fmt})
    return {"removed": removed, "kept": days[-keep_days:], "remaining": available_days(root, symbol)}
