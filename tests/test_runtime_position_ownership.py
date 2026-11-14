"""P2.3 management must not replace accepted state with untrusted reads."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock
from types import SimpleNamespace
from unittest.mock import Mock
import time
import pandas as pd

import pytest

from packages.persistence.db import Database
from packages.shared_schemas.models import Position
from services.api_gateway.state import TradingRuntime
from services.execution_gateway.gateway import ExecutionGateway
from integrations.brokers.base import BrokerError


def position(ticket="kept", broker_id="demo"):
    return Position(ticket=ticket, symbol="XAUUSD", direction="up", volume=0.1,
                    entry=2000, sl=1990, tp=2020, current_price=2001,
                    open_time=1, broker_id=broker_id)


@pytest.fixture
def managed(tmp_path):
    db = Database(tmp_path / "runtime.db")
    broker = Mock()
    broker.id = "demo"
    broker.account_info.return_value = SimpleNamespace(
        broker_id="demo", login="123", server="Demo", currency="USD")
    gateway = ExecutionGateway(SimpleNamespace(execution={}), db)
    gateway._assert_account(broker)
    kept = position()
    gateway.open_position_snapshot([kept], broker_id=broker.id)
    runtime = TradingRuntime.__new__(TradingRuntime)
    runtime.registry = Mock()
    runtime.registry.get.return_value = broker
    runtime.gateway = gateway
    runtime.db = db
    runtime.lock = RLock()
    runtime.positions_cache = [kept]
    runtime.plans, runtime.contexts, runtime.forecasts = {}, {}, {}
    runtime.active_symbol = "XAUUSD"
    runtime.manager = Mock()
    runtime.manager.evaluate.return_value = []
    runtime._log_error = Mock()
    runtime._apply_action = Mock()
    broker.positions.return_value = [position("new")]
    yield runtime, broker, db
    broker.order_send.assert_not_called()
    db.close()


@pytest.mark.parametrize("stage,empty", [("before", False), ("before", True),
                                        ("positions", False), ("positions", True), ("specs", False)])
def test_management_account_switch_preserves_cache_and_snapshot(managed, stage, empty):
    runtime, broker, db = managed
    accepted = runtime.positions_cache
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]
    result = [] if empty else [position("new")]
    broker.positions.return_value = result

    def switched(*args):
        broker.account_info.return_value.login = "456"
        return result if stage == "positions" else SimpleNamespace()

    if stage == "before":
        broker.account_info.return_value.login = "456"
    else:
        getattr(broker, "positions" if stage == "positions" else "symbol_spec").side_effect = switched
    runtime._manage_cycle(10)
    assert runtime.positions_cache is accepted
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before
    runtime.manager.evaluate.assert_not_called()
    runtime._apply_action.assert_not_called()
    runtime._log_error.assert_called_once()
    if stage == "before":
        broker.positions.assert_not_called()


@pytest.mark.parametrize("damage", ["foreign", "duplicate", "collision"])
def test_management_invalid_positions_never_enter_cache(managed, damage):
    runtime, broker, db = managed
    accepted = runtime.positions_cache
    if damage == "foreign":
        broker.positions.return_value = [position("new", "other")]
    elif damage == "duplicate":
        broker.positions.return_value = [position("new"), position("new")]
    else:
        runtime.gateway.open_position_snapshot([position("new", "other")], broker_id="other")
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]
    runtime._manage_cycle(10)
    assert runtime.positions_cache is accepted
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before
    runtime.manager.evaluate.assert_not_called()
    runtime._log_error.assert_called_once()


@pytest.mark.parametrize("empty", [False, True])
def test_management_accepts_owned_snapshot_and_keeps_other_broker(managed, empty):
    runtime, broker, db = managed
    runtime.gateway.open_position_snapshot([position("other", "other")], broker_id="other")
    broker.positions.return_value = [] if empty else [position("new")]
    runtime._manage_cycle(10)
    assert runtime.positions_cache == broker.positions.return_value
    assert {row["ticket"] for row in db.query("SELECT ticket FROM open_positions")} == (
        {"other", "kept"} if empty else {"other", "kept", "new"})
    # A position missing from an isolated broker poll cannot be treated as a
    # completed close. Its last baseline stays pending authoritative evidence.
    from packages.persistence.position_events import PositionEventLog

    owner = runtime.gateway._assert_account(broker)
    events = PositionEventLog(db).for_ticket(broker_id=broker.id, ticket="kept",
                                              account_identity=owner)
    assert any(event["status"] == "missing_unverified" for event in events)
    runtime.manager.evaluate.assert_called_once()
    runtime._log_error.assert_not_called()


def test_management_poll_archives_unverified_sl_change_before_updating_cache(managed):
    from packages.persistence.position_events import PositionEventLog
    import json

    runtime, broker, db = managed
    changed = position("kept").model_copy(update={"sl": 1995})
    broker.positions.return_value = [changed]
    runtime._manage_cycle(10)
    owner = runtime.gateway._assert_account(broker)
    events = PositionEventLog(db).for_ticket(
        broker_id=broker.id, ticket="kept", account_identity=owner)
    assert [event["status"] for event in events] == ["changed_unverified"]
    assert events[0]["detail"]["changed_fields"] == ["sl"]
    assert json.loads(db.query_one("SELECT payload FROM open_positions WHERE ticket='kept'")["payload"])["sl"] == 1990
    assert runtime.positions_cache == [changed]
    runtime._manage_cycle(11)
    assert len(PositionEventLog(db).for_ticket(broker_id=broker.id, ticket="kept",
                                              account_identity=owner)) == 1


def test_management_archives_only_recent_closed_m5_bars_for_its_symbol(managed):
    from packages.persistence.position_candles import PositionCandleLog

    runtime, broker, db = managed
    frames = pd.DataFrame([{ "t": stamp, "o": 2000.0, "h": 2004.0,
                             "l": 1998.0, "c": 2001.0, "v": 10.0}
                           for stamp in (0, 300, 600, 900, 1200)])
    runtime.contexts["XAUUSD"] = SimpleNamespace(
        snapshot=SimpleNamespace(symbol="XAUUSD", broker_id="demo",
                                 indicators=SimpleNamespace(atr_points=300)),
        frames={"M5": frames})
    runtime.contexts["EURUSD"] = SimpleNamespace(
        snapshot=SimpleNamespace(symbol="EURUSD", broker_id="demo",
                                 indicators=SimpleNamespace(atr_points=300)),
        frames={"M5": frames})
    runtime.market = SimpleNamespace(feed_mode="simulated")
    broker.positions.return_value = [
        position("tracked"),
        position("eur-tracked").model_copy(update={"symbol": "EURUSD"}),
        position("unobserved").model_copy(update={"symbol": "GBPUSD"}),
    ]
    runtime._manage_cycle(1200)
    owner = runtime.gateway._assert_account(broker)
    archive = PositionCandleLog(db).for_ticket(
        broker_id="demo", ticket="tracked", account_identity=owner, symbol="XAUUSD")
    assert [bar["t"] for bar in archive["bars"]] == [300, 600, 900]
    assert all(bar["feed_mode"] == "simulated" for bar in archive["bars"])
    assert archive["complete"] is False and archive["broker_tick_verified"] is False
    assert [bar["t"] for bar in PositionCandleLog(db).for_ticket(
        broker_id="demo", ticket="eur-tracked", account_identity=owner,
        symbol="EURUSD")["bars"]] == [300, 600, 900]
    assert PositionCandleLog(db).for_ticket(
        broker_id="demo", ticket="unobserved", account_identity=owner,
        symbol="GBPUSD")["bars"] == []
    runtime._manage_cycle(1200)
    assert len(PositionCandleLog(db).for_ticket(
        broker_id="demo", ticket="tracked", account_identity=owner,
        symbol="XAUUSD")["bars"]) == 3
    runtime._log_error.assert_not_called()


def test_chart_archive_failure_does_not_block_protective_management(managed, monkeypatch):
    from packages.persistence.position_candles import PositionCandleLog

    runtime, broker, _ = managed
    runtime.contexts["XAUUSD"] = SimpleNamespace(
        snapshot=SimpleNamespace(symbol="XAUUSD", broker_id="demo",
                                 indicators=SimpleNamespace(atr_points=300)),
        frames={"M5": pd.DataFrame([{ "t": 600, "o": 2000., "h": 2004.,
                                      "l": 1998., "c": 2001., "v": 10.}])})
    runtime.manager.evaluate.return_value = []
    broker.positions.return_value = [position("tracked")]

    def reject(*args, **kwargs):
        raise OSError("chart storage unavailable")

    monkeypatch.setattr(PositionCandleLog, "capture", reject)
    runtime._manage_cycle(1200)
    runtime.manager.evaluate.assert_called_once()
    assert runtime._log_error.call_args.args[0] == "post_entry_candle_archive"


def test_management_rejects_snapshot_if_broker_observation_cannot_be_saved(managed):
    runtime, broker, db = managed
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]
    prior_cache = runtime.positions_cache
    broker.positions.return_value = [position("kept").model_copy(update={"sl": 1995})]
    db.execute("CREATE TRIGGER deny_observation BEFORE INSERT ON position_events "
               "BEGIN SELECT RAISE(ABORT, 'observation unavailable'); END")
    runtime._manage_cycle(10)
    assert runtime.positions_cache is prior_cache
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before
    assert db.query("SELECT * FROM position_events") == []
    runtime.manager.evaluate.assert_not_called()
    runtime._log_error.assert_called_once()


def test_management_does_not_resurrect_snapshot_deleted_by_action(managed):
    runtime, _, db = managed
    runtime.manager.evaluate.return_value = [SimpleNamespace(kind="close")]
    runtime._apply_action.side_effect = lambda *args, **kwargs: db.execute(
        "DELETE FROM open_positions WHERE ticket='new'")
    runtime._manage_cycle(10)
    # The mutation removes `new` without bringing it back, while an unrelated
    # broker-missing `kept` position remains flagged for reconciliation.
    assert {row["ticket"] for row in db.query("SELECT ticket FROM open_positions")} == {"kept"}
    runtime._apply_action.assert_called_once()


@pytest.mark.parametrize("stage", ["positions", "specs"])
def test_management_registry_switch_discards_old_adapter_read(managed, stage):
    runtime, broker, db = managed
    accepted = runtime.positions_cache
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]
    other = Mock()
    other.id = "other"

    def switched(*args):
        runtime.registry.get.return_value = other
        return [position("new")] if stage == "positions" else SimpleNamespace()

    getattr(broker, "positions" if stage == "positions" else "symbol_spec").side_effect = switched
    runtime._manage_cycle(10)
    assert runtime.positions_cache is accepted
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before
    runtime.manager.evaluate.assert_not_called()
    other.positions.assert_not_called()


@pytest.mark.parametrize("stage", ["positions", "specs", "snapshot"])
def test_management_read_or_persistence_failure_preserves_cache(managed, stage):
    runtime, broker, db = managed
    accepted = runtime.positions_cache
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]
    target = runtime.gateway if stage == "snapshot" else broker
    setattr(target, "open_position_snapshot" if stage == "snapshot" else (
        "positions" if stage == "positions" else "symbol_spec"), Mock(side_effect=RuntimeError("unavailable")))
    runtime._manage_cycle(10)
    assert runtime.positions_cache is accepted
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before
    runtime.manager.evaluate.assert_not_called()
    runtime._log_error.assert_called_once()


@pytest.mark.parametrize("switch", ["account", "adapter"])
def test_management_does_not_apply_old_actions_after_evaluation_switch(managed, switch):
    runtime, broker, _ = managed

    def evaluate(*args):
        if switch == "account":
            broker.account_info.return_value.login = "456"
        else:
            runtime.registry.get.return_value = Mock()
        return [SimpleNamespace(kind="close")]

    runtime.manager.evaluate.side_effect = evaluate
    runtime._manage_cycle(10)
    runtime._apply_action.assert_not_called()
    runtime._log_error.assert_called_once()


def test_apply_action_uses_pinned_adapter_not_new_registry_selection(managed):
    runtime, broker, _ = managed
    other = Mock()
    runtime.registry.get.return_value = other
    runtime.gateway = Mock()
    runtime.notifier = Mock()
    action = SimpleNamespace(kind="modify", new_sl=1995, ticket="new", reason="test", note="test")
    TradingRuntime._apply_action(runtime, action, {}, adapter=broker)
    runtime.gateway.modify.assert_called_once_with(broker, "new", sl=1995, reason="test")


@pytest.mark.parametrize("damage", ["login", "currency", "server", "owner", "missing", "stale", "failed"])
def test_position_view_hides_untrusted_cache_without_deleting_evidence(managed, damage):
    runtime, broker, db = managed
    runtime._manage_cycle(10)
    accepted = runtime.positions_cache
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]
    if damage in ("login", "currency", "server"):
        setattr(broker.account_info.return_value, damage, "other")
    elif damage == "owner":
        db.kv_set("account-owner:demo", {"login": "other"})
    elif damage == "missing":
        db.execute("DELETE FROM kv WHERE key='account-owner:demo'")
    elif damage == "stale":
        runtime._positions_read_at = time.monotonic() - 11
    else:
        broker.positions.side_effect = RuntimeError("unavailable")
        runtime._manage_cycle(11)
    result = runtime.position_view()
    assert result["positions"] == []
    assert result["positions_status"]["available"] is False
    assert runtime.positions_cache is accepted
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before
    if damage == "missing":
        assert db.kv_get("account-owner:demo") is None


@pytest.mark.parametrize("empty", [False, True])
def test_position_view_requires_successful_owned_read_even_when_empty(managed, empty):
    runtime, broker, _ = managed
    assert runtime.position_view()["positions_status"]["available"] is False
    broker.positions.return_value = [] if empty else [position("new")]
    runtime._manage_cycle(10)
    result = runtime.position_view()
    assert result["positions_status"]["available"] is True
    assert len(result["positions"]) == (0 if empty else 1)


def test_position_view_rechecks_account_during_disclosure(managed):
    runtime, broker, _ = managed
    runtime._manage_cycle(10)
    first = broker.account_info.return_value
    broker.account_info.side_effect = [first, SimpleNamespace(
        broker_id="demo", login="456", server="Demo", currency="USD")]
    assert runtime.position_view()["positions_status"]["available"] is False


@pytest.mark.parametrize("damage", ["adapter", "same_identity_adapter", "row", "clock", "corrupt_owner", "read_error"])
def test_position_view_rejects_invalid_runtime_evidence(managed, damage):
    runtime, broker, db = managed
    runtime._manage_cycle(10)
    if damage == "adapter":
        runtime.registry.get.return_value = Mock()
    elif damage == "same_identity_adapter":
        other = Mock()
        other.id = broker.id
        other.account_info.return_value = broker.account_info.return_value
        runtime.registry.get.return_value = other
    elif damage == "row":
        runtime.positions_cache[0].broker_id = "other"
    elif damage == "clock":
        runtime._positions_read_at = float("nan")
    elif damage == "corrupt_owner":
        db.execute("UPDATE kv SET value='corrupt' WHERE key='account-owner:demo'")
    else:
        broker.account_info.side_effect = RuntimeError("unavailable")
    assert runtime.position_view()["positions_status"]["available"] is False


def test_position_view_invalid_after_management_action_until_next_read(managed):
    runtime, _, _ = managed
    runtime.manager.evaluate.return_value = [SimpleNamespace(kind="close")]
    runtime._manage_cycle(10)
    assert runtime.position_view()["positions_status"]["available"] is False


@pytest.mark.parametrize("surface", ["rest", "live"])
def test_payload_surfaces_do_not_expose_cache_after_account_switch(managed, surface):
    from services.api_gateway.routes.trading import state
    from packages.shared_schemas.models import TradeMode

    runtime, broker, _ = managed
    runtime._manage_cycle(10)
    broker.account_info.return_value.login = "456"
    runtime.mode = TradeMode.manual
    runtime.account = Mock(return_value={"login": "456"})
    runtime.risk_state = Mock(return_value=Mock(model_dump=Mock(return_value={})))
    runtime.last_reconcile = {}
    if surface == "rest":
        result = state(runtime, {})
    else:
        runtime.replica = False
        runtime.signals, runtime.gates, runtime.ticks, runtime.training = {}, {}, {}, {}
        runtime.errors = []
        runtime.version = 1
        runtime.market, runtime.risk, runtime.predictor, runtime.notifier = Mock(), Mock(), Mock(), Mock()
        runtime.predictor.metrics = {}
        result = runtime.live_payload()
    assert result["positions"] == []
    assert result["positions_status"]["available"] is False


@pytest.mark.parametrize("action", ["close_ticket", "close_all", "modify", "partial_close", "close"])
@pytest.mark.parametrize("fails", [False, True])
def test_explicit_action_invalidates_cache_before_gateway_io(managed, action, fails):
    runtime, _, db = managed
    runtime._manage_cycle(10)
    accepted = runtime.positions_cache
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]
    runtime.notifier = Mock()

    def perform(*args, **kwargs):
        assert runtime.position_view()["positions_status"]["available"] is False
        if fails:
            raise RuntimeError("action outcome unknown")
        return {"ok": False}

    runtime.gateway.close = Mock(side_effect=perform)
    runtime.gateway.modify = Mock(side_effect=perform)

    def invoke():
        if action == "close_ticket":
            return runtime.close_ticket("new")
        if action == "close_all":
            return runtime.close_all()
        return TradingRuntime._apply_action(runtime, SimpleNamespace(
            kind=action, new_sl=1995, ticket="new", volume=0.05, reason="test", note="test"), {})

    if fails and action in ("close_all", "close_ticket"):
        result = invoke()
        assert result["ok"] is False
        assert result["unknown"] == 1
    elif fails:
        with pytest.raises(RuntimeError, match="action outcome unknown"):
            invoke()
    else:
        invoke()
    assert runtime.position_view()["positions_status"]["available"] is False
    assert runtime.positions_cache is accepted
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before
    runtime._manage_cycle(11)
    assert runtime.position_view()["positions_status"]["available"] is True


@pytest.mark.parametrize("damage", ["exception", "malformed", "adapter", "account", "before"])
def test_single_close_reports_unknown_without_retry_or_sensitive_details(managed, damage):
    runtime, broker, db = managed
    runtime._manage_cycle(10)
    accepted = runtime.positions_cache
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]

    def close(adapter, ticket, **kwargs):
        assert adapter is broker
        if damage == "exception":
            raise RuntimeError("private adapter detail")
        if damage == "malformed":
            return {"ok": "true"}
        if damage == "adapter":
            runtime.registry.get.return_value = Mock(id="other")
        if damage == "account":
            broker.account_info.return_value.login = "456"
        return {"ok": True, "order": {"private": "must not disclose after ownership loss"}}

    runtime.gateway.close = Mock(side_effect=close)
    if damage == "before":
        broker.account_info.return_value.login = "456"
    result = runtime.close_ticket("new", volume=0.05)
    assert result["ok"] is False
    assert result["outcome"] == "unknown"
    assert result["unknown"] == 1
    assert result["attempted"] == (0 if damage == "before" else 1)
    assert result["exposure_verified"] is False
    assert result["reconciliation_required"] is True
    assert "private" not in str(result)
    assert runtime.gateway.close.call_count == result["attempted"]
    assert runtime.position_view()["positions_status"]["available"] is False
    assert runtime.positions_cache is accepted
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before


@pytest.mark.parametrize("ok", [True, False])
def test_single_close_acknowledgements_never_verify_exposure(managed, ok):
    runtime, broker, _ = managed
    runtime.gateway.close = Mock(return_value={"ok": ok, "order": {"ticket": "new"}})
    result = runtime.close_ticket("new", volume=0.05)
    assert result["ok"] is ok
    assert result["outcome"] == ("accepted" if ok else "rejected")
    assert result["unknown"] == 0 and result["attempted"] == 1
    assert result["exposure_verified"] is False
    assert result["reconciliation_required"] is True
    assert result["order"] == {"ticket": "new"}
    runtime.gateway.close.assert_called_once_with(broker, "new", volume=0.05, reason="manual close", actor="user")


@pytest.mark.parametrize("action", ["single", "all"])
def test_real_gateway_partial_close_acknowledgement_is_unknown_and_never_resent(managed, action):
    from packages.shared_schemas.models import OrderResult, OrderState

    runtime, broker, db = managed
    runtime.notifier = Mock()
    broker.positions.return_value = [position("new"), position("second")]
    broker.close_position.return_value = OrderResult(
        order_id="close", idempotency_key="", status=OrderState.partially_filled, filled_volume=0.04)
    result = runtime.close_ticket("new") if action == "single" else runtime.close_all()
    assert result["ok"] is False
    assert result["unknown"] == 1 and result["attempted"] == 1
    assert result["reconciliation_required"] is True
    assert result["exposure_verified"] is False
    if action == "all":
        assert result["not_attempted"] == 1
        assert result["accepted"] == 0 and result["rejected"] == 0
    broker.close_position.assert_called_once()
    assert db.query("SELECT * FROM trades") == []


def test_management_refresh_during_mutation_cannot_restore_disclosure(managed):
    runtime, _, _ = managed
    runtime._manage_cycle(10)

    def close(*args, **kwargs):
        runtime._manage_cycle(11)
        assert runtime.position_view()["positions_status"]["available"] is False
        return {"ok": True}

    runtime.gateway.close = Mock(side_effect=close)
    runtime.close_ticket("new")
    assert runtime.position_view()["positions_status"]["available"] is False
    runtime._manage_cycle(12)
    assert runtime.position_view()["positions_status"]["available"] is True


def test_read_spanning_completed_action_cannot_restore_disclosure(managed):
    runtime, broker, _ = managed
    runtime._manage_cycle(10)
    runtime.gateway.close = Mock(return_value={"ok": True})

    def positions():
        runtime.close_ticket("new")
        return [position("pre-action")]

    broker.positions.side_effect = positions
    runtime._manage_cycle(11)
    assert runtime.position_view()["positions_status"]["available"] is False
    broker.positions.side_effect = None
    runtime._manage_cycle(12)
    assert runtime.position_view()["positions_status"]["available"] is True


@pytest.mark.parametrize("overlap", ["active", "completed"])
def test_overlapping_action_read_cannot_replace_snapshot_or_cache(managed, overlap):
    runtime, broker, db = managed
    runtime._manage_cycle(10)
    accepted = runtime.positions_cache
    runtime.manager.evaluate.reset_mock()
    before = [dict(row) for row in db.query("SELECT * FROM open_positions")]
    broker.positions.return_value = [position("stale")]
    if overlap == "active":
        with runtime._position_mutation():
            runtime._manage_cycle(11)
    else:
        def read():
            with runtime._position_mutation():
                pass
            return [position("stale")]
        broker.positions.side_effect = read
        runtime._manage_cycle(11)
    assert runtime.positions_cache is accepted
    assert [dict(row) for row in db.query("SELECT * FROM open_positions")] == before
    runtime.manager.evaluate.assert_not_called()
    assert runtime.position_view()["positions_status"]["available"] is False


def test_concurrent_read_cannot_resurrect_position_removed_during_mutation(managed):
    runtime, broker, db = managed
    runtime._manage_cycle(10)
    accepted = runtime.positions_cache
    runtime.manager.evaluate.reset_mock()
    reading, release = Event(), Event()

    def read():
        reading.set()
        assert release.wait(5), "test did not release position read"
        return [position("new")]

    broker.positions.side_effect = read
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime._manage_cycle, 11)
        try:
            assert reading.wait(5), "management read did not start"
            with runtime._position_mutation():
                db.execute("DELETE FROM open_positions WHERE ticket='new'")
        finally:
            release.set()
        future.result(timeout=10)
    assert {row["ticket"] for row in db.query("SELECT ticket FROM open_positions")} == {"kept"}
    assert runtime.positions_cache is accepted
    runtime.manager.evaluate.assert_not_called()
    assert runtime.position_view()["positions_status"]["available"] is False


@pytest.mark.parametrize("damage", ["before", "account_read", "adapter_read", "foreign", "duplicate"])
def test_close_all_rejects_unowned_or_invalid_read_before_any_close(managed, damage):
    runtime, broker, _ = managed
    runtime.notifier = Mock()
    runtime.gateway.close = Mock(return_value={"ok": True})
    if damage == "before":
        broker.account_info.return_value.login = "456"
    elif damage in ("account_read", "adapter_read"):
        def read():
            if damage == "account_read":
                broker.account_info.return_value.login = "456"
            else:
                runtime.registry.get.return_value = Mock(id="other")
            return [position("new")]
        broker.positions.side_effect = read
    else:
        broker.positions.return_value = ([position("new", "other")] if damage == "foreign"
                                         else [position("new"), position("new")])
    with pytest.raises(BrokerError):
        runtime.close_all()
    runtime.gateway.close.assert_not_called()
    assert runtime.position_view()["positions_status"]["available"] is False


@pytest.mark.parametrize("switch", ["adapter", "account"])
def test_close_all_stops_after_selection_or_account_changes_during_close(managed, switch):
    runtime, broker, _ = managed
    runtime.notifier = Mock()
    broker.positions.return_value = [position("first"), position("second")]

    def close(adapter, ticket, **kwargs):
        assert adapter is broker
        if switch == "adapter":
            runtime.registry.get.return_value = Mock(id="other")
        else:
            broker.account_info.return_value.login = "456"
        return {"ok": True}

    runtime.gateway.close = Mock(side_effect=close)
    result = runtime.close_all()
    assert result["ok"] is False
    assert result["unknown"] == 1
    assert result["not_attempted"] == 1
    assert runtime.gateway.close.call_count == 1
    assert "flattened" not in str(runtime.notifier.emit.call_args_list)


@pytest.mark.parametrize("outcomes", [[True, True], [True, False], [False, False], []])
def test_close_all_reports_acknowledgements_not_flattened_exposure(managed, outcomes):
    runtime, broker, _ = managed
    runtime.notifier = Mock()
    broker.positions.return_value = [position(str(i)) for i in range(len(outcomes))]
    runtime.gateway.close = Mock(side_effect=[{"ok": ok} for ok in outcomes])
    result = runtime.close_all()
    assert result["ok"] is all(outcomes)
    assert result["attempted"] == len(outcomes)
    assert result["accepted"] == sum(outcomes)
    assert result["rejected"] == len(outcomes) - sum(outcomes)
    assert result["exposure_verified"] is False
    assert all(call.args[0] is broker for call in runtime.gateway.close.call_args_list)
    assert "flattened" not in str(runtime.notifier.emit.call_args_list)
    assert runtime.position_view()["positions_status"]["available"] is False


@pytest.mark.parametrize("stage", ["send", "before_second"])
def test_close_all_preserves_partial_results_and_stops_without_retry(managed, stage):
    runtime, broker, _ = managed
    runtime.notifier = Mock()
    broker.positions.return_value = [position("first"), position("second"), position("third")]

    def close(adapter, ticket, **kwargs):
        if ticket == "first":
            return {"ok": True}
        raise RuntimeError("sensitive adapter detail must not escape")

    runtime.gateway.close = Mock(side_effect=close)
    if stage == "before_second":
        original = runtime.gateway._assert_account
        calls = 0

        def check(adapter):
            nonlocal calls
            calls += 1
            if calls == 5:
                raise BrokerError("sensitive owner detail must not escape")
            return original(adapter)

        runtime.gateway._assert_account = check
    result = runtime.close_all()
    assert result["ok"] is False
    assert result["accepted"] == 1
    assert result["rejected"] == 0
    assert result["unknown"] == (1 if stage == "send" else 0)
    assert result["not_attempted"] == (1 if stage == "send" else 2)
    assert result["attempted"] == (2 if stage == "send" else 1)
    assert result["reconciliation_required"] is True
    assert result["exposure_verified"] is False
    assert result["closed"][0]["ticket"] == "first"
    assert "sensitive" not in str(result)
    assert runtime.gateway.close.call_count == result["attempted"]
    assert "flattened" not in str(runtime.notifier.emit.call_args_list)


@pytest.mark.parametrize("reply", [{}, {"ok": None}, {"ok": "true"}, {"ok": 1}, None])
def test_close_all_malformed_acknowledgement_is_unknown_and_stops(managed, reply):
    runtime, broker, _ = managed
    runtime.notifier = Mock()
    broker.positions.return_value = [position("first"), position("second")]
    runtime.gateway.close = Mock(return_value=reply)
    result = runtime.close_all()
    assert result["ok"] is False
    assert result["unknown"] == 1
    assert result["rejected"] == 0
    assert result["not_attempted"] == 1
    assert runtime.gateway.close.call_count == 1


def test_close_all_notification_failure_does_not_discard_outcomes(managed):
    runtime, broker, _ = managed
    runtime.notifier = Mock()
    runtime.notifier.emit.side_effect = RuntimeError("private notification error")
    broker.positions.return_value = [position("first"), position("second")]
    runtime.gateway.close = Mock(side_effect=[{"ok": True}, RuntimeError("unknown send")])
    result = runtime.close_all()
    assert result["accepted"] == 1 and result["unknown"] == 1
    assert result["notification_failed"] is True
    assert result["exposure_verified"] is False
    assert "private" not in str(result)


def test_close_all_route_preserves_partial_result_contract(managed):
    from services.api_gateway.routes.trading import close_all

    runtime, broker, _ = managed
    runtime.notifier = Mock()
    broker.positions.return_value = [position("first"), position("second")]
    runtime.gateway.close = Mock(side_effect=[{"ok": False}, RuntimeError("unknown send")])
    result = close_all(runtime=runtime, user={"email": "test@example.invalid"})
    assert result["ok"] is False
    assert result["attempted"] == 2
    assert result["rejected"] == 1 and result["unknown"] == 1
    assert result["exposure_verified"] is False


@pytest.mark.parametrize("kind", ["modify", "partial_close", "close"])
@pytest.mark.parametrize("outcome", ["accepted", "rejected", "unknown", "exception"])
def test_management_notifications_report_acknowledgement_not_execution(managed, kind, outcome):
    runtime, _, _ = managed
    runtime.notifier = Mock()
    reply = {"accepted": True, "rejected": False, "unknown": None}.get(outcome)
    operation = Mock(side_effect=RuntimeError("private send detail")) if outcome == "exception" else Mock(
        return_value=reply if kind == "modify" else {"ok": reply})
    setattr(runtime.gateway, "modify" if kind == "modify" else "close", operation)
    action = SimpleNamespace(kind=kind, ticket="new", new_sl=1995, volume=0.05,
                             reason="test", note="proposed management change")
    if outcome == "exception":
        with pytest.raises(RuntimeError, match="private send detail"):
            TradingRuntime._apply_action(runtime, action, {})
    else:
        TradingRuntime._apply_action(runtime, action, {})
    runtime.notifier.emit.assert_called_once()
    level, title, message = runtime.notifier.emit.call_args.args
    expected = "unknown" if outcome == "exception" or (kind == "modify" and outcome != "accepted") else outcome
    assert expected in title.lower()
    assert "not been verified" in message
    assert "reconcile before" in message.lower()
    assert level != "success"
    assert "Stop moved" not in title and "Position closed" not in title
    assert "private send detail" not in message
    operation.assert_called_once()


@pytest.mark.parametrize("fails", [False, True])
def test_management_notification_failure_preserves_action_outcome_without_retry(managed, fails):
    runtime, _, _ = managed
    runtime.notifier = Mock()
    runtime.notifier.emit.side_effect = ValueError("private notification detail")
    runtime.gateway.close = Mock(side_effect=RuntimeError("original action failure")) if fails else Mock(
        return_value={"ok": True})
    action = SimpleNamespace(kind="close", ticket="new", reason="test", note="test")
    if fails:
        with pytest.raises(RuntimeError, match="original action failure"):
            TradingRuntime._apply_action(runtime, action, {})
    else:
        TradingRuntime._apply_action(runtime, action, {})
    runtime.gateway.close.assert_called_once()
    runtime._log_error.assert_called_once()
    assert "private notification detail" not in str(runtime._log_error.call_args)


def test_overlapping_mutations_only_allow_refresh_after_all_finish(managed):
    runtime, _, _ = managed
    with runtime._position_mutation():
        with runtime._position_mutation():
            runtime._manage_cycle(10)
            assert runtime.position_view()["positions_status"]["available"] is False
        runtime._manage_cycle(11)
        assert runtime.position_view()["positions_status"]["available"] is False
    assert runtime._positions_mutations == 0
    assert runtime.position_view()["positions_status"]["available"] is False
    runtime._manage_cycle(12)
    assert runtime.position_view()["positions_status"]["available"] is True


@pytest.mark.parametrize("damage", [None, "workspace", "account", "payload_account", "missing",
                                   "stale", "position_age", "unavailable", "owner", "expired",
                                   "foreign_row", "switch", "nan_age", "combined_age", "empty"])
def test_replica_disclosure_requires_current_owned_frame(managed, damage):
    from services.api_gateway.cluster import LIVE_KEY, LocalSharedState

    runtime, broker, db = managed
    runtime._manage_cycle(10)
    identity = runtime.gateway._account(broker)
    runtime.shared = LocalSharedState(default_ttl=120)
    runtime.replica = True
    payload = {"account": {k: v for k, v in identity.items() if k != "workspace_id"},
               "positions": [position("leader").model_dump()],
               "positions_status": {"available": True, "age_seconds": 1.0}, "private": "leader-data"}
    frame = {"owner": "leader", "published_at": time.time(),
             "account_identity": dict(identity), "payload": payload}
    if damage == "workspace":
        frame["account_identity"]["workspace_id"] = "other"
    elif damage == "account":
        frame["account_identity"]["login"] = "456"
    elif damage == "payload_account":
        payload["account"]["login"] = "456"
    elif damage == "missing":
        del frame["account_identity"]
    elif damage == "stale":
        frame["published_at"] -= 11
    elif damage == "position_age":
        payload["positions_status"]["age_seconds"] = 11
    elif damage == "unavailable":
        payload["positions_status"]["available"] = False
    elif damage == "owner":
        db.execute("DELETE FROM kv WHERE key='account-owner:demo'")
    elif damage == "foreign_row":
        payload["positions"][0]["broker_id"] = "other"
    elif damage == "nan_age":
        payload["positions_status"]["age_seconds"] = float("nan")
    elif damage == "combined_age":
        payload["positions_status"]["age_seconds"] = 9
        frame["published_at"] -= 2
    elif damage == "empty":
        payload["positions"] = []
    elif damage == "switch":
        broker.account_info.side_effect = [broker.account_info.return_value, SimpleNamespace(
            broker_id="demo", login="456", server="Demo", currency="USD")]
    runtime.shared.publish(LIVE_KEY, frame)
    if damage == "expired":
        runtime.shared._items.clear()
        runtime._replica_frame = {"private": "cached-secret"}
    result = runtime.live_payload()
    if damage in (None, "empty"):
        assert result["positions"] == ([] if damage == "empty" else payload["positions"])
        assert result["positions_status"]["available"] is True
        assert result["positions_status"]["age_seconds"] >= 1
    else:
        assert result["positions"] == []
        assert result["positions_status"]["available"] is False
        assert "private" not in result
        assert result.get("account") is None
    assert db.kv_get("account-owner:demo") == (None if damage == "owner" else identity)


def test_replica_role_does_not_trust_cached_frame_after_expiry(managed):
    from services.api_gateway.cluster import LocalSharedState

    runtime, _, _ = managed
    runtime.shared = LocalSharedState()
    runtime.replica = True
    runtime.shared_status = {"backend": "redis"}
    runtime.lease = {"state": "blocked"}
    runtime._replica_frame = {"positions": [position().model_dump()]}
    assert runtime.role() == "blocked"


@pytest.mark.parametrize("damage", ["owner", "switch"])
def test_publication_does_not_bind_or_publish_unowned_payload(managed, damage):
    from services.api_gateway.cluster import LocalSharedState, LIVE_KEY

    runtime, broker, db = managed
    runtime.shared = LocalSharedState()
    runtime._owner, runtime._last_publish = "leader", 0
    runtime.live_payload = Mock(return_value={"private": "not-for-publication"})
    if damage == "owner":
        db.execute("DELETE FROM kv WHERE key='account-owner:demo'")
    else:
        def switched():
            broker.account_info.return_value.login = "456"
            return {"private": "not-for-publication"}
        runtime.live_payload.side_effect = switched
    runtime._maybe_publish()
    assert runtime.shared.read(LIVE_KEY) is None
    if damage == "owner":
        assert db.kv_get("account-owner:demo") is None
