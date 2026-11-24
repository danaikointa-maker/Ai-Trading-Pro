"""Paper-only execution recovery across a lost acknowledgement and reconnect."""
from __future__ import annotations

import pytest

from integrations.brokers.base import BrokerError
from integrations.brokers.paper import PaperBroker
from packages.persistence.db import Database
from packages.shared_schemas.models import (
    Health,
    OrderRequest,
    OrderSide,
    OrderState,
    SymbolSpec,
    Tick,
)
from services.execution_gateway.gateway import ExecutionGateway


class _Settings:
    execution = {"verify_after_send": True, "order_timeout_seconds": 1}


class _Feed:
    def ticker(self, _symbol: str) -> Tick:
        return Tick(t=1_800_000_000, bid=2000.0, ask=2000.2,
                    spread_points=20, last=2000.1)


class _ReconnectablePaperAdapter:
    """Inject a disconnected period and one lost ACK without using a broker."""

    adapter_type = "simulated_mt5"

    def __init__(self, paper: PaperBroker) -> None:
        self.paper = paper
        self.id = paper.id
        self.connected = True
        self.drop_next_ack = False
        self.send_calls = 0

    def __getattr__(self, name: str):
        return getattr(self.paper, name)

    def health(self) -> Health:
        return Health.connected if self.connected else Health.disconnected

    def positions(self):
        if not self.connected:
            raise BrokerError("simulated Paper transport unavailable")
        return self.paper.positions()

    def order_send(self, request: OrderRequest, ticket_hint: str = ""):
        if not self.connected:
            raise BrokerError("simulated Paper transport unavailable")
        self.send_calls += 1
        result = self.paper.order_send(request, ticket_hint=ticket_hint)
        if self.drop_next_ack:
            self.drop_next_ack = False
            self.connected = False
            raise BrokerError("simulated acknowledgement lost after Paper fill")
        return result


def _paper() -> PaperBroker:
    spec = SymbolSpec(symbol="XAUUSD", digits=2, point=0.01, tick_size=0.01,
                      contract_size=100, min_lot=0.01, max_lot=50, lot_step=0.01,
                      spread_typical_points=20, source="declared")
    profile = {
        "id": "paper-u18-reconnect",
        "server": "No7 Paper",
        "account_type": "demo",
        "symbols": {"XAUUSD": spec.model_dump(exclude={"symbol"})},
    }
    return PaperBroker(profile, _Feed(), starting_balance=10_000, seed=7)


def test_paper_order_refuses_while_disconnected_then_reconciles_lost_ack_without_resend(tmp_path):
    db = Database(tmp_path / "paper-reconnect.sqlite3")
    paper = _paper()
    adapter = _ReconnectablePaperAdapter(paper)
    gateway = ExecutionGateway(_Settings(), db)
    request = OrderRequest(
        symbol="XAUUSD", side=OrderSide.buy, volume=0.1, sl=1990, tp=2020,
        signal_id="paper-u18-reconnect-1", idempotency_key="paper-u18-reconnect-key",
        broker_id=paper.id,
    )

    try:
        adapter.connected = False
        with pytest.raises(BrokerError, match="is disconnected"):
            gateway.submit(adapter, request)
        assert adapter.send_calls == 0
        assert paper.positions() == []
        assert db.query_one("SELECT COUNT(*) AS n FROM orders")["n"] == 0

        adapter.connected = True
        adapter.drop_next_ack = True
        pending = gateway.submit(adapter, request)
        assert pending.status == OrderState.pending
        assert pending.verified is False
        assert adapter.send_calls == 1
        assert len(paper.positions()) == 1
        assert db.query_one("SELECT state FROM orders")["state"] == OrderState.pending.value

        adapter.connected = True
        recovered = ExecutionGateway(_Settings(), db).submit(adapter, request)
        assert recovered.status == OrderState.filled
        assert recovered.verified is True
        assert adapter.send_calls == 1
        assert len(paper.positions()) == 1
        assert db.query_one("SELECT state FROM orders")["state"] == OrderState.filled.value
    finally:
        db.close()
