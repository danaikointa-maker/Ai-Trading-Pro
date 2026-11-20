"""Market data service: candles, ticks, symbol specs and data-quality gates."""
from __future__ import annotations

import math
import hashlib
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
    def __init__(self, settings: Settings, registry: BrokerRegistry, news: NewsService, db=None) -> None:
        self.settings = settings
        self.registry = registry
        self.news = news
        self.db = db
        self._cache: dict[tuple[str, str, str], tuple[int, pd.DataFrame]] = {}
        self._last_ticks: dict[str, Tick] = {}
        self._virtual_now: float | None = None
        self.publisher = dict(getattr(settings, "market_data", {}).get("mt5_publisher") or {})
        scope = (str(self.publisher.get("account_id") or "default") + "\0"
                 + str(self.publisher.get("expected_login") or "") + "\0"
                 + str(self.publisher.get("expected_server") or ""))
        self._publisher_key = ("mt5-market-publisher:" + hashlib.sha256(
            scope.encode("utf-8")).hexdigest()[:16])
        saved = self.db.kv_get(self._publisher_key) if self.db is not None else None
        self._publisher_snapshot = saved.get("snapshot") if isinstance(saved, dict) else None
        self._publisher_received_at = float(saved.get("received_at") or 0) if isinstance(saved, dict) else 0.0

    # ------------------------------------------------------------------ core
    @property
    def adapter(self) -> BrokerAdapter:
        return self.registry.get()

    @property
    def effective_mode(self) -> str:
        if self.publisher.get("enabled"):
            return "mt5_demo_publisher" if self._publisher_fresh() else "mt5_demo_publisher_stale"
        return str(getattr(self, "feed_mode", "simulate"))

    def symbols(self, broker_id: str | None = None) -> list[str]:
        return self.registry.get(broker_id).symbol_names()

    def spec(self, symbol: str, broker_id: str | None = None) -> SymbolSpec:
        if self._publisher_fresh():
            raw = (self._publisher_snapshot.get("specs") or {}).get(symbol)
            if raw:
                return SymbolSpec(**raw)
        return self.registry.get(broker_id).symbol_spec(symbol)

    def set_virtual_now(self, now: float) -> None:
        self._virtual_now = now

    def now(self) -> float:
        return self._virtual_now if self._virtual_now is not None else time.time()

    def on_ticks(self, ticks: dict[str, Tick]) -> None:
        self._last_ticks.update(ticks)
        if self.db is not None:
            broker_id = self.registry.get().id
            for symbol, tick in ticks.items():
                self.db.kv_set(f"market-last-quote:{broker_id}:{symbol}", tick.model_dump())

    def publish_mt5_snapshot(self, payload: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
        """Store a data-only MT5 Demo snapshot; no position or command fields are accepted."""
        cfg = self.publisher
        if not cfg.get("enabled"):
            raise ValueError("MT5 market publisher is disabled")
        if not cfg.get("expected_login") or not cfg.get("expected_server") or not cfg.get("symbols"):
            raise ValueError("MT5 market publisher Demo identity and symbol allowlist are not configured")
        identity = payload["identity"]
        if (str(identity.get("login") or "") != str(cfg.get("expected_login") or "")
                or str(identity.get("server") or "") != str(cfg.get("expected_server") or "")
                or identity.get("trade_mode") != "demo" or identity.get("connected") is not True):
            raise ValueError("MT5 Demo identity is missing or mismatched")
        current = time.time() if now is None else float(now)
        try:
            captured, server, utc = (float(payload[key])
                                     for key in ("captured_at", "server_time", "utc_time"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("snapshot timestamp anchors are required") from exc
        max_age = float(cfg.get("max_snapshot_age_seconds", 15))
        if (not all(math.isfinite(v) for v in (captured, server, utc)) or captured > current + 2
                or current - captured > max_age
                or abs(captured - utc) > 2
                or abs(server - utc) > 14 * 3600):
            raise ValueError("snapshot timestamps are future-dated, stale, or invalid")
        time_basis = str(payload.get("time_basis") or "broker_server")
        if time_basis not in {"utc", "broker_server"}:
            raise ValueError("time_basis must be utc or broker_server")
        if time_basis == "utc" and abs(server - utc) > 2:
            raise ValueError("UTC snapshots must use the same server and UTC anchor")
        allowed = set(cfg.get("symbols") or [])
        prior = self._publisher_snapshot or {}
        quotes = payload.get("quotes") or {}
        rates = payload.get("rates") or prior.get("rates") or {}
        specs = payload.get("specs") or prior.get("specs") or {}
        if not quotes or (set(quotes) | set(rates) | set(specs)) - allowed:
            raise ValueError("snapshot has no quotes or contains an unapproved symbol")
        clean_quotes = {}
        for symbol, row in quotes.items():
            bid, ask, tick_t = float(row["bid"]), float(row["ask"]), float(row["t"])
            last = float(row.get("last") or 0)
            if (not all(math.isfinite(v) for v in (bid, ask, tick_t)) or bid <= 0
                    or ask < bid or tick_t <= 0 or not math.isfinite(last)
                    or abs(server - tick_t) > max_age + 2):
                raise ValueError(f"invalid quote for {symbol}")
            clean_quotes[symbol] = {"bid": bid, "ask": ask,
                                    "last": last, "t": tick_t}
        clean_rates = {}
        for symbol, frames in rates.items():
            clean_rates[symbol] = {}
            for timeframe, rows in frames.items():
                if timeframe not in {"M1", "M3", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"}:
                    raise ValueError("unsupported rates timeframe")
                if not isinstance(rows, list) or not 1 <= len(rows) <= 2000:
                    raise ValueError("rates must contain 1..2000 bars")
                previous, checked = 0, []
                for row in rows:
                    bar = {k: float(row[k]) for k in ("t", "o", "h", "l", "c")}
                    bar["v"] = float(row.get("v") or 0)
                    if (not all(math.isfinite(v) for v in bar.values()) or bar["t"] <= previous
                            or bar["l"] > min(bar["o"], bar["c"])
                            or bar["h"] < max(bar["o"], bar["c"]) or bar["v"] < 0):
                        raise ValueError(f"invalid or unordered {timeframe} bar for {symbol}")
                    previous = int(bar["t"])
                    checked.append(bar)
                clean_rates[symbol][timeframe] = checked
        clean_specs = {}
        for symbol, raw in specs.items():
            spec = SymbolSpec(**raw)
            if (spec.symbol != symbol or spec.point <= 0 or spec.tick_size <= 0
                    or spec.contract_size <= 0 or spec.min_lot <= 0 or spec.lot_step <= 0
                    or not spec.spec_complete):
                raise ValueError(f"symbol spec identity mismatch for {symbol}")
            clean_specs[symbol] = spec.model_dump()
        if set(clean_quotes) - set(clean_specs):
            raise ValueError("every published quote requires its broker symbol specification")
        snapshot = {"captured_at": captured, "time_basis": time_basis,
                    "server_time": server, "utc_time": utc,
                    "quotes": clean_quotes, "rates": clean_rates, "specs": clean_specs,
                    "identity": {"verified_demo": True}}
        self._publisher_snapshot, self._publisher_received_at = snapshot, current
        self.invalidate()
        if self.db is not None:
            self.db.kv_set(self._publisher_key, {"snapshot": snapshot, "received_at": current})
        return {"accepted": True, "received_at": current, "symbols": sorted(clean_quotes),
                "rate_bars": sum(len(bars) for frames in clean_rates.values()
                                 for bars in frames.values())}

    def _publisher_fresh(self) -> bool:
        return bool(self.publisher.get("enabled") and self._publisher_snapshot
                    and time.time() - self._publisher_received_at
                    <= float(self.publisher.get("max_snapshot_age_seconds", 15)))

    def _publisher_tick(self, symbol: str) -> Tick:
        snapshot = self._publisher_snapshot or {}
        quote, spec = (snapshot.get("quotes") or {}).get(symbol), (snapshot.get("specs") or {}).get(symbol)
        if not quote or not spec:
            raise StaleDataError(f"MT5 publisher has no quote/spec for {symbol}")
        offset = (round(float(snapshot["server_time"]) - float(snapshot["utc_time"]))
                  if snapshot.get("time_basis") == "broker_server" else 0)
        bid, ask = float(quote["bid"]), float(quote["ask"])
        return Tick(t=float(quote["t"]) - offset, bid=bid, ask=ask,
                    spread_points=round((ask - bid) / float(spec["point"]), 1),
                    last=float(quote.get("last") or (bid + ask) / 2))

    def timestamp_metadata(self) -> dict[str, Any]:
        if self._publisher_fresh():
            snapshot = self._publisher_snapshot or {}
            offset = (round(float(snapshot["server_time"]) - float(snapshot["utc_time"]))
                      if snapshot.get("time_basis") == "broker_server" else 0)
            display = "broker_server" if snapshot.get("time_basis") == "broker_server" else "utc"
            return {"basis": "utc", "display_basis": display,
                    "server_utc_offset_seconds": offset}
        adapter = self.registry.get()
        if hasattr(adapter, "timestamp_metadata"):
            return adapter.timestamp_metadata()
        return {"basis": "utc", "display_basis": "utc",
                "server_utc_offset_seconds": 0}

    def latest_quote(self, symbol: str, broker_id: str | None = None) -> dict[str, Any] | None:
        if self.publisher.get("enabled"):
            try:
                if not self._publisher_fresh():
                    raise StaleDataError("MT5 publisher snapshot is missing or stale")
                return {"tick": self._publisher_tick(symbol).model_dump(), "stale": False,
                        "source": "mt5_demo_publisher"}
            except (KeyError, ValueError, StaleDataError) as exc:
                return {"tick": None, "stale": True, "source": "mt5_demo_publisher",
                        "reason": str(exc)}
        adapter = self.registry.get(broker_id)
        try:
            tick = adapter.ticker(symbol)
            self._last_ticks[symbol] = tick
            if self.db is not None:
                self.db.kv_set(f"market-last-quote:{adapter.id}:{symbol}", tick.model_dump())
            return {"tick": tick.model_dump(), "stale": False, "source": "broker"}
        except Exception:  # noqa: BLE001 - display last-known quote, never certify as live
            tick = self._last_ticks.get(symbol)
            if tick is None and self.db is not None:
                payload = self.db.kv_get(f"market-last-quote:{adapter.id}:{symbol}")
                try:
                    tick = Tick(**payload) if payload is not None else None
                except (TypeError, ValueError):
                    tick = None
            if tick is None:
                return None
            self._last_ticks[symbol] = tick
            return {"tick": tick.model_dump(), "stale": True, "source": "persisted"}

    def ticker(self, symbol: str, broker_id: str | None = None) -> Tick:
        if self.publisher.get("enabled"):
            if not self._publisher_fresh():
                raise StaleDataError("MT5 publisher snapshot is missing or stale")
            return self._publisher_tick(symbol)
        adapter = self.registry.get(broker_id)
        tick = adapter.ticker(symbol)
        self._last_ticks[symbol] = tick
        return tick

    def candles(self, symbol: str, timeframe: str = "M1", limit: int = 600,
                broker_id: str | None = None, force: bool = False) -> pd.DataFrame:
        if self.publisher.get("enabled"):
            if not self._publisher_fresh():
                raise StaleDataError("MT5 publisher snapshot is missing or stale")
            rows = (((self._publisher_snapshot or {}).get("rates") or {}).get(symbol) or {}).get(timeframe)
            if not rows:
                raise StaleDataError(f"MT5 publisher has no {timeframe} rates for {symbol}")
            frame = pd.DataFrame(rows).sort_values("t").tail(int(limit)).reset_index(drop=True)
            frame["t"] = frame["t"].astype("int64")
            if self._publisher_snapshot.get("time_basis") == "broker_server":
                frame["t"] -= round(float(self._publisher_snapshot["server_time"])
                                    - float(self._publisher_snapshot["utc_time"]))
            return enrich(frame)
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
        tick_time = float(tick.t)
        age_seconds = now - tick_time
        risk_limits = self.settings.risk_cfg().get("limits", {})
        limit = float(risk_limits.get("data_staleness_seconds", 30))
        future_tolerance = float(risk_limits.get("data_future_tolerance_seconds", 2))
        future_by = max(0.0, -age_seconds)
        future_invalid = future_by > future_tolerance
        staleness = max(0.0, age_seconds)
        df = self.candles(symbol, timeframe, 10, broker_id)
        gaps = 0
        if len(df) > 2:
            diffs = df["t"].diff().iloc[1:]
            gaps = int((diffs > 90).sum()) if timeframe == "M1" else 0
        ok = health in ("connected", "degraded") and not future_invalid and staleness <= limit
        reason = ""
        if health not in ("connected", "degraded"):
            reason = f"broker health is {health}"
        elif future_invalid:
            reason = (f"tick timestamp is in the future ({future_by:.1f}s > "
                      f"{future_tolerance:.0f}s clock-skew tolerance)")
        elif staleness > limit:
            reason = f"price feed is stale ({staleness:.1f}s > {limit:.0f}s)"
        return {
            "ok": ok,
            "health": health,
            "staleness_seconds": round(staleness, 2),
            "future_seconds": round(future_by, 2) if future_by else 0.0,
            "spread_points": tick.spread_points,
            "gaps_last_10": gaps,
            "reason": reason,
            # The label must describe where the prices came from, not which adapter
            # happens to be loaded: with `feed_mode: replay` the adapter is still the
            # paper one, but the bars are imported candles.
            "feed": (self.effective_mode.replace("_", "-") if self.publisher.get("enabled") else
                     getattr(self, "feed_mode", None)
                     or ("simulated" if adapter.adapter_type == "simulated_mt5" else "mt5-live")),
        }

    def require_fresh(self, symbol: str, timeframe: str = "M1") -> dict[str, Any]:
        quality = self.data_quality(symbol, timeframe)
        if not quality["ok"]:
            raise StaleDataError(quality.get("reason") or "market data is not fresh")
        return quality
