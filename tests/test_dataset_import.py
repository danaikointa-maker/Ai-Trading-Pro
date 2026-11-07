"""Imported candles decide whether any number in the product means anything.

The importer's job is to be boring and strict: read the file the broker wrote,
put the times in UTC, and refuse rather than silently shift or drop data. Two
bugs this suite exists to prevent: pandas reading a bare epoch number as
nanoseconds (which collapses every bar into one), and naive timestamps being
taken as UTC (which shifts the whole series by the broker's offset).
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from services.market_data.dataset import (DatasetError, describe, import_candles,
                                          load_candles, load_dataset)


def _rows(n: int = 12, start: str = "2026-09-01 00:00:00") -> list[tuple]:
    out = []
    times = pd.date_range(start, periods=n, freq="min")
    price = 4200.0
    for i, ts in enumerate(times):
        o = price
        c = round(price * (1 + ((i % 5) - 2) / 5000), 2)
        out.append((ts, round(o, 2), round(max(o, c) + 0.3, 2),
                    round(min(o, c) - 0.3, 2), c, 100 + i))
        price = c
    return out


def _write_mt5(path, rows):
    """MT5 'Save as' shape: <DATE> <TIME> <OPEN> ... tab separated."""
    lines = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>"]
    for ts, o, h, l, c, v in rows:
        lines.append(f"{ts:%Y.%m.%d}\t{ts:%H:%M:%S}\t{o}\t{h}\t{l}\t{c}\t{v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_generic(path, rows, sep=","):
    df = pd.DataFrame([[ts.strftime("%Y-%m-%d %H:%M:%S"), o, h, l, c, v]
                       for ts, o, h, l, c, v in rows],
                      columns=["time", "open", "high", "low", "close", "volume"])
    df.to_csv(path, sep=sep, index=False)
    return path


# --------------------------------------------------------------------- parsing
def test_mt5_export_with_split_date_and_time(tmp_path):
    path = _write_mt5(tmp_path / "mt5.csv", _rows())
    df = load_candles(path, tz="UTC")
    assert list(df.columns) == ["t", "o", "h", "l", "c", "v"]
    assert len(df) == 12
    assert df["t"].iloc[0] == int(pd.Timestamp("2026-09-01 00:00:00", tz="UTC").timestamp())
    assert df["t"].diff().dropna().eq(60).all(), "bars are one minute apart"


def test_generic_header_and_semicolon_separator(tmp_path):
    path = _write_generic(tmp_path / "generic.csv", _rows(), sep=";")
    df = load_candles(path, tz="UTC")
    assert len(df) == 12
    assert df["o"].iloc[0] == pytest.approx(4200.0)


def test_epoch_seconds_round_trip(tmp_path):
    """A normalised file read back must not lose its bars to unit guessing."""
    df = load_candles(_write_mt5(tmp_path / "a.csv", _rows()), tz="UTC")
    once = tmp_path / "once.csv"
    df.to_csv(once, index=False)
    again = load_candles(once, tz="UTC")
    assert again["t"].tolist() == df["t"].tolist()
    assert again["c"].tolist() == df["c"].tolist()


def test_naive_timestamps_use_the_named_timezone(tmp_path):
    """Bangkok is UTC+7: the same wall clock must land 7 hours earlier in UTC."""
    rows = _rows(4, start="2026-09-01 09:00:00")
    as_utc = load_candles(_write_generic(tmp_path / "u.csv", rows), tz="UTC")
    as_bkk = load_candles(_write_generic(tmp_path / "b.csv", rows), tz="Asia/Bangkok")
    assert as_utc["t"].iloc[0] - as_bkk["t"].iloc[0] == 7 * 3600


# ------------------------------------------------------------------ validation
def test_duplicate_bars_are_collapsed_and_counted(tmp_path):
    rows = _rows()
    rows.insert(5, rows[4])          # broker re-sent a bar
    df = load_candles(_write_mt5(tmp_path / "dup.csv", rows), tz="UTC")
    assert len(df) == 12
    assert df.attrs["dropped_duplicates"] == 1
    assert df["t"].is_monotonic_increasing


def test_broken_ohlc_rows_are_dropped_and_counted(tmp_path):
    rows = _rows()
    ts, o, h, l, c, v = rows[3]
    rows[3] = (ts, o, o - 5.0, o - 1.0, c, v)   # high below open
    df = load_candles(_write_mt5(tmp_path / "bad.csv", rows), tz="UTC")
    assert len(df) == 11
    assert df.attrs["dropped_invalid"] == 1


def test_unsorted_file_is_sorted(tmp_path):
    rows = _rows()
    rows[0], rows[1] = rows[1], rows[0]
    df = load_candles(_write_mt5(tmp_path / "unsorted.csv", rows), tz="UTC")
    assert df["t"].is_monotonic_increasing


def test_missing_price_column_is_refused(tmp_path):
    path = tmp_path / "nope.csv"
    path.write_text("time,open,high,close\n2026-09-01 00:00:00,1,2,1.5\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="missing price column"):
        load_candles(path, tz="UTC")


def test_unparseable_timestamps_are_refused_not_dropped(tmp_path):
    path = tmp_path / "badtime.csv"
    path.write_text("time,open,high,low,close\nyesterday,1,2,0.5,1.5\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="timestamp"):
        load_candles(path, tz="UTC")


def test_all_rows_invalid_is_an_error(tmp_path):
    path = tmp_path / "garbage.csv"
    path.write_text("time,open,high,low,close\n2026-09-01 00:00:00,0,0,0,0\n", encoding="utf-8")
    with pytest.raises(DatasetError):
        load_candles(path, tz="UTC")


def test_unknown_timezone_is_reported(tmp_path):
    with pytest.raises(DatasetError, match="localise"):
        load_candles(_write_generic(tmp_path / "tz.csv", _rows()), tz="Mars/Olympus")


# --------------------------------------------------------------------- import
def test_import_writes_a_sidecar_with_the_facts(tmp_path):
    meta = import_candles(_write_mt5(tmp_path / "src.csv", _rows()), "XAUUSD",
                          tmp_path / "out", tz="UTC")
    sidecar = tmp_path / "out" / "XAUUSD_M1.meta.json"
    assert sidecar.exists()
    on_disk = json.loads(sidecar.read_text(encoding="utf-8"))
    assert on_disk["rows"] == 12 == meta["rows"]
    assert on_disk["dropped_duplicates"] == 0
    assert on_disk["source_sha256_16"]
    assert on_disk["from_iso"].endswith("+00:00")


def test_load_dataset_round_trips_what_was_imported(tmp_path):
    src = _write_mt5(tmp_path / "src.csv", _rows())
    import_candles(src, "XAUUSD", tmp_path / "out", tz="UTC")
    df = load_dataset(tmp_path / "out", "XAUUSD")
    assert len(df) == 12
    assert df["t"].iloc[0] == int(pd.Timestamp("2026-09-01 00:00:00", tz="UTC").timestamp())


def test_load_dataset_explains_an_empty_directory(tmp_path):
    with pytest.raises(DatasetError, match="import_candles"):
        load_dataset(tmp_path, "EURUSD")


def test_describe_counts_gaps(tmp_path):
    rows = [r for r in _rows(6) if r[0].minute != 2]   # remove one bar -> a gap
    df = load_candles(_write_mt5(tmp_path / "gap.csv", rows), tz="UTC")
    facts = describe(df)
    assert facts["gaps"] == 1
    assert facts["largest_gap_minutes"] == 2.0
