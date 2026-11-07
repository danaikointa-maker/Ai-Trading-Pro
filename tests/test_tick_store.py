"""Daily tick storage: only the days a question needs are ever read.

A real tick export is millions of rows per day, so "load the file and index it" stops
working the moment real data arrives. These tests pin the property that matters:
a backtest window over one day reads one day, construction reads none, and a gap in
coverage is reported instead of silently settled.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from services.market_data.tick_store import (TickStore, TickStoreError, available_days,
                                             coverage, day_key, day_path, prune_days,
                                             pyarrow_available, read_day, write_days)
from services.market_data.ticks import TickBook, import_ticks, load_tick_csv, tick_layout

DAY1 = pd.Timestamp("2026-01-05 09:00:00", tz="UTC")
DAY2 = pd.Timestamp("2026-01-06 09:00:00", tz="UTC")
DAY3 = pd.Timestamp("2026-01-07 09:00:00", tz="UTC")


def _ticks(start: pd.Timestamp, rows: int, *, base: float = 2000.0,
           step: float = 0.2, spread: float = 0.25) -> pd.DataFrame:
    times = [int(start.timestamp()) + i for i in range(rows)]
    bid = [round(base + i * step, 5) for i in range(rows)]
    return pd.DataFrame({"t": times, "bid": bid,
                         "ask": [round(b + spread, 5) for b in bid]})


def _write_csv(path: Path, frames: list[pd.DataFrame]) -> Path:
    merged = pd.concat(frames).sort_values("t")
    rows = [
        f"{pd.Timestamp(int(t), unit='s', tz='UTC').strftime('%Y-%m-%d %H:%M:%S')},{b},{a}"
        for t, b, a in zip(merged["t"], merged["bid"], merged["ask"])
    ]
    path.write_text("time,bid,ask\n" + "\n".join(rows), "utf-8")
    return path


@pytest.fixture()
def three_days(tmp_path) -> dict:
    csv = _write_csv(tmp_path / "export.csv",
                     [_ticks(DAY1, 120), _ticks(DAY2, 90, base=2010.0),
                      _ticks(DAY3, 60, base=2020.0)])
    summary = import_ticks(csv, "XAUUSD", tmp_path, tz="UTC")
    return {"root": tmp_path, "summary": summary, "csv": csv}


# --------------------------------------------------------------------- layout
def test_import_splits_by_utc_day_and_reports_coverage(three_days):
    summary = three_days["summary"]
    assert summary["layout"] == "daily"
    assert [d["day"] for d in summary["days"]] == ["2026-01-05", "2026-01-06", "2026-01-07"]
    assert [d["rows"] for d in summary["days"]] == [120, 90, 60]
    assert summary["rows"] == 270

    cov = coverage(three_days["root"], "XAUUSD")
    assert cov["days_covered"] == 3
    assert cov["rows"] == 270
    assert cov["first_t"] == int(DAY1.timestamp())
    assert cov["last_t"] == int(DAY3.timestamp()) + 59


def test_each_day_file_holds_only_that_day(three_days):
    assert available_days(three_days["root"], "XAUUSD") == ["2026-01-05", "2026-01-06",
                                                            "2026-01-07"]
    for day in ("2026-01-05", "2026-01-06", "2026-01-07"):
        frame, fmt = read_day(three_days["root"], "XAUUSD", day)
        assert all(day_key(t) == day for t in frame["t"])
        assert fmt in ("parquet", "csv.gz")
        assert frame["t"].is_monotonic_increasing


def test_parquet_is_used_when_pyarrow_is_installed(three_days):
    days = available_days(three_days["root"], "XAUUSD")
    suffixes = {Path(day_path(three_days["root"], "XAUUSD", d,
                              "parquet" if pyarrow_available() else "csv.gz")).exists()
                for d in days}
    assert suffixes == {True}


# ------------------------------------------------------------- lazy reading
def test_building_a_book_reads_no_day_files(three_days):
    store = TickStore(three_days["root"], "XAUUSD")
    assert len(store.days) == 3
    assert store.reads == 0, "the manifest already answers the day ranges"


def test_only_the_needed_day_is_read(three_days):
    store = TickStore(three_days["root"], "XAUUSD")
    start = int(DAY2.timestamp())
    times, bid, _ = store.window(start, start + 10)
    assert len(times) == 10
    assert store.reads == 1
    assert store.days_for(start, start + 10) == ["2026-01-06"]
    # a window spanning two days reads exactly those two
    span = store.window(int(DAY2.timestamp()) + 80, int(DAY3.timestamp()) + 10)
    assert len(span[0]) == 10 + 10
    assert store.reads == 2, "day 2 was already cached; only day 3 needed a read"


def test_a_window_between_days_reads_nothing(three_days):
    store = TickStore(three_days["root"], "XAUUSD")
    gap_start = int(DAY1.timestamp()) + 500          # long after day 1 ends
    gap_end = int(DAY2.timestamp()) - 500            # before day 2 starts
    assert store.window(gap_start, gap_end)[0].size == 0
    assert store.reads == 0
    assert store.missing_days == 1


def test_cache_is_bounded(three_days):
    store = TickStore(three_days["root"], "XAUUSD", cache_days=1)
    for day in store.days:
        store.day_frame(day)
    assert len(store._cache) == 1
    assert store.reads == 3


# ------------------------------------------------------------------ querying
def test_first_touch_works_across_the_daily_split(three_days):
    store = TickStore(three_days["root"], "XAUUSD")
    start = int(DAY1.timestamp()) + 10           # bid 2002.0
    end = int(DAY1.timestamp()) + 15
    touch = store.first_touch(start, end, "up", stop=1990.0, targets=[(0, 2002.6)])
    assert touch is not None and touch.kind == "tp"
    # a stop above the market is hit immediately for a short (exit price = ask)
    stop = store.first_touch(start, end, "down", stop=2000.0, targets=[])
    assert stop is not None and stop.kind == "stop" and stop.t == start


def test_tickbook_reports_the_daily_layout_in_its_stats(three_days):
    book = TickBook.load(three_days["root"], "XAUUSD")
    assert book.layout == "daily"
    stats = book.stats()
    assert stats["layout"] == "daily" and stats["days"] == 3
    assert stats["first_t"] == int(DAY1.timestamp())
    book.used, book.exhausted = 2, 1
    assert book.stats()["bars_settled_by_ticks"] == 2


# -------------------------------------------------------------------- import
def test_chunked_import_matches_a_single_pass(three_days, tmp_path):
    """Reading in chunks must not change the data — only the peak memory."""
    other = tmp_path / "chunked"
    summary = import_ticks(three_days["csv"], "XAUUSD", other, tz="UTC", chunk_rows=50)
    assert summary["rows"] == three_days["summary"]["rows"]
    assert [d["sha256"] for d in summary["days"]] == \
           [d["sha256"] for d in three_days["summary"]["days"]]


def test_duplicates_across_chunks_are_dropped_and_counted(tmp_path):
    rows = ["time,bid,ask"]
    for i in range(10):
        stamp = pd.Timestamp(int(DAY1.timestamp()) + i, unit="s", tz="UTC")
        rows.append(f"{stamp.strftime('%Y-%m-%d %H:%M:%S')},{2000 + i * 0.1:.2f},{2000.3 + i * 0.1:.2f}")
    # the same second appears again in a later chunk
    rows.append(f"{pd.Timestamp(int(DAY1.timestamp()) + 9, unit='s', tz='UTC').strftime('%Y-%m-%d %H:%M:%S')},2001.0,2001.3")
    csv = tmp_path / "dupes.csv"
    csv.write_text("\n".join(rows), "utf-8")

    summary = import_ticks(csv, "XAUUSD", tmp_path / "out", tz="UTC", chunk_rows=5)
    assert summary["rows"] == 10
    assert summary["dropped"]["duplicate timestamp"] == 1


def test_bad_rows_are_counted_per_reason_when_streamed(tmp_path):
    csv = tmp_path / "mixed.csv"
    csv.write_text(
        "time,bid,ask\n"
        "2026-01-05 10:00:00,2000.0,2000.3\n"
        "not-a-time,2000.1,2000.4\n"
        "2026-01-05 10:00:01,0,2000.4\n"
        "2026-01-05 10:00:02,2000.5,2000.2\n"
        "2026-01-05 10:00:03,2000.2,2000.5\n", "utf-8")
    summary = import_ticks(csv, "XAUUSD", tmp_path / "out", tz="UTC")
    assert summary["rows"] == 2
    assert summary["dropped"] == {"unparsed timestamp": 1, "missing/zero price": 1,
                                  "ask below bid": 1}


def test_semicolon_separated_export_is_accepted(tmp_path):
    csv = tmp_path / "semi.csv"
    csv.write_text("Time;Bid;Ask\n2026-01-05 10:00:00;2000.0;2000.3\n"
                   "2026-01-05 10:00:01;2000.1;2000.4\n", "utf-8")
    frame, summary = load_tick_csv(csv, tz="UTC")
    assert summary["rows_used"] == 2 and list(frame.columns) == ["t", "bid", "ask"]


def test_unknown_format_is_refused(tmp_path):
    frame = _ticks(DAY1, 3)
    with pytest.raises(TickStoreError, match="unknown tick format"):
        write_days(tmp_path, "XAUUSD", frame, fmt="feather")


def test_a_second_import_adds_days_instead_of_replacing_the_index(three_days, tmp_path):
    later = _write_csv(tmp_path / "later.csv", [_ticks(pd.Timestamp("2026-01-09", tz="UTC"), 20)])
    summary = import_ticks(later, "XAUUSD", three_days["root"], tz="UTC")
    assert summary["days_covered"] == 4, "the earlier three days must stay in the manifest"
    cov = coverage(three_days["root"], "XAUUSD")
    assert cov["rows"] == 290 and [d["day"] for d in cov["days"]][-1] == "2026-01-09"
    # re-importing the same day replaces its entry rather than double-counting it
    again = import_ticks(three_days["csv"], "XAUUSD", three_days["root"], tz="UTC")
    assert again["rows"] == 290


# -------------------------------------------------------------------- prune
def test_prune_keeps_the_newest_days(three_days):
    out = prune_days(three_days["root"], "XAUUSD", keep_days=2)
    assert [d["day"] for d in out["removed"]] == ["2026-01-05"]
    assert out["remaining"] == ["2026-01-06", "2026-01-07"]
    with pytest.raises(TickStoreError, match="keep_days"):
        prune_days(three_days["root"], "XAUUSD", keep_days=0)


def test_random_windows_answer_identically_in_both_layouts(three_days, tmp_path):
    """50 random windows x 3 shapes of question, daily store vs one-file store."""
    import random

    import_ticks(three_days["csv"], "XAUUSD", tmp_path / "one", tz="UTC", layout="file")
    daily = TickBook.load(three_days["root"], "XAUUSD")
    single = TickBook.load(tmp_path / "one", "XAUUSD")
    first, last = daily.stats()["first_t"], daily.stats()["last_t"]
    rng = random.Random(3)
    shapes = (("up", 1995.0, [(0, 2010.0)]), ("down", 2100.0, [(0, 1990.0)]),
              ("up", 1999.9, [(0, 2000.5), (1, 2015.0)]))
    checked = 0
    for _ in range(50):
        start = rng.randint(first, last)
        end = start + rng.choice([1, 5, 60, 3600])
        for shape in shapes:
            assert daily.first_touch(start, end, *shape) == single.first_touch(start, end, *shape)
            checked += 1
    assert checked == 150


# -------------------------------------------------------------- http surface
@pytest.fixture()
def isolated_datasets(client, tmp_path):
    """Point the runtime at a scratch datasets dir so no other test sees these ticks."""
    runtime = client.app.state.runtime
    original = runtime.settings.paths["datasets"]
    runtime.settings.paths["datasets"] = tmp_path
    try:
        yield runtime, tmp_path
    finally:
        runtime.settings.paths["datasets"] = original


def test_tick_status_reports_daily_coverage(client, token, isolated_datasets, tmp_path):
    """The dashboard reads this to answer 'how much real tick data do we have?'."""
    runtime, datasets = isolated_datasets
    csv = _write_csv(tmp_path / "status.csv", [_ticks(DAY1, 30), _ticks(DAY3, 30)])
    import_ticks(csv, "XAUUSD", datasets, tz="UTC")

    res = client.get("/api/datasets/ticks/status?symbol=XAUUSD",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    entry = next(t for t in body["ticks"] if t["symbol"] == "XAUUSD")
    assert entry["available"] is True
    assert entry["layout"] == "daily"
    assert entry["days_covered"] == 2
    assert entry["rows_loaded"] == 0, "status must not read a single day file"
    assert entry["gaps"] == ["2026-01-06"], "a missing interior day has to be visible"
    assert body["used_for_intra_bar_ordering"] is True
    assert {d["day"] for d in entry["days"]} == {"2026-01-05", "2026-01-07"}
    assert isinstance(runtime, object)


def test_prune_refuses_days_a_backtest_used_and_is_audited(client, token, isolated_datasets,
                                                           tmp_path):
    runtime, datasets = isolated_datasets
    csv = _write_csv(tmp_path / "prune.csv", [_ticks(DAY1, 10), _ticks(DAY2, 10),
                                              _ticks(DAY3, 10)])
    import_ticks(csv, "XAUUSD", datasets, tz="UTC")
    runtime.db.execute(
        "INSERT OR REPLACE INTO backtests(id, created_at, symbol, strategy, payload) "
        "VALUES(?,?,?,?,?)",
        ("BT-REF-1", "2026-01-08T00:00:00", "XAUUSD", "trend",
         json.dumps({"symbol": "XAUUSD",
                     "dataset": {"ticks": {"symbol": "XAUUSD", "days_used": ["2026-01-05"]}}})),
    )
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post("/api/datasets/ticks/prune?symbol=XAUUSD&keep_days=2", headers=headers)
    assert res.status_code == 409
    assert "2026-01-05" in res.json()["detail"]
    assert available_days(datasets, "XAUUSD") == ["2026-01-05", "2026-01-06", "2026-01-07"]

    forced = client.post("/api/datasets/ticks/prune?symbol=XAUUSD&keep_days=2&force=true",
                         headers=headers)
    assert forced.status_code == 200
    body = forced.json()
    assert [r["day"] for r in body["removed"]] == ["2026-01-05"]
    assert available_days(datasets, "XAUUSD") == ["2026-01-06", "2026-01-07"]
    assert body["rows_after"] == 20
    audit = [a for a in runtime.db.query("SELECT action, detail FROM audit "
                                         "ORDER BY id DESC LIMIT 10")
             if a["action"] == "datasets.ticks_prune"]
    assert audit and json.loads(audit[0]["detail"])["forced"] is True
    after = client.get("/api/datasets/ticks/status?symbol=XAUUSD", headers=headers).json()
    assert after["ticks"][0]["days_covered"] == 2


def test_prune_needs_admin(client, auth, isolated_datasets, tmp_path):
    runtime, datasets = isolated_datasets
    csv = _write_csv(tmp_path / "v.csv", [_ticks(DAY1, 5), _ticks(DAY2, 5)])
    import_ticks(csv, "XAUUSD", datasets, tz="UTC")
    created = client.post("/api/users", json={"email": "tickviewer@no7.ai",
                                              "password": "longenough1", "role": "viewer"},
                          headers=auth)
    assert created.status_code == 200, created.text
    try:
        login = client.post("/api/auth/login", json={"email": "tickviewer@no7.ai",
                                                     "password": "longenough1"})
        viewer = {"Authorization": f"Bearer {login.json()['token']}"}
        res = client.post("/api/datasets/ticks/prune?symbol=XAUUSD&keep_days=1", headers=viewer)
        assert res.status_code == 403
        assert available_days(datasets, "XAUUSD") == ["2026-01-05", "2026-01-06"]
        # a viewer may still read the coverage
        assert client.get("/api/datasets/ticks/status?symbol=XAUUSD",
                          headers=viewer).status_code == 200
    finally:
        client.delete("/api/users/tickviewer@no7.ai", headers=auth)


def test_gzipped_legacy_file_still_imports_and_loads(tmp_path):
    """An export written by the first version of the importer keeps working."""
    src = _write_csv(tmp_path / "legacy.csv", [_ticks(DAY1, 5)])
    path = tmp_path / "ticks" / "XAUUSD_ticks.csv.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame, _ = load_tick_csv(src, tz="UTC")
    path.write_bytes(gzip.compress(frame.to_csv(index=False).encode(), mtime=0))
    assert tick_layout(tmp_path, "XAUUSD") == "file"
    book = TickBook.load(tmp_path, "XAUUSD")
    assert book is not None and len(book) == 5
