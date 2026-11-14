"""Pruning cannot delete evidence before validating its tick index."""
import json

import pytest

from services.market_data.tick_store import TickStore, TickStoreError, manifest_path, prune_days, read_manifest
from services.market_data.ticks import import_ticks


def _registered(root):
    source = root / 'source.csv'
    source.write_text('time,bid,ask\n2026-01-05 09:00:00,2000,2000.25\n'
                      '2026-01-06 09:00:00,2001,2001.25\n')
    import_ticks(source, 'XAUUSD', root, fmt='csv.gz')
    return manifest_path(root, 'XAUUSD')


@pytest.mark.parametrize('damage', ['missing', 'json', 'root'])
def test_prune_validates_index_before_deleting_any_day(tmp_path, damage):
    path = _registered(tmp_path)
    if damage == 'missing':
        path.unlink()
    elif damage == 'json':
        path.write_text('{')
    else:
        payload = json.loads(path.read_text())
        payload['dataset_root'] = 'foreign'
        path.write_text(json.dumps(payload))
    before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
    with pytest.raises(TickStoreError, match='manifest|index'):
        prune_days(tmp_path, 'XAUUSD', 1)
    assert {p.name: p.read_bytes() for p in path.parent.iterdir()} == before


def test_successful_prune_updates_registered_totals(tmp_path):
    _registered(tmp_path)
    prune_days(tmp_path, 'XAUUSD', 1)
    payload = read_manifest(tmp_path, 'XAUUSD')
    assert payload['rows'] == 1
    assert payload['days_covered'] == 1
    assert [e['day'] for e in payload['days']] == ['2026-01-06']
    store = TickStore(tmp_path, 'XAUUSD')
    assert store.rows() == 1
    assert store.first_t == payload['days'][0]['first_t']