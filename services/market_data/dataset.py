"""Bring real candles into the platform.

Every number this platform prints is only as meaningful as the bars under it, and
the default feed is synthetic — good for exercising the pipeline, useless as
evidence. This module turns a broker export (MT5 "Save as", TradingView, Dukascopy
CSV…) into the one schema the engines already speak: `t, o, h, l, c, v` with `t`
in UTC epoch seconds.

The import refuses to guess: columns must be identifiable, timestamps must parse in
a named timezone, prices must be positive, and any row it had to drop is counted
and reported rather than silently discarded.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

OHLC_COLUMNS = ("o", "h", "l", "c")

# Header spellings seen in the wild -> our schema. MT5 writes "<DATE> <TIME>
# <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> <VOL> <SPREAD>" with angle brackets.
_ALIASES: dict[str, str] = {
    "t": "t", "time": "t", "timestamp": "t", "datetime": "t", "date_time": "t",
    "gmt_time": "t", "utc": "t", "bar_time": "t",
    "date": "date",
    "o": "o", "open": "o", "open_price": "o", "bid_open": "o",
    "h": "h", "high": "h", "high_price": "h", "bid_high": "h",
    "l": "l", "low": "l", "low_price": "l", "bid_low": "l",
    "c": "c", "close": "c", "close_price": "c", "bid_close": "c", "price": "c",
    "v": "v", "volume": "v", "vol": "v", "tickvol": "v", "tick_volume": "v",
    "real_volume": "v", "ticks": "v",
    "ask": "ask", "bid": "bid", "spread": "spread",
}

_SEPARATORS = (",", ";", "\t", "|")


class DatasetError(ValueError):
    """Raised when a file cannot be trusted as candle data."""


def _clean_header(name: str) -> str:
    raw = str(name).strip().strip("<>").strip().lower()
    raw = raw.replace(" ", "_").replace("-", "_").replace(".", "_")
    return _ALIASES.get(raw, raw)


def _read_any(path: Path) -> pd.DataFrame:
    """Read a CSV with whichever separator the file actually uses."""
    last: Exception | None = None
    for sep in _SEPARATORS:
        try:
            df = pd.read_csv(path, sep=sep, engine="python")
        except Exception as exc:  # noqa: BLE001 - try the next separator
            last = exc
            continue
        if df.shape[1] > 1:
            return df
    if last is not None:
        raise DatasetError(f"cannot read {path.name}: {last}") from last
    raise DatasetError(f"cannot read {path.name}: no columns detected")


def _timestamps(df: pd.DataFrame, tz: str) -> pd.Series:
    date_col = "date" if "date" in df.columns else None
    if date_col and "t" in df.columns:
        combined = df[date_col].astype(str).str.strip() + " " + df["t"].astype(str).str.strip()
        stamps = pd.to_datetime(combined, errors="coerce", format="mixed")
    elif "t" in df.columns and pd.api.types.is_numeric_dtype(df["t"]):
        # an already-normalised file (or an exporter that writes epoch seconds):
        # pandas would read a bare 1792999980 as nanoseconds and collapse the series
        stamps = pd.to_datetime(df["t"].astype("float64"), unit="s", errors="coerce", utc=True)
    elif "t" in df.columns:
        stamps = pd.to_datetime(df["t"], errors="coerce", format="mixed")
    else:
        raise DatasetError("no time column: expected one of time/datetime/date+time")

    bad = int(stamps.isna().sum())
    if bad:
        raise DatasetError(f"{bad} row(s) have a timestamp that does not parse — "
                           "check the date format and the --tz you passed")

    if stamps.dt.tz is None:
        # Naive stamps are only meaningful with a named timezone; assuming local
        # time silently shifts every bar by hours.
        try:
            stamps = stamps.dt.tz_localize(tz)
        except Exception as exc:  # noqa: BLE001
            raise DatasetError(f"cannot localise timestamps as {tz!r}: {exc}") from exc
    # epoch seconds by subtraction, not by casting: pandas 3 keeps datetime64[us],
    # so `astype("int64") // 10**9` silently collapsed every bar inside a 1000s bin.
    utc = stamps.dt.tz_convert("UTC")
    return (utc - pd.Timestamp(0, tz="UTC")).dt.total_seconds().astype("int64")


def load_candles(path: str | Path, tz: str = "UTC", digits: int | None = None) -> pd.DataFrame:
    """Load a candle file into the engine schema (`t, o, h, l, c, v`), UTC epochs.

    Raises `DatasetError` — never returns quietly-partial data — when the file has
    no recognisable OHLC columns or unparseable timestamps.
    """
    path = Path(path)
    if not path.exists():
        raise DatasetError(f"file not found: {path}")
    raw = _read_any(path)
    raw.columns = [_clean_header(c) for c in raw.columns]
    missing = [c for c in ("o", "h", "l", "c") if c not in raw.columns]
    if missing:
        raise DatasetError(f"missing price column(s): {missing} "
                           f"(found {sorted(set(raw.columns))})")

    df = pd.DataFrame({
        "t": _timestamps(raw, tz),
        "o": pd.to_numeric(raw["o"], errors="coerce"),
        "h": pd.to_numeric(raw["h"], errors="coerce"),
        "l": pd.to_numeric(raw["l"], errors="coerce"),
        "c": pd.to_numeric(raw["c"], errors="coerce"),
        "v": pd.to_numeric(raw["v"], errors="coerce") if "v" in raw.columns else 0.0,
    })
    df["v"] = df["v"].fillna(0.0).clip(lower=0.0)

    # sort + duplicate collapse: re-sent bars are normal in broker exports
    before = len(df)
    df = df.drop_duplicates(subset="t", keep="last").sort_values("t", kind="stable")
    dropped_dupes = before - len(df)

    # an OHLC row that violates its own geometry (or has a non-price) is corrupt
    finite = df[["o", "h", "l", "c"]].notna().all(axis=1)
    positive = (df[["o", "h", "l", "c"]] > 0).all(axis=1)
    geometry = ((df["h"] >= df[["o", "c"]].max(axis=1) - 1e-12)
                & (df["l"] <= df[["o", "c"]].min(axis=1) + 1e-12))
    good = finite & positive & geometry
    dropped_invalid = int((~good).sum())
    df = df[good].reset_index(drop=True)

    if df.empty:
        raise DatasetError("no usable rows left after validation")
    if digits is not None:
        df = df.round({k: int(digits) for k in ("o", "h", "l", "c")})
    df["t"] = df["t"].astype("int64")
    df.attrs["dropped_duplicates"] = dropped_dupes
    df.attrs["dropped_invalid"] = dropped_invalid
    return df


TIMEFRAME_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                     "H1": 3600, "H4": 14400, "D1": 86400}


def describe(df: pd.DataFrame, expected_seconds: int | None = None) -> dict[str, Any]:
    """Facts about the series a human can check against the source file."""
    expected = int(expected_seconds or 60)
    t = df["t"].to_numpy()
    gaps = int((pd.Series(t).diff().dropna() > expected).sum())
    largest = int(pd.Series(t).diff().dropna().max()) if len(t) > 1 else 0
    return {
        "rows": int(len(df)),
        "from": int(t[0]),
        "to": int(t[-1]),
        "from_iso": pd.Timestamp(int(t[0]), unit="s", tz="UTC").isoformat(),
        "to_iso": pd.Timestamp(int(t[-1]), unit="s", tz="UTC").isoformat(),
        "span_days": round((int(t[-1]) - int(t[0])) / 86400, 2),
        "gaps": gaps,
        "largest_gap_minutes": round(largest / 60, 1) if largest else 0.0,
        "dropped_duplicates": int(df.attrs.get("dropped_duplicates", 0)),
        "dropped_invalid": int(df.attrs.get("dropped_invalid", 0)),
        "first_close": float(df["c"].iloc[0]),
        "last_close": float(df["c"].iloc[-1]),
        "min_close": float(df["c"].min()),
        "max_close": float(df["c"].max()),
    }


def import_candles(src: str | Path, symbol: str, out_dir: str | Path,
                   tz: str = "UTC", digits: int | None = None,
                   timeframe: str = "M1") -> dict[str, Any]:
    """Validate a file and store it as `{SYMBOL}_{TF}.csv` plus a metadata sidecar.

    The sidecar is not decoration: it records the source hash and every row the
    importer dropped, so a later "why is this run different" question has an answer.
    """
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = load_candles(src, tz=tz, digits=digits)
    facts = describe(df, expected_seconds=TIMEFRAME_SECONDS.get(timeframe.upper(), 60))
    dest = out_dir / f"{symbol.upper()}_{timeframe.upper()}.csv"
    df.to_csv(dest, index=False)

    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
    meta = {
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "source_file": src.name,
        "source_sha256_16": digest,
        "source_timezone": tz,
        "imported_at": int(time.time()),
        "csv": dest.name,
        **facts,
    }
    (out_dir / f"{symbol.upper()}_{timeframe.upper()}.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def load_dataset(out_dir: str | Path, symbol: str, timeframe: str = "M1") -> pd.DataFrame:
    """Read back an imported dataset, re-validated like a fresh import."""
    path = Path(out_dir) / f"{symbol.upper()}_{timeframe.upper()}.csv"
    if not path.exists():
        raise DatasetError(f"no imported {timeframe.upper()} data for {symbol.upper()} "
                           f"({path}) — run scripts/import_candles.py first")
    return load_candles(path, tz="UTC")
