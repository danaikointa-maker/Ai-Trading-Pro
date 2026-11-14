"""Status distinguishes quarantined ticks from usable registered data."""
from types import SimpleNamespace

import pytest

from services.api_gateway.routes.datasets import _tick_symbols, tick_status
from services.market_data.tick_store import manifest_path
from services.market_data.ticks import import_ticks


def test_status_reports_quarantine_without_raw_index_or_path(tmp_path):
    source = tmp_path / 'source.csv'
    source.write_text('time,bid,ask\n2026-01-05 09:00:00,2000,2000.25\n')
    import_ticks(source, 'XAUUSD', tmp_path, fmt='csv.gz')
    path = manifest_path(tmp_path, 'XAUUSD')
    path.write_text('{private-sentinel')
    runtime = SimpleNamespace(settings=SimpleNamespace(paths={'datasets': tmp_path}))
    result = tick_status('XAUUSD', runtime, {'email': 'local-test'})
    assert result['used_for_intra_bar_ordering'] is False
    entry = result['ticks'][0]
    assert entry['available'] is False
    assert entry['status'] == 'quarantined'
    assert str(tmp_path) not in str(result)
    assert 'private-sentinel' not in str(result)
    assert path.read_text() == '{private-sentinel'


def test_status_keeps_valid_symbols_when_another_index_is_invalid(tmp_path):
    source = tmp_path / 'source.csv'
    source.write_text('time,bid,ask\n2026-01-05 09:00:00,2000,2000.25\n')
    for symbol in ('XAUUSD', 'EURUSD'):
        import_ticks(source, symbol, tmp_path, fmt='csv.gz')
    manifest_path(tmp_path, 'EURUSD').write_text('{')
    runtime = SimpleNamespace(settings=SimpleNamespace(paths={'datasets': tmp_path}))
    result = tick_status('', runtime, {})
    by_symbol = {entry['symbol']: entry for entry in result['ticks']}
    assert by_symbol['EURUSD']['available'] is False
    assert by_symbol['XAUUSD']['available'] is True
    assert result['used_for_intra_bar_ordering'] is True


def test_legacy_symbol_inventory_preserves_underscores(tmp_path):
    folder = tmp_path / 'ticks'
    folder.mkdir()
    (folder / 'XAU_USD_ticks.json').write_text('{}')
    assert _tick_symbols(tmp_path, '') == ['XAU_USD']


def test_status_inventory_does_not_follow_linked_tick_root(tmp_path):
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    (foreign / 'PRIVATE_ticks.json').write_text('{}')
    root = tmp_path / 'owned'
    root.mkdir()
    try:
        (root / 'ticks').symlink_to(foreign, target_is_directory=True)
    except OSError:
        pytest.skip('symlink creation requires Windows privilege')
    from services.market_data.tick_store import TickStoreError
    with pytest.raises(TickStoreError, match='linked|path'):
        _tick_symbols(root, '')