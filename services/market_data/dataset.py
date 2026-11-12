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
import io
import json
import re
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


def _read_any(path: Path, content: bytes | None = None) -> pd.DataFrame:
    """Read a CSV with whichever separator the file actually uses."""
    last: Exception | None = None
    for sep in _SEPARATORS:
        try:
            df = pd.read_csv(io.BytesIO(content) if content is not None else path, sep=sep, engine="python")
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
    return _normalise(raw, tz, digits)


def _normalise(raw: pd.DataFrame, tz: str, digits: int | None = None) -> pd.DataFrame:
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


def workspace_dataset_dir(configured: str | Path, selected: str | Path | None = None) -> Path:
    """Resolve a CLI selection without granting access to a foreign dataset root."""
    configured = Path(configured).expanduser()
    candidate = Path(selected).expanduser() if selected is not None else configured
    if (any(p.is_symlink() for p in (configured, *configured.parents, candidate, *candidate.parents))
            or not candidate.resolve().is_relative_to(configured.resolve())):
        raise DatasetError("dataset selection outside configured workspace")
    return candidate.resolve()


def _dataset_paths(out_dir: str | Path, symbol: str, timeframe: str) -> tuple[Path, Path, Path]:
    if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", symbol)
            or symbol.endswith(".") or symbol.upper().split(".")[0] in
            {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
            or not isinstance(timeframe, str) or timeframe.upper() not in TIMEFRAME_SECONDS):
        raise DatasetError("invalid dataset identifier")
    selected = Path(out_dir)
    if any(p.is_symlink() for p in (selected, *selected.parents)):
        raise DatasetError("dataset artifact path is linked")
    root = selected.resolve()
    csv = root / f"{symbol.upper()}_{timeframe.upper()}.csv"
    sidecar = csv.with_suffix(".meta.json")
    for path in (csv, sidecar):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise DatasetError("dataset artifact path outside root")
    return root, csv, sidecar


def import_candles(src: str | Path, symbol: str, out_dir: str | Path,
                   tz: str = "UTC", digits: int | None = None,
                   timeframe: str = "M1") -> dict[str, Any]:
    """Validate a file and store it as `{SYMBOL}_{TF}.csv` plus a metadata sidecar.

    The sidecar is not decoration: it records the source hash and every row the
    importer dropped, so a later "why is this run different" question has an answer.
    """
    src = Path(src)
    out_dir, dest, sidecar = _dataset_paths(out_dir, symbol, timeframe)
    if dest.exists() or sidecar.exists():
        raise DatasetError("dataset artifact exists; refusing overwrite or silent adoption")
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        source_bytes = src.read_bytes()
    except OSError:
        raise DatasetError("dataset source is unavailable") from None
    df = _normalise(_read_any(src, source_bytes), tz, digits)
    facts = describe(df, expected_seconds=TIMEFRAME_SECONDS.get(timeframe.upper(), 60))
    csv_bytes = df.to_csv(index=False).encode("utf-8")

    digest = hashlib.sha256(source_bytes).hexdigest()
    meta = {
        "schema": 1,
        "dataset_root": str(out_dir),
        "source_sha256": digest,
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "source_file": src.name,
        "source_sha256_16": digest[:16],
        "source_timezone": tz,
        "imported_at": int(time.time()),
        "csv": dest.name,
        **facts,
    }
    # Exclusive creation never replaces legacy evidence. Partial writes are left
    # untrusted: a missing/mismatched sidecar cannot be loaded.
    try:
        with dest.open("xb") as output:
            output.write(csv_bytes)
        with sidecar.open("x", encoding="utf-8") as output:
            output.write(json.dumps(meta, indent=2, ensure_ascii=False))
    except OSError:
        raise DatasetError("dataset artifact write failed; incomplete artifacts quarantined") from None
    return meta


def load_dataset(out_dir: str | Path, symbol: str, timeframe: str = "M1") -> pd.DataFrame:
    """Read back an imported dataset, re-validated like a fresh import."""
    root, path, sidecar = _dataset_paths(out_dir, symbol, timeframe)
    if not path.exists():
        raise DatasetError(f"no imported {timeframe.upper()} data for {symbol.upper()} "
                           f"({path}) — run scripts/import_candles.py first")
    try:
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        if (not isinstance(meta, dict) or meta.get("schema") != 1 or meta.get("dataset_root") != str(root)
                or meta.get("symbol") != symbol.upper() or meta.get("timeframe") != timeframe.upper()
                or meta.get("csv") != path.name):
            raise DatasetError("dataset provenance invalid; artifact quarantined")
        content = path.read_bytes()
    except (OSError, ValueError, UnicodeError):
        raise DatasetError("dataset provenance unavailable or invalid; artifact quarantined") from None
    if hashlib.sha256(content).hexdigest() != meta.get("csv_sha256"):
        raise DatasetError("dataset digest mismatch; artifact quarantined")
    return _normalise(_read_any(path, content), "UTC")
