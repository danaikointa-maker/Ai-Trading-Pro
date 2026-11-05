"""Broker adapter contract.

Everything above this layer (analysis, risk, execution gateway, dashboard) is
broker-agnostic. Adding a broker means adding one adapter + one YAML profile.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from packages.shared_schemas.models import (
    AccountInfo,
    Health,
    OrderRequest,
    OrderResult,
    Position,
    SymbolSpec,
    Tick,
    TradeRecord,
)


class BrokerError(RuntimeError):
    """Raised when an adapter refuses or fails an operation."""

    def __init__(self, message: str, retcode: int = 0) -> None:
        super().__init__(message)
        self.retcode = retcode


class BrokerAdapter(ABC):
    id: str = "generic"
    label: str = "Generic broker"
    adapter_type: str = "generic"
    server: str = ""
    account_type: str = "demo"
    live_allowed: bool = False
    regulated_note: str = ""

    # ------------------------------------------------------------- metadata
    @abstractmethod
    def health(self) -> Health: ...

    @abstractmethod
    def account_info(self) -> AccountInfo: ...

    @abstractmethod
    def symbol_spec(self, symbol: str) -> SymbolSpec: ...

    @abstractmethod
    def symbol_names(self) -> list[str]: ...

    @abstractmethod
    def ticker(self, symbol: str) -> Tick: ...

    @abstractmethod
    def candles(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame: ...

    # -------------------------------------------------------------- trading
    @abstractmethod
    def positions(self) -> list[Position]: ...

    @abstractmethod
    def order_send(self, request: OrderRequest, ticket_hint: str = "") -> OrderResult: ...

    @abstractmethod
    def modify_position(self, ticket: str, sl: float | None = None, tp: float | None = None) -> bool: ...

    @abstractmethod
    def close_position(self, ticket: str, volume: float | None = None, comment: str = "") -> OrderResult: ...

    # ------------------------------------------------------------- lifecycle
    def on_tick(self, ticks: dict[str, Tick]) -> list[TradeRecord]:
        """Adapters that simulate SL/TP internally return closed trades here."""
        return []

    def equity(self) -> tuple[float, float]:
        info = self.account_info()
        return info.balance, info.equity

    def closed_trades(self) -> list[TradeRecord]:
        return []

    def drain_closed_trades(self) -> list[TradeRecord]:
        return []

    def set_balance(self, balance: float) -> None:
        raise BrokerError("this adapter does not support balance overrides")

    def shutdown(self) -> None:
        return None

    def describe(self) -> dict[str, Any]:
        info = self.account_info()
        return {
            "id": self.id,
            "label": self.label,
            "adapter": self.adapter_type,
            "server": self.server,
            "account_type": self.account_type,
            "health": self.health().value,
            "live_allowed": self.live_allowed,
            "regulated_note": self.regulated_note,
            "account": info.model_dump(),
            "symbols": self.symbol_names(),
        }

class BrokerRegistryProtocol:
    def get(self, broker_id: str) -> BrokerAdapter: ...
