"""Candle artifact gates never adopt legacy files or follow linked output files."""
import hashlib
import json
import shutil
from unittest.mock import Mock

import pytest

from services.market_data.dataset import DatasetError, import_candles, load_dataset


@pytest.fixture
def imported(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("t,o,h,l,c,v\n1800000000,10,12,9,11,1\n1800000060,11,13,10,12,2\n", encoding="utf-8")
    root = tmp_path / "datasets"
    meta = import_candles(source, "XAUUSD", root)
    return source, root, meta


def test_import_records_full_source_and_output_digests(imported):
    source, root, meta = imported
    assert meta["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert meta["csv_sha256"] == hashlib.sha256((root / meta["csv"]).read_bytes()).hexdigest()
    assert meta["dataset_root"] == str(root.resolve())
    assert len(load_dataset(root, "XAUUSD")) == 2


@pytest.mark.parametrize("damage", ["csv", "missing", "legacy", "invalid", "shape", "symbol", "root", "digest"])
def test_untrusted_dataset_rejected_before_csv_parse(imported, monkeypatch, damage):
    _, root, meta = imported
    sidecar = root / "XAUUSD_M1.meta.json"
    if damage == "csv":
        (root / meta["csv"]).write_bytes((root / meta["csv"]).read_bytes() + b"\n")
    elif damage == "missing":
        sidecar.unlink()
    elif damage == "invalid":
        sidecar.write_text("{", encoding="utf-8")
    elif damage == "shape":
        sidecar.write_text("[]", encoding="utf-8")
    else:
        if damage == "legacy":
            meta.pop("schema", None)
        else:
            meta[{"symbol": "symbol", "root": "dataset_root", "digest": "csv_sha256"}[damage]] = "foreign"
        sidecar.write_text(json.dumps(meta), encoding="utf-8")
    loader = Mock(side_effect=AssertionError("untrusted CSV must not be parsed"))
    monkeypatch.setattr("services.market_data.dataset.pd.read_csv", loader)
    with pytest.raises(DatasetError, match="provenance|quarantin|digest"):
        load_dataset(root, "XAUUSD")
    loader.assert_not_called()


def test_copying_dataset_to_another_root_does_not_adopt_it(imported, tmp_path):
    _, root, _ = imported
    foreign = tmp_path / "foreign"
    shutil.copytree(root, foreign)
    with pytest.raises(DatasetError, match="provenance|quarantin"):
        load_dataset(foreign, "XAUUSD")


@pytest.mark.parametrize("symbol", ["../outside", "a/b", "a\\b", "a:stream", "", "CON", "a."])
def test_invalid_symbol_rejected_before_read_or_write(tmp_path, monkeypatch, symbol):
    loader = Mock(side_effect=AssertionError("invalid symbol must not read source"))
    monkeypatch.setattr("services.market_data.dataset.load_candles", loader)
    with pytest.raises(DatasetError, match="identifier"):
        import_candles(tmp_path / "missing.csv", symbol, tmp_path / "out")
    with pytest.raises(DatasetError, match="identifier"):
        load_dataset(tmp_path / "out", symbol)
    loader.assert_not_called()
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("part", ["XAUUSD_M1.csv", "XAUUSD_M1.meta.json"])
def test_linked_dataset_artifacts_are_not_read_or_overwritten(imported, tmp_path, part):
    source, root, _ = imported
    target = root / part
    external = tmp_path / "external"
    external.write_bytes(target.read_bytes())
    target.unlink()
    try:
        target.symlink_to(external)
    except OSError:
        pytest.skip("symlink creation requires Windows privilege")
    before = external.read_bytes()
    with pytest.raises(DatasetError, match="path|artifact|provenance"):
        load_dataset(root, "XAUUSD")
    with pytest.raises(DatasetError, match="path|artifact|exists"):
        import_candles(source, "XAUUSD", root)
    assert external.read_bytes() == before


def test_reimport_does_not_overwrite_or_adopt_existing_artifacts(imported):
    source, root, _ = imported
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(DatasetError, match="exists|artifact"):
        import_candles(source, "XAUUSD", root)
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


def test_load_parses_the_verified_bytes_even_if_path_changes(imported, monkeypatch):
    _, root, _ = imported
    import pandas as pd

    reader = pd.read_csv
    def swapped(path, *args, **kwargs):
        (root / "XAUUSD_M1.csv").write_text("untrusted replacement", encoding="utf-8")
        return reader(path, *args, **kwargs)
    monkeypatch.setattr("services.market_data.dataset.pd.read_csv", swapped)
    assert len(load_dataset(root, "XAUUSD")) == 2


@pytest.mark.parametrize("script", ["import_candles", "evaluate_dataset"])
def test_dataset_cli_defaults_to_configured_workspace(tmp_path, monkeypatch, script):
    import importlib
    import sys
    from types import SimpleNamespace

    module = importlib.import_module(f"scripts.{script}")
    owned = tmp_path / "workspace-datasets"
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(paths={"datasets": owned}), raising=False)
    monkeypatch.setattr(sys, "argv", [script, "--csv", str(tmp_path / "source.csv"), "--symbol", "XAUUSD"])
    observed = []
    def stop(source, symbol, out_dir, **kwargs):
        observed.append(out_dir)
        raise DatasetError("test stops before IO")
    monkeypatch.setattr(module, "import_candles", stop)
    assert module.main() == 2
    assert observed and __import__("pathlib").Path(observed[0]) == owned


@pytest.mark.parametrize("script,flag", [("import_candles", "--out-dir"), ("evaluate_dataset", "--dataset-dir")])
def test_dataset_cli_cannot_select_a_foreign_root(tmp_path, monkeypatch, script, flag):
    import importlib
    import sys
    from types import SimpleNamespace

    module = importlib.import_module(f"scripts.{script}")
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(paths={"datasets": tmp_path / "owned"}), raising=False)
    monkeypatch.setattr(sys, "argv", [script, "--csv", str(tmp_path / "source.csv"), "--symbol", "XAUUSD",
                                      flag, str(tmp_path / "foreign")])
    loader = Mock(side_effect=AssertionError("foreign root must be rejected before import"))
    monkeypatch.setattr(module, "import_candles", loader)
    assert module.main() == 2
    loader.assert_not_called()