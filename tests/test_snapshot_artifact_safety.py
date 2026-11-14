"""Snapshot manifests cannot select arbitrary files or adopt damaged artifacts."""
import gzip
import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

from services.market_data.snapshots import SnapshotError, list_snapshots, load_snapshot, save_snapshot


@pytest.fixture
def saved(tmp_path):
    root = tmp_path / "owned"
    frame = pd.DataFrame({"t": [1800000000, 1800000060], "o": [10., 11.],
                          "h": [12., 13.], "l": [9., 10.], "c": [11., 12.], "v": [1, 2]})
    snapshot = save_snapshot(root, "XAUUSD", "M1", frame, "simulated fixture")
    return root, frame, snapshot, root / "snapshots" / f"{snapshot.id}.json"


@pytest.mark.parametrize("damage", ["external", "id", "sha256", "rows", "first_t", "last_t", "bytes",
                                   "legacy", "root", "malformed", "shape"])
def test_bad_manifest_is_refused(saved, tmp_path, monkeypatch, damage):
    root, _, snapshot, manifest = saved
    meta = json.loads(manifest.read_text())
    if damage == "external":
        foreign = tmp_path / "foreign.csv.gz"
        shutil.copyfile(snapshot.path, foreign)
        meta["path"] = str(foreign)
    elif damage == "legacy":
        meta.pop("schema", None)
        meta.pop("dataset_root", None)
    elif damage == "root":
        meta["dataset_root"] = "foreign"
    elif damage in ("rows", "first_t", "last_t", "bytes"):
        meta[damage] += 1
    elif damage == "id":
        meta["id"] = "DS-0000000000"
    elif damage == "sha256":
        meta["sha256"] = "0" * 64
    manifest.write_text("{" if damage == "malformed" else "[]" if damage == "shape" else json.dumps(meta))
    reader = Mock(wraps=pd.read_csv)
    monkeypatch.setattr("services.market_data.snapshots.pd.read_csv", reader)
    with pytest.raises(SnapshotError, match="snapshot|manifest|provenance"):
        load_snapshot(root, snapshot.id)
    if damage in ("external", "id", "sha256", "legacy", "root", "malformed", "shape"):
        reader.assert_not_called()


def test_snapshot_copy_does_not_grant_foreign_root_ownership(saved, tmp_path):
    root, _, snapshot, _ = saved
    foreign = tmp_path / "other-workspace"
    shutil.copytree(root, foreign)
    with pytest.raises(SnapshotError, match="provenance|path|root"):
        load_snapshot(foreign, snapshot.id)


@pytest.mark.parametrize("part", ["manifest", "data", "directory"])
def test_snapshot_links_cannot_read_write_or_appear_in_listing(saved, tmp_path, part):
    root, frame, snapshot, manifest = saved
    target = manifest if part == "manifest" else Path(snapshot.path) if part == "data" else manifest.parent
    foreign = tmp_path / f"foreign-{part}"
    target.rename(foreign)
    try:
        target.symlink_to(foreign, target_is_directory=part == "directory")
    except OSError:
        pytest.skip("symlink creation requires Windows privilege")
    before = {p.name: p.read_bytes() for p in foreign.iterdir()} if foreign.is_dir() else foreign.read_bytes()
    with pytest.raises(SnapshotError, match="path|artifact|root"):
        load_snapshot(root, snapshot.id)
    with pytest.raises(SnapshotError, match="path|artifact|root"):
        save_snapshot(root, "XAUUSD", "M1", frame, "simulated fixture")
    if part == "directory":
        with pytest.raises(SnapshotError, match="path|artifact|root"):
            list_snapshots(root)
    else:
        assert list_snapshots(root) == []
    after = {p.name: p.read_bytes() for p in foreign.iterdir()} if foreign.is_dir() else foreign.read_bytes()
    assert before == after


@pytest.mark.parametrize("damage", ["data", "manifest", "missing-data", "missing-manifest"])
def test_save_does_not_repair_or_reuse_unverified_existing_artifacts(saved, damage):
    root, frame, snapshot, manifest = saved
    data = Path(snapshot.path)
    if damage == "data":
        data.write_bytes(gzip.compress(b"different bytes"))
    elif damage == "manifest":
        manifest.write_text("{broken")
    else:
        (data if damage == "missing-data" else manifest).unlink()
    before = {p.name: p.read_bytes() for p in manifest.parent.iterdir()}
    with pytest.raises(SnapshotError, match="snapshot|artifact|manifest"):
        save_snapshot(root, "XAUUSD", "M1", frame, "simulated fixture")
    assert {p.name: p.read_bytes() for p in manifest.parent.iterdir()} == before


def test_same_content_with_conflicting_instrument_is_not_silently_reused(saved):
    root, frame, _, _ = saved
    with pytest.raises(SnapshotError, match="conflict|identity|symbol"):
        save_snapshot(root, "EURUSD", "M1", frame, "simulated fixture")


def test_listing_skips_malformed_and_foreign_path_manifests(saved, tmp_path):
    root, _, _, manifest = saved
    meta = json.loads(manifest.read_text())
    meta["path"] = str(tmp_path / "private.csv.gz")
    manifest.write_text(json.dumps(meta))
    (manifest.parent / "DS-BROKEN.json").write_text("[]")
    assert list_snapshots(root) == []


@pytest.mark.parametrize("snapshot_id", ["C:private", "DS-foo:bar", "DS-name.", "", "../outside"])
def test_invalid_snapshot_id_never_creates_directories(tmp_path, snapshot_id):
    root = tmp_path / "absent"
    with pytest.raises(SnapshotError, match="invalid"):
        load_snapshot(root, snapshot_id)
    assert not root.exists()


def test_malformed_deflate_is_a_snapshot_error_not_a_raw_decoder_exception(saved):
    root, _, snapshot, _ = saved
    Path(snapshot.path).write_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff\x07" + b"\x00" * 8)
    with pytest.raises(SnapshotError, match="corrupt|quarantin"):
        load_snapshot(root, snapshot.id)


def test_snapshot_parse_uses_hashed_bytes_even_if_file_changes(saved, monkeypatch):
    root, _, snapshot, _ = saved
    reader = pd.read_csv
    def replaced(path, *args, **kwargs):
        Path(snapshot.path).write_bytes(b"replacement")
        return reader(path, *args, **kwargs)
    monkeypatch.setattr("services.market_data.snapshots.pd.read_csv", replaced)
    _, frame = load_snapshot(root, snapshot.id)
    assert len(frame) == 2