"""Daily tick inventory metadata cannot silently change root or identity."""
import json
import shutil

import pandas as pd
import pytest

from services.market_data.tick_store import (
    TickStore, TickStoreError, coverage, manifest_path, read_day, write_days, write_manifest,
)
from services.market_data.ticks import tick_summary


def _registered(root):
    frame = pd.DataFrame({'t': [1767603600], 'bid': [2000.0], 'ask': [2000.25]})
    days = write_days(root, 'XAUUSD', frame, fmt='csv.gz')
    write_manifest(root, 'XAUUSD', source={}, days=days)
    return manifest_path(root, 'XAUUSD')


@pytest.mark.parametrize('consumer', ['coverage', 'store', 'summary', 'writer'])
@pytest.mark.parametrize('damage', ['root', 'symbol', 'schema', 'json', 'shape', 'duplicate'])
def test_manifest_damage_is_refused_without_repair(tmp_path, consumer, damage):
    path = _registered(tmp_path)
    payload = json.loads(path.read_text())
    if damage == 'root':
        payload['dataset_root'] = str(tmp_path / 'foreign')
    elif damage == 'symbol':
        payload['symbol'] = 'EURUSD'
    elif damage == 'schema':
        payload['schema'] = 999
    elif damage == 'shape':
        payload = []
    elif damage == 'duplicate':
        payload['days'] *= 2
    raw = '{' if damage == 'json' else json.dumps(payload)
    path.write_text(raw, encoding='utf-8')
    with pytest.raises(TickStoreError, match='manifest|provenance'):
        if consumer == 'coverage':
            coverage(tmp_path, 'XAUUSD')
        elif consumer == 'store':
            TickStore(tmp_path, 'XAUUSD')
        elif consumer == 'summary':
            tick_summary(tmp_path, 'XAUUSD')
        else:
            write_manifest(tmp_path, 'XAUUSD', source={}, days=[])
    assert path.read_text(encoding='utf-8') == raw


def test_copied_manifest_is_not_adopted_by_another_root(tmp_path):
    owned = tmp_path / 'owned'
    _registered(owned)
    foreign = tmp_path / 'foreign'
    shutil.copytree(owned, foreign)
    with pytest.raises(TickStoreError, match='manifest|provenance'):
        TickStore(foreign, 'XAUUSD')


def test_writer_cannot_override_manifest_identity_through_extras(tmp_path):
    path = _registered(tmp_path)
    before = path.read_bytes()
    with pytest.raises(TickStoreError, match='manifest|identity'):
        write_manifest(tmp_path, 'XAUUSD', source={}, days=[], extras={'symbol': 'EURUSD'})
    assert path.read_bytes() == before


@pytest.mark.parametrize('damage', ['data', 'missing-manifest', 'missing-entry', 'rows'])
def test_read_day_refuses_unregistered_or_changed_bytes(tmp_path, damage):
    path = _registered(tmp_path)
    payload = json.loads(path.read_text())
    data = tmp_path / 'ticks' / 'XAUUSD' / '2026-01-05.csv.gz'
    if damage == 'data':
        import gzip
        data.write_bytes(gzip.compress(b't,bid,ask\n1767603600,1,2\n'))
    elif damage == 'missing-manifest':
        path.unlink()
    else:
        if damage == 'missing-entry':
            payload['days'] = []
        else:
            payload['days'][0]['rows'] = 99
        path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(TickStoreError, match='manifest|registered|corrupt|integrity'):
        read_day(tmp_path, 'XAUUSD', '2026-01-05')


def test_changed_stored_bytes_are_refused_before_pandas(tmp_path, monkeypatch):
    _registered(tmp_path)
    data = tmp_path / 'ticks' / 'XAUUSD' / '2026-01-05.csv.gz'
    raw = bytearray(data.read_bytes())
    raw[4] ^= 1  # gzip timestamp changes without changing decompressed ticks or length.
    data.write_bytes(raw)
    def forbidden(*args, **kwargs):
        pytest.fail('changed stored bytes must not reach the parser')
    monkeypatch.setattr(pd, 'read_csv', forbidden)
    with pytest.raises(TickStoreError, match='integrity|corrupt'):
        read_day(tmp_path, 'XAUUSD', '2026-01-05')