"""Tick CLI cannot bypass configured workspace paths or leak storage exceptions."""
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from scripts import import_ticks as cli
from services.market_data.tick_store import TickStoreError


def test_tick_cli_refuses_foreign_root_before_import(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'reload_settings', lambda: SimpleNamespace(paths={'datasets': tmp_path / 'owned'}))
    monkeypatch.setattr(sys, 'argv', ['import_ticks', '--csv', 'source.csv', '--symbol', 'XAUUSD',
                                     '--data-dir', str(tmp_path / 'foreign')])
    importer = Mock(return_value={})
    monkeypatch.setattr(cli, 'import_ticks', importer)
    assert cli.main() == 1
    importer.assert_not_called()


def test_tick_cli_handles_store_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'reload_settings', lambda: SimpleNamespace(paths={'datasets': tmp_path}))
    monkeypatch.setattr(sys, 'argv', ['import_ticks', '--csv', 'source.csv', '--symbol', 'XAUUSD'])
    monkeypatch.setattr(cli, 'import_ticks', Mock(side_effect=TickStoreError('tick manifest invalid')))
    assert cli.main() == 1


@pytest.mark.parametrize('selected', ['default', 'child'])
def test_tick_cli_preserves_owned_root_selection(tmp_path, monkeypatch, selected):
    owned = tmp_path / 'owned'
    target = owned if selected == 'default' else owned / 'child'
    monkeypatch.setattr(cli, 'reload_settings', lambda: SimpleNamespace(paths={'datasets': owned}))
    argv = ['import_ticks', '--csv', 'source.csv', '--symbol', 'XAUUSD']
    if selected == 'child':
        argv += ['--data-dir', str(target)]
    monkeypatch.setattr(sys, 'argv', argv)
    importer = Mock(return_value={'path': str(target)})
    monkeypatch.setattr(cli, 'import_ticks', importer)
    assert cli.main() == 0
    assert importer.call_args.args[2] == target.resolve()