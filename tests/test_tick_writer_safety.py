"""Pre-existing staging and legacy links must never redirect tick I/O."""
import pandas as pd
import pytest

from services.market_data.tick_store import TickStoreError, day_path, write_days
from services.market_data.ticks import TickBook, import_ticks, tick_path, tick_summary


def _frame():
    return pd.DataFrame({'t': [1767603600], 'bid': [2000.0], 'ask': [2000.25]})


@pytest.mark.parametrize('kind', ['file', 'link', 'dangling'])
def test_writer_refuses_existing_staging_artifact(tmp_path, kind):
    path = day_path(tmp_path, 'XAUUSD', '2026-01-05', 'csv.gz')
    path.parent.mkdir(parents=True)
    staging = path.with_suffix(path.suffix + '.tmp')
    foreign = tmp_path / 'foreign'
    if kind != 'dangling':
        foreign.write_bytes(b'keep')
    if kind == 'file':
        staging.write_bytes(b'keep')
    else:
        try:
            staging.symlink_to(foreign)
        except OSError:
            pytest.skip('symlink creation requires Windows privilege')
    with pytest.raises(TickStoreError, match='staging|path|write'):
        write_days(tmp_path, 'XAUUSD', _frame(), fmt='csv.gz')
    assert not path.exists()
    if kind != 'dangling':
        assert foreign.read_bytes() == b'keep'
    else:
        assert not foreign.exists()
    assert staging.is_symlink() if kind != 'file' else staging.read_bytes() == b'keep'


@pytest.mark.parametrize('symbol', ['../foreign', 'a\\b', 'a:stream', 'CON', ''])
def test_legacy_path_rejects_invalid_symbol(tmp_path, symbol):
    with pytest.raises(TickStoreError, match='symbol|path'):
        tick_path(tmp_path, symbol)


@pytest.mark.parametrize('operation', ['load', 'summary', 'import-data', 'import-manifest'])
def test_legacy_link_is_rejected_before_read_or_write(tmp_path, operation):
    folder = tmp_path / 'ticks'
    folder.mkdir()
    foreign = tmp_path / 'private'
    foreign.write_bytes(b'keep')
    suffix = 'json' if operation in ('summary', 'import-manifest') else 'csv.gz'
    link = folder / f'XAUUSD_ticks.{suffix}'
    try:
        link.symlink_to(foreign)
    except OSError:
        pytest.skip('symlink creation requires Windows privilege')
    source = tmp_path / 'export.csv'
    source.write_text('time,bid,ask\n2026-01-05 09:00:00,2000,2000.25\n', encoding='utf-8')
    with pytest.raises(TickStoreError, match='linked|path'):
        if operation == 'load':
            TickBook.load(tmp_path, 'XAUUSD')
        elif operation == 'summary':
            tick_summary(tmp_path, 'XAUUSD')
        else:
            import_ticks(source, 'XAUUSD', tmp_path, layout='file')
    assert foreign.read_bytes() == b'keep'
    if operation == 'import-manifest':
        assert not (folder / 'XAUUSD_ticks.csv.gz').exists()