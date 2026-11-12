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