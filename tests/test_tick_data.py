"""Tick data: import it, then let it decide what happened inside an ambiguous bar.

The backtester's conservative rule is "if a bar touched both the stop and a target,
assume the stop". That rule can turn a winner into a loser. These tests build exactly
such a bar and show the outcome flipping when real ticks say the target came first —
which is the only reason to import ticks at all.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

from packages.persistence.db import Database
from packages.shared_schemas.models import Direction, SymbolSpec, TradeMode
from services.backtest_engine.backtester import Backtester, SimPosition
from services.market_data.ticks import (TickBook, TickDataError, import_ticks, load_tick_csv,
                                        tick_layout, tick_summary)
from packages.shared_schemas.settings import reload_settings


# ------------------------------------------------------------------- import
def _write_ticks(path: Path, rows: list[tuple[str, float, float]]) -> Path:
    path.write_text("time,bid,ask\n" + "\n".join(f"{t},{b},{a}" for t, b, a in rows), "utf-8")
    return path


def test_import_normalises_timestamps_and_reports_drops(tmp_path):
    src = _write_ticks(tmp_path / "ticks.csv", [
        ("2026-01-05 10:00:00", 2000.0, 2000.3),
        ("2026-01-05 10:00:01", 2000.1, 2000.4),
        ("not-a-time", 2000.1, 2000.4),          # unparsed
        ("2026-01-05 10:00:02", 0.0, 2000.4),    # zero price
        ("2026-01-05 10:00:03", 2000.5, 2000.2),  # ask below bid
        ("2026-01-05 10:00:04", 2000.2, 2000.5),
        ("2026-01-05 10:00:04", 2000.3, 2000.6),  # duplicate timestamp
    ])
    frame, summary = load_tick_csv(src, tz="UTC")
    assert list(frame.columns) == ["t", "bid", "ask"]
    assert summary["rows_read"] == 7
    assert summary["rows_used"] == 3
    assert summary["dropped"] == {"unparsed timestamp": 1, "missing/zero price": 1,
                                  "ask below bid": 1, "duplicate timestamp": 1}
    assert frame["t"].is_monotonic_increasing
    # the *last* duplicate wins, so the freshest quote is the one kept
    assert frame["bid"].iloc[-1] == pytest.approx(2000.3)


def test_import_rejects_a_file_without_the_right_columns(tmp_path):
    src = tmp_path / "bad.csv"
    src.write_text("time,price\n2026-01-05 10:00:00,2000\n", "utf-8")
    with pytest.raises(TickDataError, match="missing"):
        load_tick_csv(src)


def test_import_writes_daily_files_and_a_manifest(tmp_path):
    src = _write_ticks(tmp_path / "x.csv", [("2026-01-05 10:00:00", 2000.0, 2000.3),
                                            ("2026-01-05 10:00:05", 2000.2, 2000.5)])
    summary = import_ticks(src, "xauusd", tmp_path, tz="UTC")
    assert summary["layout"] == "daily" and summary["days_covered"] == 1
    day = summary["days"][0]
    assert Path(day["path"]).exists()
    assert day["path"].endswith((".parquet", ".csv.gz"))
    assert day["rows"] == 2
    manifest = tick_summary(tmp_path, "XAUUSD")
    assert manifest and manifest["rows"] == 2 and manifest["layout"] == "daily"
    assert manifest["spread_points_median"] == pytest.approx(0.3)
    assert tick_layout(tmp_path, "XAUUSD") == "daily"
    book = TickBook.load(tmp_path, "XAUUSD")
    assert book is not None and book.layout == "daily"
    touch = book.first_touch(day["first_t"], day["last_t"] + 1, "up", 1999.0, [(0, 2000.1)])
    assert touch is not None and touch.kind == "tp" and touch.t == day["last_t"]


def test_legacy_single_file_layout_still_loads(tmp_path):
    src = _write_ticks(tmp_path / "x.csv", [("2026-01-05 10:00:00", 2000.0, 2000.3),
                                            ("2026-01-05 10:00:05", 2000.2, 2000.5)])
    summary = import_ticks(src, "xauusd", tmp_path, tz="UTC", layout="file")
    stored = Path(summary["path"])
    assert stored.exists() and stored.name == "XAUUSD_ticks.csv.gz"
    assert gzip.decompress(stored.read_bytes()).decode().startswith("t,bid,ask")
    assert tick_layout(tmp_path, "XAUUSD") == "file"
    book = TickBook.load(tmp_path, "XAUUSD")
    assert book is not None and book.layout == "memory" and len(book) == 2


# ------------------------------------------------------- which came first?
def _book(rows: list[tuple[int, float, float]]) -> TickBook:
    return TickBook(pd.DataFrame(rows, columns=["t", "bid", "ask"]))


def test_ticks_decide_that_the_target_came_first():
    book = _book([(100, 2000.0, 2000.4), (110, 2001.5, 2001.9), (120, 1999.0, 1999.4)])
    touch = book.first_touch(100, 400, "up", stop=1999.5, targets=[(0, 2001.0)])
    assert touch is not None and touch.kind == "tp" and touch.index == 0
    assert touch.t == 110


def test_ticks_decide_that_the_stop_came_first():
    book = _book([(100, 2000.0, 2000.4), (110, 1999.0, 1999.4), (120, 2001.5, 2001.9)])
    touch = book.first_touch(100, 400, "up", stop=1999.5, targets=[(0, 2001.0)])
    assert touch is not None and touch.kind == "stop"
    assert touch.t == 110


def test_short_positions_are_settled_on_the_ask():
    # A short exits at the ask: falling ask = profit, rising ask = stop.
    book = _book([(100, 2000.0, 2000.4), (110, 1998.0, 1998.4), (120, 2001.0, 2001.4)])
    touch = book.first_touch(100, 400, "down", stop=2000.8, targets=[(0, 1998.5)])
    assert touch is not None and touch.kind == "tp" and touch.t == 110


def test_no_ticks_in_the_window_is_none_not_a_guess():
    book = _book([(100, 2000.0, 2000.4)])
    assert book.first_touch(500, 800, "up", stop=1999.0, targets=[(0, 2001.0)]) is None


def test_book_stats_count_settled_and_missing_bars():
    book = _book([(100, 2000.0, 2000.4)])
    book.used, book.exhausted = 3, 2
    stats = book.stats()
    assert stats["bars_settled_by_ticks"] == 3 and stats["bars_without_ticks"] == 2
    assert stats["rows"] == 1


# ------------------------------------------- the outcome really flips
@pytest.fixture()
def spec():
    settings = reload_settings()
    return SymbolSpec(**settings.symbol_spec(settings.default_broker_id(), "XAUUSD"))


@pytest.fixture()
def backtester(tmp_path):
    settings = reload_settings()
    db = Database(str(tmp_path / "bt.sqlite3"))
    from services.risk_engine.engine import RiskEngine
    from services.risk_engine.planner import TradePlanner

    yield Backtester(settings, RiskEngine(settings, db), TradePlanner(settings.risk_cfg(),
                                                                     settings.strategy_cfg()))
    db.close()


def _long_position(spec: SymbolSpec) -> SimPosition:
    sl, tp = 1995.0, 2005.0
    return SimPosition(
        direction=Direction.up, entry=2000.0, sl=sl, sl_initial=sl,
        tps=[tp, 2010.0, 2015.0], volumes=[1.0, 0.0, 0.0], partials_done=0,
        remaining=1.0, initial_volume=1.0, opened_at=1000, entry_bar=1000,
        risk_amount=abs(2000.0 - sl) / spec.point * spec.value_per_point_per_lot,
        trade_mode=TradeMode.manual, strategy="test", signal_id="SIG123456",
    )


def _ambiguous_bar() -> pd.Series:
    """One M5 bar that swept both the stop (1995) and the target (2005)."""
    return pd.Series({"t": 1000, "o": 2000.0, "h": 2006.0, "l": 1994.0, "c": 2002.0, "v": 100.0})


def test_without_ticks_the_ambiguous_bar_books_a_loss(backtester, spec):
    pos, closed = backtester._manage_bar(_long_position(spec), _ambiguous_bar(), spec, 0.25, 0.0)
    assert pos is None and closed is not None
    assert closed.exit_reason == "stop loss"
    assert closed.pnl < 0


def test_with_ticks_saying_target_first_the_same_bar_books_a_win(backtester, spec):
    # price ran up to the target before ever trading down to the stop
    ticks = _book([(1000, 2000.0, 2000.3), (1010, 2003.0, 2003.3), (1020, 2005.5, 2005.8),
                   (1030, 1994.0, 1994.3)])
    pos, closed = backtester._manage_bar(_long_position(spec), _ambiguous_bar(), spec, 0.25, 0.0,
                                        ticks)
    assert pos is None and closed is not None
    assert closed.exit_reason == "take profit"
    assert closed.pnl > 0
    assert ticks.used == 1


def test_with_ticks_saying_stop_first_still_books_the_loss(backtester, spec):
    ticks = _book([(1000, 2000.0, 2000.3), (1010, 1994.5, 1994.8), (1020, 2005.5, 2005.8)])
    pos, closed = backtester._manage_bar(_long_position(spec), _ambiguous_bar(), spec, 0.25, 0.0,
                                        ticks)
    assert closed is not None and closed.exit_reason == "stop loss"
    assert closed.pnl < 0
    assert ticks.used == 1


def test_partial_ladder_is_booked_to_the_tick_that_actually_filled(backtester, spec):
    """TP1 first, then the stop on the remainder — neither all-win nor all-loss.

    A one-target-per-position view would call this either a win or a loss; the tick
    path books the partial that really filled and stops out the rest, which is a
    smaller loss than the conservative rule's full stop-out.
    """
    laddered = _long_position(spec)
    laddered.volumes = [0.4, 0.3, 0.3]  # 40% comes off at TP1
    ticks = _book([(1000, 2000.0, 2000.3), (1005, 2005.2, 2005.5), (1010, 1994.6, 1994.9)])
    _pos, closed = backtester._manage_bar(laddered, _ambiguous_bar(), spec, 0.25, 0.0, ticks)
    assert closed is not None and closed.exit_reason == "stop loss"
    assert ticks.used == 1

    _pos, conservative = backtester._manage_bar(_long_position(spec), _ambiguous_bar(),
                                                spec, 0.25, 0.0)
    assert closed.pnl > conservative.pnl  # the partial win offsets part of the loss
    assert closed.pnl < abs(conservative.pnl)  # and it is still a losing trade


def test_the_trade_is_the_same_whether_ticks_are_daily_or_one_file(backtester, spec, tmp_path):
    """Storage layout must not move a single number.

    The daily store reads lazily and the legacy store loads everything; both answer the
    same question about the same ticks, so the trade they settle has to be identical.
    """
    rows = [(1000, 2000.0, 2000.3), (1005, 2005.2, 2005.5), (1010, 1994.6, 1994.9)]
    src = _write_ticks(tmp_path / "same.csv",
                       [(pd.Timestamp(t, unit="s", tz="UTC").strftime("%Y-%m-%d %H:%M:%S"), b, a)
                        for t, b, a in rows])
    daily = import_ticks(src, "XAUUSD", tmp_path / "daily", tz="UTC")
    import_ticks(src, "XAUUSD", tmp_path / "single", tz="UTC", layout="file")
    assert daily["layout"] == "daily" and tick_layout(tmp_path / "single", "XAUUSD") == "file"

    outcomes, daily_stats = [], None
    for book in (TickBook.load(tmp_path / "daily", "XAUUSD"),
                 TickBook.load(tmp_path / "single", "XAUUSD")):
        position = _long_position(spec)
        position.volumes = [0.4, 0.3, 0.3]
        _pos, closed = backtester._manage_bar(position, _ambiguous_bar(), spec, 0.25, 0.0, book)
        outcomes.append((closed.exit_reason, round(closed.pnl, 10), book.used, book.exhausted,
                         book.first_touch(1000, 1300, "up", 1995.0, [(0, 2005.0)])))
        if book.layout == "daily":
            daily_stats = book.stats()
    assert outcomes[0] == outcomes[1], "the layout changed the trade"
    assert outcomes[0][2] == 1 and outcomes[0][3] == 0
    # the daily book read exactly the one day it needed, and says which
    assert daily_stats["days_loaded"] == 1
    assert daily_stats["days_used"] == ["1970-01-01"]
    assert daily_stats["ticks_in_window"] is None or daily_stats["ticks_in_window"] >= 0


def test_a_bar_outside_tick_coverage_falls_back_in_daily_layout_too(backtester, spec, tmp_path):
    """A gap in the imported days must keep the conservative rule, and be counted."""
    src = _write_ticks(tmp_path / "gap.csv",
                       [("2026-01-05 10:00:00", 2010.0, 2010.3),
                        ("2026-01-05 10:00:01", 2010.2, 2010.5)])
    import_ticks(src, "XAUUSD", tmp_path, tz="UTC")
    book = TickBook.load(tmp_path, "XAUUSD")
    assert book.layout == "daily"
    _pos, closed = backtester._manage_bar(_long_position(spec), _ambiguous_bar(), spec, 0.25, 0.0,
                                          book)
    assert closed.exit_reason == "stop loss"   # conservative rule kept
    assert book.used == 0 and book.exhausted == 1  # and the guess is counted, never silent


def test_ticks_with_no_coverage_fall_back_and_are_counted(backtester, spec):
    ticks = _book([(999_000, 2000.0, 2000.3)])  # unrelated window
    pos, closed = backtester._manage_bar(_long_position(spec), _ambiguous_bar(), spec, 0.25, 0.0,
                                        ticks)
    assert closed is not None and closed.exit_reason == "stop loss"
    assert ticks.used == 0 and ticks.exhausted == 1


def test_the_note_says_when_the_ticks_do_not_overlap_the_run(backtester, spec, tmp_path):
    """A store full of ticks for other dates must not read as "ticks were consulted"."""
    src = _write_ticks(tmp_path / "elsewhere.csv",
                       [("2026-01-05 10:00:00", 2010.0, 2010.3),
                        ("2026-01-05 10:00:01", 2010.2, 2010.5)])
    import_ticks(src, "XAUUSD", tmp_path, tz="UTC")
    book = TickBook.load(tmp_path, "XAUUSD")
    book.cover_window(1000, 1300)          # the run's window is far from the ticks
    note = backtester._intra_bar_note(book)
    assert "none of the imported ticks fall inside this run's window" in note
    assert book.stats()["symbol"] == "XAUUSD"
    assert book.stats()["ticks_in_window"] == 0
    assert book.stats()["days_in_window"] == 0

    covered = TickBook.load(tmp_path, "XAUUSD")
    covered.cover_window(int(pd.Timestamp("2026-01-05 10:00:00", tz="UTC").timestamp()),
                         int(pd.Timestamp("2026-01-05 10:00:05", tz="UTC").timestamp()))
    assert covered.stats()["ticks_in_window"] == 2
    assert "none of the imported ticks" not in backtester._intra_bar_note(covered)


# ------------------------------------------------------------ http surface
def test_tick_status_endpoint_reports_absence_honestly(client, token):
    res = client.get("/api/datasets/ticks/status",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    body = res.json()
    assert "ticks" in body
    assert body["used_for_intra_bar_ordering"] is False or isinstance(body["ticks"], list)


def test_report_says_how_ambiguous_bars_were_settled(client, token):
    import time

    headers = {"Authorization": f"Bearer {token}"}
    started = client.post("/api/backtests", json={"symbol": "XAUUSD", "bars": 2000},
                          headers=headers)
    assert started.status_code == 200
    job_id = started.json()["job_id"]
    for _ in range(120):
        job = client.get(f"/api/backtests/jobs/{job_id}", headers=headers).json()
        if job["state"] in ("done", "error"):
            break
        time.sleep(0.25)
    assert job["state"] == "done", job
    report = client.get(f"/api/backtests/{job['report_id']}", headers=headers).json()
    intra = report["diagnostics"]["intra_bar"]
    assert intra["mode"] == "conservative" or "bars_settled_by_ticks" in intra
    note = [a for a in report["assumptions"] if "Intra-bar order" in a]
    assert note, "the report must say how ambiguous bars were settled"
    assert json.dumps(report)  # serialisable
