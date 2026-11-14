"""Legacy layout must verify local registration before parsing stored ticks."""
import json

import pytest

from services.market_data.ticks import TickBook, import_ticks, tick_summary
from services.market_data.tick_store import TickStoreError, legacy_tick_path


@pytest.mark.parametrize('consumer', ['load', 'summary', 'import'])
@pytest.mark.parametrize('damage', ['missing', 'root', 'symbol', 'json', 'bytes'])
def test_legacy_invalid_registration_is_refused(tmp_path, consumer, damage):
    source = tmp_path / 'source.csv'
    source.write_text('time,bid,ask\n2026-01-05 09:00:00,2000,2000.25\n')
    import_ticks(source, 'XAUUSD', tmp_path, layout='file')
    meta = legacy_tick_path(tmp_path, 'XAUUSD', metadata=True)
    data = legacy_tick_path(tmp_path, 'XAUUSD')
    payload = json.loads(meta.read_text())
    if damage == 'missing':
        meta.unlink()
    elif damage == 'bytes':
        data.write_bytes(data.read_bytes() + b'tamper')
    elif damage == 'json':
        meta.write_text('{')
    else:
        payload['dataset_root' if damage == 'root' else 'symbol'] = 'foreign'
        meta.write_text(json.dumps(payload))
    before = data.read_bytes()
    with pytest.raises(TickStoreError, match='legacy|provenance|integrity'):
        if consumer == 'load':
            TickBook.load(tmp_path, 'XAUUSD')
        elif consumer == 'summary':
            tick_summary(tmp_path, 'XAUUSD')
        else:
            import_ticks(source, 'XAUUSD', tmp_path, layout='file')
    assert data.read_bytes() == before