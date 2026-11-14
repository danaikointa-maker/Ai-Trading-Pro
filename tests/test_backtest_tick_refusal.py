"""A requested tick-assisted run cannot silently downgrade after load refusal."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from packages.shared_schemas.models import BacktestRequest
from services.api_gateway.routes import backtest
from services.market_data.tick_store import TickStoreError


@pytest.mark.parametrize('error', [TickStoreError('private-sentinel C:/private/ticks'),
                                  OSError('private-sentinel C:/private/ticks')])
def test_invalid_requested_ticks_do_not_publish_bar_only_report(tmp_path, monkeypatch, error):
    adapter = SimpleNamespace(id='local-test', symbol_spec=Mock(return_value=object()),
                              candles=Mock(return_value=object()))
    runtime = SimpleNamespace(
        db=SimpleNamespace(workspace_id='team-a', execute=Mock(), audit=Mock()),
        adapter=adapter, registry=SimpleNamespace(get=Mock(return_value=adapter)),
        settings=SimpleNamespace(paths={'datasets': tmp_path}, market_data={}),
        feed_mode='simulate', risk=object(), planner=object())
    engine = Mock()
    monkeypatch.setattr('services.backtest_engine.backtester.Backtester', Mock(return_value=engine))
    snapshot = SimpleNamespace(id='DS-LOCAL', as_dict=lambda: {'id': 'DS-LOCAL'})
    monkeypatch.setattr(backtest, 'save_snapshot', Mock(return_value=snapshot))
    monkeypatch.setattr(backtest.TickBook, 'load', Mock(side_effect=error))
    key = 'P2-TICK-REFUSAL'
    try:
        backtest._run_job(key, runtime, BacktestRequest(symbol='XAUUSD', bars=4000, use_ticks=True), 'local-test')
        assert backtest.JOBS[key]['state'] == 'error'
        engine.run.assert_not_called()
        runtime.db.execute.assert_not_called()
        assert 'private-sentinel' not in str(backtest.JOBS[key])
        assert 'C:/private' not in str(backtest.JOBS[key])
        assert backtest.JOBS[key]['workspace_id'] == 'team-a'
    finally:
        backtest.JOBS.pop(key, None)