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
                                        tick_summary)
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


def test_import_writes_a_gzipped_store_and_a_manifest(tmp_path):
    src = _write_ticks(tmp_path / "x.csv", [("2026-01-05 10:00:00", 2000.0, 2000.3),
                                            ("2026-01-05 10:00:05", 2000.2, 2000.5)])
    summary = import_ticks(src, "xauusd", tmp_path, tz="UTC")
    stored = Path(summary["path"])
    assert stored.exists() and stored.name == "XAUUSD_ticks.csv.gz"
    assert gzip.decompress(stored.read_bytes()).decode().startswith("t,bid,ask")
    manifest = tick_summary(tmp_path, "XAUUSD")
    assert manifest and manifest["stored_rows"] == 2
    assert manifest["spread_points_median"] == pytest.approx(0.3)


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


def test_ticks_with_no_coverage_fall_back_and_are_counted(backtester, spec):
    ticks = _book([(999_000, 2000.0, 2000.3)])  # unrelated window
    pos, closed = backtester._manage_bar(_long_position(spec), _ambiguous_bar(), spec, 0.25, 0.0,
                                        ticks)
    assert closed is not None and closed.exit_reason == "stop loss"
    assert ticks.used == 0 and ticks.exhausted == 1


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
