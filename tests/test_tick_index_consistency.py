"""Tick index totals must agree with day entries before use or publication."""
import json

import pytest

from services.market_data.tick_store import TickStore, TickStoreError, manifest_path
from services.market_data.ticks import import_ticks, tick_summary


def _import(root):
    source = root / 'source.csv'
    source.write_text('time,bid,ask\n2026-01-05 09:00:00,2000,2000.25\n')
    import_ticks(source, 'XAUUSD', root, fmt='csv.gz')
    return manifest_path(root, 'XAUUSD')


@pytest.mark.parametrize('field,value', [('rows', 999), ('rows', True), ('days_covered', 2),
                                        ('first_t', 1), ('last_t', 2)])
def test_invalid_aggregate_is_not_used(tmp_path, field, value):
    path = _import(tmp_path)
    payload = json.loads(path.read_text())
    payload[field] = value
    path.write_text(json.dumps(payload))
    with pytest.raises(TickStoreError, match='manifest|index'):
        TickStore(tmp_path, 'XAUUSD')


def test_daily_summary_does_not_fallback_when_manifest_missing(tmp_path):
    path = _import(tmp_path)
    path.unlink()
    with pytest.raises(TickStoreError, match='manifest|index'):
        tick_summary(tmp_path, 'XAUUSD')


def test_invalid_manifest_preserves_daily_data_before_reimport(tmp_path):
    path = _import(tmp_path)
    payload = json.loads(path.read_text())
    payload['rows'] = 999
    path.write_text(json.dumps(payload))
    data = tmp_path / 'ticks/XAUUSD/2026-01-05.csv.gz'
    before = data.read_bytes()
    with pytest.raises(TickStoreError, match='manifest|index'):
        import_ticks(tmp_path / 'source.csv', 'XAUUSD', tmp_path, fmt='csv.gz')
    assert data.read_bytes() == before


def test_replaced_index_invalidates_cached_day(tmp_path):
    path = _import(tmp_path)
    store = TickStore(tmp_path, 'XAUUSD')
    assert len(store.day_frame('2026-01-05')) == 1
    payload = json.loads(path.read_text())
    payload['symbol'] = 'EURUSD'
    path.write_text(json.dumps(payload))
    with pytest.raises(TickStoreError, match='manifest|index'):
        store.day_frame('2026-01-05')