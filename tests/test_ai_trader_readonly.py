from types import SimpleNamespace
from unittest.mock import Mock

from services.api_gateway.routes.explain import _research_observability
from services.strategy_engine.explainer import TradeExplainer


def test_research_observability_is_small_and_marks_stale_source():
    market = SimpleNamespace(
        latest_quote=lambda _symbol: {
            "tick": {"bid": 2000.0}, "stale": True, "source": "persisted",
            "account_id": "private", "credential": "private",
        },
        timestamp_metadata=lambda: {
            "display_basis": "broker_server", "server_utc_offset_seconds": 25200,
            "terminal_path": "private",
        },
        effective_mode="mt5_demo_publisher_stale",
    )
    provenance = _research_observability(SimpleNamespace(market=market), "XAUUSD")
    assert provenance == {
        "feed_mode": "mt5_demo_publisher_stale",
        "quote_status": "stale",
        "quote_source": "persisted",
        "display_basis": "broker_server",
        "server_utc_offset_seconds": 25200,
    }


def test_research_observability_rejects_unknown_labels_and_bad_clock_values():
    market = SimpleNamespace(
        latest_quote=lambda _symbol: {"tick": {"bid": 2000.0}, "stale": False,
                                      "source": "account-123-secret"},
        timestamp_metadata=lambda: {"display_basis": "local", "server_utc_offset_seconds": 1e99},
        effective_mode="untrusted-config-secret",
    )
    provenance = _research_observability(SimpleNamespace(market=market), "XAUUSD")
    assert provenance == {
        "feed_mode": "unknown",
        "quote_status": "unavailable",
        "quote_source": "unavailable",
        "display_basis": "unknown",
        "server_utc_offset_seconds": None,
    }


def test_order_intent_never_reaches_enabled_local_model():
    llm = SimpleNamespace(enabled=True, generate=Mock(return_value="unsafe model output"), model="test")
    explainer = TradeExplainer(llm)
    result = explainer.explain("buy XAUUSD now", None, None, None)
    assert "ไม่สามารถสั่งซื้อ/ขายได้" in result["answer"]
    assert any("ไม่มีการส่งคำสั่งใด ๆ" in bullet for bullet in result["bullets"])
    llm.generate.assert_not_called()


def test_fact_sheet_keeps_only_allowlisted_observability():
    explainer = TradeExplainer(SimpleNamespace(enabled=False))
    facts = explainer.fact_sheet(None, None, None, {
        "feed_mode": "simulate", "quote_status": "fresh", "quote_source": "broker",
        "display_basis": "utc", "server_utc_offset_seconds": 0,
        "account_id": "private", "position": {"ticket": "private"}, "token": "private",
    })
    assert facts["observability"] == {
        "feed_mode": "simulate", "quote_status": "fresh", "quote_source": "broker",
        "display_basis": "utc", "server_utc_offset_seconds": 0,
    }

