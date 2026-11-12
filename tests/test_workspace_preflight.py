"""P2.5 identity rejection must precede persistent initialization changes."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from packages.persistence.db import Database


def seed(path, identity="team-a", *, legacy=False):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE retained(value TEXT)")
        conn.execute("INSERT INTO retained VALUES('keep')")
        if not legacy:
            conn.execute("CREATE TABLE workspace_identity(singleton INTEGER PRIMARY KEY, workspace_id TEXT NOT NULL)")
            if identity is not None:
                conn.execute("INSERT INTO workspace_identity VALUES(1, ?)", (identity,))


def snapshot(path):
    return {p.name: p.read_bytes() for p in path.parent.glob(path.name + "*") if p.is_file()}


def test_mismatched_workspace_rejects_without_schema_pragma_or_file_mutation(tmp_path):
    path = tmp_path / "workspace.db"
    seed(path)
    before = snapshot(path)
    with pytest.raises(ValueError, match="workspace"):
        Database(path, workspace_id="team-b")
    assert snapshot(path) == before
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='broker_deals'").fetchone() is None


@pytest.mark.parametrize("identity", [None, "", "bad space"])
def test_missing_or_invalid_stored_identity_is_not_implicitly_claimed(tmp_path, identity):
    path = tmp_path / "invalid.db"
    seed(path, identity)
    before = snapshot(path)
    with pytest.raises(ValueError, match="workspace"):
        Database(path, workspace_id="team-a")
    assert snapshot(path) == before


def test_nonempty_legacy_database_requires_explicit_adoption_without_mutation(tmp_path):
    path = tmp_path / "legacy.db"
    seed(path, legacy=True)
    before = snapshot(path)
    with pytest.raises(ValueError, match="legacy"):
        Database(path, workspace_id="team-a")
    assert snapshot(path) == before


def test_explicit_legacy_adoption_preserves_rows_and_is_pinned(tmp_path):
    path = tmp_path / "legacy.db"
    seed(path, legacy=True)
    db = Database(path, workspace_id="team-a", adopt_legacy=True)
    assert db.query_one("SELECT value FROM retained")["value"] == "keep"
    db.close()
    with pytest.raises(ValueError, match="workspace"):
        Database(path, workspace_id="team-b", adopt_legacy=True)


def test_schema_failure_rolls_back_legacy_adoption(tmp_path, monkeypatch):
    from packages.persistence import db as module

    path = tmp_path / "legacy.db"
    seed(path, legacy=True)
    before = snapshot(path)
    monkeypatch.setattr(module, "SCHEMA", module.SCHEMA + "\nINVALID SQL;")
    with pytest.raises(sqlite3.Error):
        Database(path, workspace_id="team-a", adopt_legacy=True)
    assert snapshot(path) == before


def test_new_database_reopens_in_same_workspace(tmp_path):
    path = tmp_path / "new.db"
    first = Database(path, workspace_id="team-a")
    first.kv_set("retained", 42)
    first.close()
    second = Database(path, workspace_id="team-a")
    assert second.kv_get("retained") == 42
    second.close()


def test_adoption_flag_is_explicit_boolean_not_truthy_string(tmp_path):
    path = tmp_path / "legacy.db"
    seed(path, legacy=True)
    before = snapshot(path)
    with pytest.raises(ValueError, match="adopt_legacy"):
        Database(path, workspace_id="team-a", adopt_legacy="false")
    assert snapshot(path) == before


def test_missing_identity_table_with_extra_rows_is_not_repaired(tmp_path):
    path = tmp_path / "extra.db"
    seed(path)
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO workspace_identity VALUES(2, 'team-b')")
    before = snapshot(path)
    with pytest.raises(ValueError, match="workspace"):
        Database(path, workspace_id="team-a", adopt_legacy=True)
    assert snapshot(path) == before


def test_new_concurrent_openers_cannot_choose_different_workspaces(tmp_path):
    path = tmp_path / "new.db"
    barrier = Barrier(2)

    def open_db(workspace):
        barrier.wait(timeout=5)
        try:
            db = Database(path, workspace_id=workspace)
        except ValueError:
            return "rejected"
        db.close()
        return workspace

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(open_db, ["team-a", "team-b"]))
    assert results.count("rejected") == 1


def test_competing_adopters_cannot_relabel_legacy_database(tmp_path):
    path = tmp_path / "legacy.db"
    seed(path, legacy=True)
    barrier = Barrier(2)

    def open_db(workspace):
        barrier.wait(timeout=5)
        try:
            db = Database(path, workspace_id=workspace, adopt_legacy=True)
        except ValueError:
            return "rejected"
        db.close()
        return workspace

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(open_db, ["team-a", "team-b"]))
    assert results.count("rejected") == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT workspace_id FROM workspace_identity").fetchone()[0] in results
        assert conn.execute("SELECT value FROM retained").fetchone()[0] == "keep"