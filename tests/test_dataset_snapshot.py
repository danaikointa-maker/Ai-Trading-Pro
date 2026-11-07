"""Dataset snapshots: a backtest must be repeatable, or its numbers mean nothing.

The simulator advances with the wall clock and MT5 history gets revised, so
"run it again" used to produce different bars and different numbers from the same
settings. Snapshots pin the bars; the id is the content hash, and a snapshot that
no longer matches its hash is refused rather than silently re-run.
"""
from __future__ import annotations

import gzip
import json

import pandas as pd
import pytest

from services.market_data.snapshots import (SnapshotError, bar_data_note, canonical_bytes,
                                           describe_source, fingerprint, list_snapshots,
                                           load_snapshot, save_snapshot)


def bars(n: int = 300, start: int = 1_600_000_000, step: int = 60) -> pd.DataFrame:
    rows = []
    price = 2000.0
    for i in range(n):
        price += 0.5 if i % 3 else -0.4
        rows.append({"t": start + i * step, "o": price, "h": price + 1.2,
                     "l": price - 1.1, "c": price + 0.3, "v": 100 + i})
    return pd.DataFrame(rows)


def test_fingerprint_is_stable_and_order_independent(tmp_path):
    frame = bars()
    shuffled = frame.sample(frac=1.0, random_state=3).reset_index(drop=True)
    assert fingerprint(frame) == fingerprint(shuffled), "row order must not change the hash"

    changed = frame.copy()
    changed.loc[10, "c"] = changed.loc[10, "c"] + 0.0001
    assert fingerprint(changed) != fingerprint(frame)


def test_canonical_form_round_trips_through_csv():
    frame = bars(50)
    again = pd.read_csv(pd.io.common.BytesIO(canonical_bytes(frame)))
    assert fingerprint(again) == fingerprint(frame)


def test_save_and_load_return_the_same_bars(tmp_path):
    frame = bars()
    snapshot = save_snapshot(tmp_path, "XAUUSD", "M1", frame, describe_source("simulate", 7))
    assert snapshot.id.startswith("DS-")
    assert snapshot.rows == len(frame)
    assert snapshot.first_t == int(frame["t"].iloc[0])
    assert snapshot.last_t == int(frame["t"].iloc[-1])

    manifest, loaded = load_snapshot(tmp_path, snapshot.id)
    assert manifest.sha256 == snapshot.sha256
    assert fingerprint(loaded) == snapshot.sha256
    assert loaded["c"].tolist() == pytest.approx(frame["c"].tolist())


def test_saving_the_same_bars_twice_reuses_the_snapshot(tmp_path):
    frame = bars()
    first = save_snapshot(tmp_path, "XAUUSD", "M1", frame, "simulated")
    second = save_snapshot(tmp_path, "XAUUSD", "M1", frame, "simulated")
    assert first.id == second.id
    assert len(list_snapshots(tmp_path)) == 1


def test_a_tampered_snapshot_is_refused(tmp_path):
    frame = bars()
    snapshot = save_snapshot(tmp_path, "XAUUSD", "M1", frame, "simulated")

    edited = frame.copy()
    edited.loc[0, "h"] = 9999.0
    (tmp_path / "snapshots" / f"{snapshot.id}.csv.gz").write_bytes(
        gzip.compress(canonical_bytes(edited), mtime=0))

    with pytest.raises(SnapshotError, match="corrupted"):
        load_snapshot(tmp_path, snapshot.id)


def test_missing_snapshot_is_a_clear_error(tmp_path):
    with pytest.raises(SnapshotError, match="not found"):
        load_snapshot(tmp_path, "DS-DOESNOTEXIST")


def test_empty_or_duplicated_bars_are_rejected(tmp_path):
    with pytest.raises(SnapshotError, match="empty"):
        save_snapshot(tmp_path, "XAUUSD", "M1", pd.DataFrame(), "simulated")

    frame = bars(10)
    frame.loc[1, "t"] = frame.loc[0, "t"]
    with pytest.raises(SnapshotError, match="duplicate"):
        save_snapshot(tmp_path, "XAUUSD", "M1", frame, "simulated")


