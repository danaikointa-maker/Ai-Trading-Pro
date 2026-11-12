"""Tick path selection rejects untrusted identifiers before filesystem access."""
import pytest

from services.market_data.tick_store import (
    TickStoreError, available_days, day_path, manifest_path, read_day, symbol_dir,
)


@pytest.mark.parametrize("symbol", ["", ".", "..", "../foreign", "a/b", "a\\b",
                                     "C:\\foreign", "a:stream", "XAUUSD.", "CON"])
@pytest.mark.parametrize("operation", [symbol_dir, manifest_path, available_days])
def test_tick_symbol_cannot_select_a_path(tmp_path, symbol, operation):
    with pytest.raises(TickStoreError, match="symbol|path"):
        operation(tmp_path, symbol)


@pytest.mark.parametrize("day", ["../foreign", "2026-01-01/other", "2026-02-30",
                                 "2026-1-01", "C:\\foreign", "2026-01-01:stream"])
def test_tick_day_is_a_calendar_partition(tmp_path, day):
    with pytest.raises(TickStoreError, match="day|path"):
        read_day(tmp_path, "XAUUSD", day)


@pytest.mark.parametrize("fmt", ["../csv", "csv", "csv.gz/other", "parquet:stream"])
def test_tick_format_cannot_select_a_path(tmp_path, fmt):
    with pytest.raises(TickStoreError, match="format|path"):
        day_path(tmp_path, "XAUUSD", "2026-01-01", fmt)


@pytest.mark.parametrize("part", ["root", "symbol", "manifest", "day"])
def test_tick_links_are_rejected(tmp_path, part):
    root = tmp_path / "owned"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "data").write_text("private", encoding="utf-8")
    folder = root / "ticks" / "XAUUSD"
    folder.mkdir(parents=True)
    selected = {"root": root / "ticks", "symbol": folder,
                "manifest": folder / "manifest.json",
                "day": folder / "2026-01-01.csv.gz"}[part]
    try:
        if part == "root":
            folder.rmdir()
        if selected.is_dir():
            selected.rmdir()
        selected.symlink_to(foreign if part in ("root", "symbol") else foreign / "data",
                            target_is_directory=part in ("root", "symbol"))
    except OSError:
        pytest.skip("symlink creation requires Windows privilege")
    operation = (lambda: manifest_path(root, "XAUUSD")) if part == "manifest" else (
        lambda: read_day(root, "XAUUSD", "2026-01-01"))
    with pytest.raises(TickStoreError, match="linked|path"):
        operation()
    assert (foreign / "data").read_text(encoding="utf-8") == "private"


def test_tick_symbol_and_day_paths_remain_compatible(tmp_path):
    assert day_path(tmp_path, "xauusd", "2026-01-01", "csv.gz") == (
        tmp_path / "ticks" / "XAUUSD" / "2026-01-01.csv.gz")