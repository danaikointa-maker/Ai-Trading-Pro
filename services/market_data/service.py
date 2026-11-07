"""Market data service: candles, ticks, symbol specs and data-quality gates."""
from __future__ import annotations

import time
from typing import Any

import pandas as pd

from integrations.brokers.base import BrokerAdapter
from integrations.brokers.registry import BrokerRegistry
from packages.indicators.pipeline import enrich
from packages.shared_schemas.models import SymbolSpec, Tick
from packages.shared_schemas.settings import Settings
from services.market_data.news import NewsService


class StaleDataError(RuntimeError):
    pass


class MarketDataService:
    def __init__(self, settings: Settings, registry: BrokerRegistry, news: NewsService) -> None:
        self.settings = settings
        self.registry = registry
        self.news = news
        self._cache: dict[tuple[str, str, str], tuple[int, pd.DataFrame]] = {}
        self._last_ticks: dict[str, Tick] = {}
        self._virtual_now: float | None = None

    # ------------------------------------------------------------------ core
    @property
    def adapter(self) -> BrokerAdapter:
        return self.registry.get()

    def symbols(self, broker_id: str | None = None) -> list[str]:
        return self.registry.get(broker_id).symbol_names()

    def spec(self, symbol: str, broker_id: str | None = None) -> SymbolSpec:
        return self.registry.get(broker_id).symbol_spec(symbol)

    def set_virtual_now(self, now: float) -> None:
        self._virtual_now = now

    def now(self) -> float:
        return self._virtual_now if self._virtual_now is not None else time.time()

    def on_ticks(self, ticks: dict[str, Tick]) -> None:
        self._last_ticks.update(ticks)

    def ticker(self, symbol: str, broker_id: str | None = None) -> Tick:
        adapter = self.registry.get(broker_id)
        tick = adapter.ticker(symbol)
        self._last_ticks[symbol] = tick
        return tick

    def candles(self, symbol: str, timeframe: str = "M1", limit: int = 600,
                broker_id: str | None = None, force: bool = False) -> pd.DataFrame:
        adapter = self.registry.get(broker_id)
        key = (adapter.id, symbol, timeframe)
        raw = adapter.candles(symbol, timeframe, limit)
        last_t = int(raw["t"].iloc[-1]) if len(raw) else 0
        cached = self._cache.get(key)
        if cached and not force and cached[0] == last_t and len(cached[1]) >= min(limit, len(raw)):
            # The cache may hold a longer frame than this caller asked for (analysis
            # asks for 600 bars, /api/market/candles may ask for 20). Returning the
            # whole cache ignored `limit` and shipped 181 candles for limit=20.
            return cached[1].tail(limit).reset_index(drop=True).copy()
        enriched = enrich(raw)
        self._cache[key] = (last_t, enriched)
        return enriched.tail(limit).reset_index(drop=True).copy()

    def invalidate(self, symbol: str | None = None) -> None:
        for key in list(self._cache):
            if symbol is None or key[1] == symbol:
                self._cache.pop(key, None)

    # ---------------------------------------------------------- data quality
    def data_quality(self, symbol: str, timeframe: str = "M1", broker_id: str | None = None) -> dict[str, Any]:
        adapter = self.registry.get(broker_id)
        health = adapter.health().value
        try:
            tick = self.ticker(symbol, broker_id)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "health": health, "staleness_seconds": None,
                    "reason": f"ticker unavailable: {exc}", "spread_points": None}
        now = self.now()
        staleness = max(0.0, now - float(tick.t))
        limit = float(self.settings.risk_cfg().get("limits", {}).get("data_staleness_seconds", 30))
        df = self.candles(symbol, timeframe, 10, broker_id)
        gaps = 0
        if len(df) > 2:
            diffs = df["t"].diff().iloc[1:]
            gaps = int((diffs > 90).sum()) if timeframe == "M1" else 0
        ok = health in ("connected", "degraded") and staleness <= limit
        reason = ""
        if health not in ("connected", "degraded"):
            reason = f"broker health is {health}"
        elif staleness > limit:
            reason = f"price feed is stale ({staleness:.1f}s > {limit:.0f}s)"
        return {
            "ok": ok,
            "health": health,
            "staleness_seconds": round(staleness, 2),
            "spread_points": tick.spread_points,
            "gaps_last_10": gaps,
            "reason": reason,
            # The label must describe where the prices came from, not which adapter
            # happens to be loaded: with `feed_mode: replay` the adapter is still the
            # paper one, but the bars are imported candles.
            "feed": getattr(self, "feed_mode", None)
            or ("simulated" if adapter.adapter_type == "simulated_mt5" else "mt5-live"),
        }

    def require_fresh(self, symbol: str, timeframe: str = "M1") -> dict[str, Any]:
        quality = self.data_quality(symbol, timeframe)
        if not quality["ok"]:
            raise StaleDataError(quality.get("reason") or "market data is not fresh")
        return quality
