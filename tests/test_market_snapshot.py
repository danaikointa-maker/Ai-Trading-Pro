from types import SimpleNamespace

from packages.shared_schemas.models import Tick
from services.market_data.service import MarketDataService


class BrokenRegistry:
    def get(self, broker_id=None):
        return SimpleNamespace(id="demo", ticker=lambda _symbol: (_ for _ in ()).throw(RuntimeError("market closed")))


class WorkingRegistry:
    def get(self, broker_id=None):
        return SimpleNamespace(id="demo", ticker=lambda _symbol: Tick(
            t=1_700_000_100.0, bid=2001, ask=2002, spread_points=100, last=2001.5))


class QualityRegistry:
    def __init__(self, tick):
        self.tick = tick

    def get(self, broker_id=None):
        return SimpleNamespace(
            id="demo",
            health=lambda: SimpleNamespace(value="connected"),
            ticker=lambda _symbol: self.tick,
            candles=lambda _symbol, _timeframe, _limit: __import__("pandas").DataFrame(),
            adapter_type="real_mt5",
        )


def _quality_service(tick_time):
    service = MarketDataService(
        SimpleNamespace(risk_cfg=lambda: {"limits": {
            "data_staleness_seconds": 30,
            "data_future_tolerance_seconds": 2,
        }}),
        QualityRegistry(Tick(t=tick_time, bid=2000, ask=2001, spread_points=10, last=2000.5)),
        SimpleNamespace(),
    )
    service.set_virtual_now(1_700_000_000.0)
    return service


def test_data_quality_accepts_recent_tick():
    quality = _quality_service(1_700_000_001.0).data_quality("XAUUSD")
    assert quality["ok"] is True
    assert quality["staleness_seconds"] == 0.0
    assert quality["future_seconds"] == 1.0


def test_data_quality_rejects_stale_tick():
    quality = _quality_service(1_699_999_960.0).data_quality("XAUUSD")
    assert quality["ok"] is False
    assert quality["staleness_seconds"] == 40.0
    assert "stale" in quality["reason"]


def test_data_quality_rejects_future_tick_beyond_clock_skew_tolerance():
    quality = _quality_service(1_700_007_200.0).data_quality("XAUUSD")
    assert quality["ok"] is False
    assert quality["staleness_seconds"] == 0.0
    assert quality["future_seconds"] == 7200.0
    assert "timestamp is in the future" in quality["reason"]


def test_data_quality_tolerates_small_future_clock_skew():
    quality = _quality_service(1_700_000_002.0).data_quality("XAUUSD")
    assert quality["ok"] is True
    assert quality["future_seconds"] == 2.0


def test_last_quote_survives_service_restart_and_is_marked_stale(tmp_path):
    from packages.persistence.db import Database

    db = Database(str(tmp_path / "market.sqlite3"))
    try:
        first = MarketDataService(SimpleNamespace(), BrokenRegistry(), SimpleNamespace())
        first.db = db
        tick = Tick(t=1_700_000_000.0, bid=2000, ask=2001, spread_points=100, last=2000.5)
        first.on_ticks({"XAUUSD": tick})

        restarted = MarketDataService(SimpleNamespace(), BrokenRegistry(), SimpleNamespace())
        restarted.db = db
        latest = restarted.latest_quote("XAUUSD")
        assert latest == {"tick": tick.model_dump(), "stale": True, "source": "persisted"}
    finally:
        db.close()


def test_open_market_quote_replaces_last_known_quote(tmp_path):
    from packages.persistence.db import Database

    db = Database(str(tmp_path / "market-open.sqlite3"))
    try:
        service = MarketDataService(SimpleNamespace(), WorkingRegistry(), SimpleNamespace())
        service.db = db
        service.on_ticks({"XAUUSD": Tick(t=1_700_000_000.0, bid=2000, ask=2001,
                                         spread_points=100, last=2000.5)})
        latest = service.latest_quote("XAUUSD")
        assert latest["stale"] is False
        assert latest["source"] == "broker"
        assert latest["tick"]["t"] == 1_700_000_100.0
    finally:
        db.close()