def test_source_description_and_assumption_match_the_data(tmp_path):
    sim = describe_source("simulate", 7)
    assert "simulated" in sim and "7" in sim
    assert "not market data" in bar_data_note(sim)

    replay = describe_source("replay")
    assert "replay" in replay and "imported" in replay
    note = bar_data_note(replay)
    assert "replay" in note.lower()
    assert "tick history" in note and "approximations" in note

    mt5 = describe_source("mt5", adapter_id="connext-demo")
    assert "MT5" in mt5 and "connext-demo" in mt5


def test_snapshot_listing_is_newest_first(tmp_path):
    one = save_snapshot(tmp_path, "XAUUSD", "M1", bars(120), "simulated")
    two = save_snapshot(tmp_path, "XAUUSD", "M1", bars(140, start=1_700_000_000), "simulated")
    listed = list_snapshots(tmp_path)
    assert {one.id, two.id} == {item["id"] for item in listed}
    assert json.dumps(listed)  # serialisable manifests


def test_backtest_report_carries_the_snapshot_and_its_bar_note(client, token):
    """End to end: POST a backtest, then reproduce it from the recorded snapshot."""
    import time as _time

    headers = {"Authorization": f"Bearer {token}"}
    started = client.post("/api/backtests", json={"symbol": "XAUUSD", "bars": 2500},
                          headers=headers)
    assert started.status_code == 200
    job_id = started.json()["job_id"]
    for _ in range(120):
        job = client.get(f"/api/backtests/jobs/{job_id}", headers=headers).json()
        if job["state"] in ("done", "error"):
            break
        _time.sleep(0.25)
    assert job["state"] == "done", job

    report = client.get(f"/api/backtests/{job['report_id']}", headers=headers).json()
    dataset = report["dataset"]
    assert dataset["id"].startswith("DS-")
    assert dataset["sha256"] and dataset["rows"] >= 1000
    assert dataset["reproducible"] is True
    assert dataset["reproduce_with"]["snapshot_id"] == dataset["id"]
    assert any("Bar data:" in line for line in report["assumptions"])

    # the same snapshot is accepted and replays the same bar count
    again = client.post("/api/backtests",
                        json={"symbol": "XAUUSD", "snapshot_id": dataset["id"]},
                        headers=headers)
    assert again.status_code == 200
    job2 = again.json()["job_id"]
    for _ in range(120):
        j2 = client.get(f"/api/backtests/jobs/{job2}", headers=headers).json()
        if j2["state"] in ("done", "error"):
            break
        _time.sleep(0.25)
    assert j2["state"] == "done", j2
    report2 = client.get(f"/api/backtests/{j2['report_id']}", headers=headers).json()
    assert report2["dataset"]["sha256"] == dataset["sha256"]
    assert report2["bars"] == report["bars"]
    assert report2["metrics"] == report["metrics"], "same bars must reproduce the same numbers"


def test_unknown_snapshot_id_fails_fast(client, token):
    res = client.post("/api/backtests", json={"symbol": "XAUUSD", "snapshot_id": "DS-NOPE"},
                      headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 400
    assert "not found" in res.json()["detail"]


def test_datasets_api_lists_and_pins(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    pinned = client.post("/api/datasets", json={"symbol": "XAUUSD", "bars": 1200}, headers=headers)
    assert pinned.status_code == 200
    manifest = pinned.json()
    assert manifest["id"].startswith("DS-")

    listed = client.get("/api/datasets", headers=headers).json()["snapshots"]
    assert any(item["id"] == manifest["id"] for item in listed)

    detail = client.get(f"/api/datasets/{manifest['id']}", headers=headers).json()
    assert detail["verified"] is True
    assert len(detail["sample"]) == 3

    missing = client.get("/api/datasets/DS-NOPE", headers=headers)
    assert missing.status_code == 404


def test_too_few_bars_is_a_clear_message_not_a_traceback(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post("/api/backtests", json={"symbol": "XAUUSD", "bars": 900}, headers=headers)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "900" in detail and "at least" in detail and "snapshot_id" in detail
