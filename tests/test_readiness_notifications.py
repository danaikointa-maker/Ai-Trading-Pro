"""Readiness alert transitions must not flood one alert per decision cycle."""
from types import SimpleNamespace

from packages.shared_schemas.models import Signal, SignalAction, SignalReadiness, SignalStatus
from services.api_gateway.state import TradingRuntime


class Recorder:
    def __init__(self):
        self.calls = []

    def emit(self, *args, **kwargs):
        self.calls.append((args, kwargs))


def test_wait_only_notifies_after_a_meaningful_transition():
    recorder = Recorder()
    runtime = SimpleNamespace(_last_readiness={}, notifier=recorder)
    signal = Signal(id="S1", t=100, symbol="XAUUSD", timeframe="M5", broker_id="sim",
                    action=SignalAction.wait, status=SignalStatus.weak, score=55,
                    strategy="none", regime="trending", readiness=SignalReadiness.wait,
                    readiness_reason="ราคาอยู่นอกโซน")

    TradingRuntime._maybe_alert_readiness(runtime, signal)
    TradingRuntime._maybe_alert_readiness(runtime, signal)
    assert recorder.calls == []  # initial idle state is intentionally quiet

    signal.readiness = SignalReadiness.ready
    TradingRuntime._maybe_alert_readiness(runtime, signal)
    assert recorder.calls == []  # existing BUY/SELL notifier handles READY

    signal.readiness = SignalReadiness.blocked
    signal.readiness_reason = "data feed stale"
    TradingRuntime._maybe_alert_readiness(runtime, signal)
    TradingRuntime._maybe_alert_readiness(runtime, signal)
    assert len(recorder.calls) == 1
    assert recorder.calls[0][0][0] == "warning"
    assert recorder.calls[0][1]["dedupe_seconds"] == 300

    signal.readiness = SignalReadiness.wait
    TradingRuntime._maybe_alert_readiness(runtime, signal)
    assert len(recorder.calls) == 2
    assert recorder.calls[1][0][0] == "info"


def test_initial_safety_block_warns_once():
    recorder = Recorder()
    runtime = SimpleNamespace(_last_readiness={}, notifier=recorder)
    signal = Signal(id="S2", t=100, symbol="EURUSD", timeframe="M5", broker_id="sim",
                    action=SignalAction.wait, status=SignalStatus.weak, score=55,
                    strategy="none", regime="trending", readiness=SignalReadiness.blocked,
                    readiness_reason="news lockout")
    TradingRuntime._maybe_alert_readiness(runtime, signal)
    TradingRuntime._maybe_alert_readiness(runtime, signal)
    assert len(recorder.calls) == 1
