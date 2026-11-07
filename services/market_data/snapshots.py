"""Dataset snapshots: pin the exact bars a backtest ran on.

A backtest number is meaningless without the data behind it. The simulator moves
with the seed *and* the wall clock, MT5 history is revised, and an imported CSV can
be replaced. So every backtest writes its bars to a snapshot and records the id +
sha256 in the report; re-running with that id replays the same bars, not "whatever
the feed produces today".

(This is separate from ``dataset.py``, which imports a broker CSV into the platform.
Snapshots are the frozen bars a run is judged on.)

Snapshots are content-addressed: the id derives from the sha256 of the bars, so the
same data always yields the same id and saving twice is a no-op.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

COLUMNS = ["t", "o", "h", "l", "c", "v"]
SNAPSHOT_SUBDIR = "snapshots"


class SnapshotError(RuntimeError):
    """A snapshot is missing, unreadable, or no longer matches its hash."""


@dataclass
class Snapshot:
    id: str
    symbol: str
    timeframe: str
    rows: int
    first_t: int
    last_t: int
    sha256: str
    source: str
    created_at: int
    bytes: int
    path: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def describe_source(feed_mode: str, seed: int | None = None,
                    adapter_id: str | None = None) -> str:
    """One honest sentence about where the bars came from.

    This string ends up in the report's assumptions: a backtest on imported candles
    must not describe itself as simulated, and vice versa.
    """
    mode = (feed_mode or "").lower()
    if mode in ("simulate", "simulated"):
        return (f"simulated GBM feed (seed {seed})" if seed is not None
                else "simulated GBM feed")
    if mode == "replay":
        return "imported candles replayed from the dataset directory"
    if mode == "mt5":
        return f"MT5 terminal history from {adapter_id or 'the configured terminal'}"
    return f"feed '{feed_mode}'"


def bar_data_note(source: str) -> str:
    """The assumption line that tells the operator what the bars are."""
    low = source.lower()
    if "simulat" in low:
        return (f"Bar data: {source} — not market data. Use these numbers to compare rules "
                f"against each other, never as evidence about a real market.")
    if "replay" in low:
        return (f"Bar data: {source} — real bars, but no intra-bar path and no tick history, "
                f"so fills and the stop/target order inside a bar remain approximations.")
    if "mt5" in low:
        return (f"Bar data: {source} — broker history, still M1 resolution; intra-bar ordering "
                f"is approximated.")
    return f"Bar data: {source}."


def canonical_bytes(frame: pd.DataFrame) -> bytes:
    """Deterministic byte form of the bars — the input to the sha256."""
    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        raise SnapshotError(f"bars are missing columns: {missing}")
    ordered = frame[COLUMNS].sort_values("t").reset_index(drop=True)
    if ordered["t"].duplicated().any():
        raise SnapshotError("bars contain duplicate timestamps")
    return ordered.to_csv(index=False, float_format="%.5f",
                          lineterminator="\n").encode("utf-8")


def fingerprint(frame: pd.DataFrame) -> str:
    return hashlib.sha256(canonical_bytes(frame)).hexdigest()


def snapshot_dir(datasets_dir: Path | str) -> Path:
    path = Path(datasets_dir) / SNAPSHOT_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path(datasets_dir: Path | str, snapshot_id: str) -> Path:
    return snapshot_dir(datasets_dir) / f"{snapshot_id}.json"


def save_snapshot(datasets_dir: Path | str, symbol: str, timeframe: str,
                  frame: pd.DataFrame, source: str) -> Snapshot:
    """Write (or reuse) a snapshot; the id is derived from the content."""
    if frame is None or len(frame) == 0:
        raise SnapshotError("cannot snapshot an empty bar set")
    sha = fingerprint(frame)
    snapshot_id = f"DS-{sha[:10].upper()}"
    manifest_file = _manifest_path(datasets_dir, snapshot_id)
    data_file = snapshot_dir(datasets_dir) / f"{snapshot_id}.csv.gz"

    ordered = frame[COLUMNS].sort_values("t").reset_index(drop=True)
    if manifest_file.exists() and data_file.exists():
        manifest = json.loads(manifest_file.read_text("utf-8"))
        if manifest.get("sha256") == sha:
            return Snapshot(**manifest)

    raw = canonical_bytes(ordered)
    data_file.write_bytes(gzip.compress(raw, mtime=0))
    snapshot = Snapshot(
        id=snapshot_id,
        symbol=symbol,
        timeframe=timeframe,
        rows=int(len(ordered)),
        first_t=int(ordered["t"].iloc[0]),
        last_t=int(ordered["t"].iloc[-1]),
        sha256=sha,
        source=source,
        created_at=int(time.time()),
        bytes=len(raw),
        path=str(data_file),
    )
    manifest_file.write_text(json.dumps(snapshot.as_dict(), indent=2), "utf-8")
    return snapshot


def load_snapshot(datasets_dir: Path | str, snapshot_id: str) -> tuple[Snapshot, pd.DataFrame]:
    """Load a snapshot and verify it still hashes to its recorded digest.

    A mismatch means the file was edited or replaced; refusing is the only honest
    answer, because a "reproduction" on different data is not a reproduction.
    """
    if not snapshot_id or "/" in snapshot_id or "\\" in snapshot_id or ".." in snapshot_id:
        raise SnapshotError(f"invalid snapshot id: {snapshot_id!r}")
    manifest_file = _manifest_path(datasets_dir, snapshot_id)
    if not manifest_file.exists():
        raise SnapshotError(f"snapshot {snapshot_id} not found in {snapshot_dir(datasets_dir)}")
    manifest = json.loads(manifest_file.read_text("utf-8"))
    data_file = Path(manifest["path"])
    if not data_file.exists():
        raise SnapshotError(
            f"snapshot {snapshot_id} manifest points at a missing file: {data_file}")
    frame = pd.read_csv(data_file)
    actual = fingerprint(frame)
    if actual != manifest["sha256"]:
        raise SnapshotError(
            f"snapshot {snapshot_id} is corrupted: sha256 {actual[:12]}… != recorded "
            f"{str(manifest['sha256'])[:12]}… — refusing to backtest on changed data")
    return Snapshot(**manifest), frame


def list_snapshots(datasets_dir: Path | str, limit: int = 50) -> list[dict[str, Any]]:
    files = sorted(snapshot_dir(datasets_dir).glob("DS-*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            out.append(json.loads(path.read_text("utf-8")))
        except json.JSONDecodeError:
            continue
    return out
