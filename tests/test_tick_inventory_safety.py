"""Inventory accepts calendar partitions, not arbitrary filesystem names."""
import pytest

from services.market_data.tick_store import TickStoreError, available_days


def test_csv_inventory_returns_calendar_day_not_csv_stem(tmp_path):
    folder = tmp_path / 'ticks' / 'XAUUSD'
    folder.mkdir(parents=True)
    (folder / '2026-01-05.csv.gz').write_bytes(b'not parsed by inventory')
    assert available_days(tmp_path, 'XAUUSD') == ['2026-01-05']


@pytest.mark.parametrize('name', ['garbage.parquet', '2026-02-30.csv.gz',
                                 '2026-1-05.parquet', '2026-01-05.extra.csv.gz'])
def test_inventory_refuses_invalid_partition_name(tmp_path, name):
    folder = tmp_path / 'ticks' / 'XAUUSD'
    folder.mkdir(parents=True)
    (folder / name).write_bytes(b'keep')
    with pytest.raises(TickStoreError, match='day|path|inventory'):
        available_days(tmp_path, 'XAUUSD')
    assert (folder / name).read_bytes() == b'keep'


@pytest.mark.parametrize('kind', ['link', 'dangling', 'directory'])
def test_inventory_refuses_non_regular_partition(tmp_path, kind):
    folder = tmp_path / 'ticks' / 'XAUUSD'
    folder.mkdir(parents=True)
    path = folder / '2026-01-05.csv.gz'
    foreign = tmp_path / 'foreign'
    if kind == 'directory':
        path.mkdir()
    else:
        if kind == 'link':
            foreign.write_bytes(b'keep')
        try:
            path.symlink_to(foreign)
        except OSError:
            pytest.skip('symlink creation requires Windows privilege')
    with pytest.raises(TickStoreError, match='linked|path|inventory'):
        available_days(tmp_path, 'XAUUSD')


def test_inventory_deduplicates_formats_and_ignores_staging(tmp_path):
    folder = tmp_path / 'ticks' / 'XAUUSD'
    folder.mkdir(parents=True)
    for name in ['2026-01-05.parquet', '2026-01-05.csv.gz', 'bad.parquet.tmp', 'manifest.json']:
        (folder / name).write_bytes(b'keep')
    assert available_days(tmp_path, 'XAUUSD') == ['2026-01-05']