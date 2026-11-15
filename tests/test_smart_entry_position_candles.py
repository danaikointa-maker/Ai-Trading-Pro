"""Historical candles must be observed in time, scoped and immutable."""
from __future__ import annotations

import sqlite3

import pytest

from packages.persistence.db import Database
from packages.persistence.position_candles import PositionCandleLog
from packages.shared_schemas.models import Position


def position(ticket="C-1"):
    return Position(ticket=ticket, symbol="XAUUSD", direction="up", volume=0.1,
                    entry=2000, sl=1990, tp=2020, open_time=600,
                    current_price=2001, broker_id="demo")


def bar(stamp: int, **patch):
    return {"t": stamp, "o": 2000.0, "h": 2004.0, "l": 1998.0,
            "c": 2002.0, "v": 10.0} | patch


@pytest.fixture
def candles(tmp_path):
    db = Database(tmp_path / "candles.sqlite")
    identity = {"broker_id": "demo", "login": "123", "server": "Demo",
                "currency": "USD", "workspace_id": db.workspace_id}
    yield PositionCandleLog(db), db, identity
    db.close()


def test_closed_recent_bars_only_no_future_open_bar_or_posthoc_backfill(candles):
    log, db, owner = candles
    observed = [bar(0), bar(300), bar(600), bar(900), bar(1200)]
    assert log.capture(position=position(), account_identity=owner, bars=observed,
                       market_time=1400, feed_mode="replay") == 2
    rows = log.for_ticket(broker_id="demo", ticket="C-1", account_identity=owner,
                          symbol="XAUUSD")
    assert [row["t"] for row in rows["bars"]] == [600, 900]
    assert not rows["broker_tick_verified"] and not rows["complete"]
    assert all(row["t"] + 300 <= 1400 for row in rows["bars"])
    assert log.capture(position=position(), account_identity=owner, bars=observed,
                       market_time=1400, feed_mode="replay") == 0
    assert db.query("SELECT count(*) AS n FROM position_candles")[0]["n"] == 2


def test_conflicts_rollback_and_immutable_triggers(candles):
    log, db, owner = candles
    assert log.capture(position=position(), account_identity=owner, bars=[bar(600)],
                       market_time=1000, feed_mode="mt5-live") == 1
    with pytest.raises(ValueError, match="conflict"):
        log.capture(position=position(), account_identity=owner,
                    bars=[bar(900), bar(600, c=2003)], market_time=1300,
                    feed_mode="mt5-live")
    assert [r["t"] for r in db.query("SELECT t FROM position_candles")] == [600]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE position_candles SET symbol='EURUSD'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("DELETE FROM position_candles")


def test_cross_account_and_wrong_symbol_never_show_foreign_bars(candles):
    log, _, owner = candles
    log.capture(position=position(), account_identity=owner, bars=[bar(600)],
                market_time=1000, feed_mode="simulated")
    assert log.for_ticket(broker_id="demo", ticket="C-1",
                          account_identity={**owner, "login": "other"}, symbol="XAUUSD")["bars"] == []
    assert log.for_ticket(broker_id="demo", ticket="C-1", account_identity=owner,
                          symbol="EURUSD")["bars"] == []
    with pytest.raises(ValueError, match="conflict"):
        log.capture(position=position(), account_identity={**owner, "login": "other"},
                    bars=[bar(600)], market_time=1000, feed_mode="simulated")
    assert log.for_ticket(broker_id="demo", ticket="C-1",
                          account_identity=None, symbol="XAUUSD")["bars"] == []
    with pytest.raises(ValueError, match="unverified"):
        log.capture(position=position(), account_identity=None, bars=[bar(600)],
                    market_time=1000, feed_mode="simulated")


@pytest.mark.parametrize("invalid", [bar(600, h=1990), bar(600, c=float("nan")),
                                     bar(600, t=True), bar(600, v=-1)])
def test_invalid_ohlc_fails_closed(candles, invalid):
    log, db, owner = candles
    with pytest.raises(ValueError):
        log.capture(position=position(), account_identity=owner, bars=[invalid],
                    market_time=1000, feed_mode="mt5-live")
    assert db.query("SELECT * FROM position_candles") == []
