"""Broker adapter registry — one YAML profile per account, zero code changes.

``adapter`` values:
  * ``simulated_mt5`` — paper account with MT5 contract specs and local fills
  * ``mt5``           — real terminal via the official Python package
  * ``generic_mt5``   — same as mt5, kept as an explicit template profile
"""
from __future__ import annotations

import os
from typing import Any

from integrations.brokers.base import BrokerAdapter
from integrations.brokers.mt5_live import MT5Broker
from integrations.brokers.paper import PaperBroker
from packages.shared_schemas.settings import Settings
from services.market_data.simulator import SyntheticFeed


class BrokerRegistry:
    def __init__(self, settings: Settings, feed: SyntheticFeed) -> None:
        self.settings = settings
        self.feed = feed
        self._adapters: dict[str, BrokerAdapter] = {}
        self.active_id = settings.default_broker_id()

    def build(self) -> None:
        for profile in self.settings.brokers.get("brokers", []):
            adapter_type = profile.get("adapter", "simulated_mt5")
            try:
                if adapter_type in ("simulated_mt5", "paper"):
                    self._adapters[profile["id"]] = PaperBroker(
                        profile, self.feed,
                        starting_balance=float(profile.get("starting_balance", 10000.0)),
                        seed=abs(hash(profile["id"])) % 10_000,
                    )
                elif adapter_type in ("mt5", "generic_mt5"):
                    broker = MT5Broker(
                        profile,
                        terminal_path=os.environ.get("MT5_TERMINAL_PATH", ""),
                        login=int(os.environ.get("MT5_LOGIN") or 0) or None,
                        password=os.environ.get("MT5_PASSWORD", ""),
                        server=os.environ.get("MT5_SERVER", profile.get("server", "")),
                        timeout_ms=int(os.environ.get("MT5_TIMEOUT_MS", 5000)),
                    )
                    broker.connect()
                    self._adapters[profile["id"]] = broker
            except Exception as exc:  # noqa: BLE001 - one bad profile must not kill the app
                self.settings.app.setdefault("_broker_errors", {})[profile["id"]] = str(exc)

    def get(self, broker_id: str | None = None) -> BrokerAdapter:
        key = broker_id or self.active_id
        if key not in self._adapters:
            raise KeyError(f"broker profile not loaded: {key}")
        return self._adapters[key]

    def all(self) -> list[BrokerAdapter]:
        return list(self._adapters.values())

    def set_active(self, broker_id: str) -> BrokerAdapter:
        adapter = self.get(broker_id)
        self.active_id = broker_id
        return adapter

    def find_for_symbol(self, symbol: str) -> list[BrokerAdapter]:
        out = []
        for adapter in self._adapters.values():
            try:
                if symbol in adapter.symbol_names():
                    out.append(adapter)
            except Exception:  # noqa: BLE001
                continue
        return out

    def describe_all(self) -> list[dict[str, Any]]:
        rows = []
        for adapter in self._adapters.values():
            try:
                rows.append(adapter.describe())
            except Exception as exc:  # noqa: BLE001
                rows.append({"id": adapter.id, "label": adapter.label, "health": "disconnected", "error": str(exc)})
        return rows

    def health_map(self) -> dict[str, str]:
        out = {}
        for adapter in self._adapters.values():
            try:
                out[adapter.id] = adapter.health().value
            except Exception:  # noqa: BLE001
                out[adapter.id] = "disconnected"
        return out
