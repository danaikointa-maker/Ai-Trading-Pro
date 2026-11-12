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
import io
import json
import re
import time
import zlib
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
    schema: int = 1
    dataset_root: str = ""

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
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise SnapshotError("snapshot artifact root path is linked")
    return path.resolve()


def _manifest_path(datasets_dir: Path | str, snapshot_id: str) -> Path:
    if not isinstance(snapshot_id, str) or not re.fullmatch(r"DS-[A-Z0-9_-]{1,64}", snapshot_id):
        raise SnapshotError("invalid snapshot id")
    folder = snapshot_dir(datasets_dir)
    for path in (folder / f"{snapshot_id}.json", folder / f"{snapshot_id}.csv.gz"):
        if path.is_symlink() or not path.resolve().is_relative_to(folder):
            raise SnapshotError("snapshot artifact path outside root")
    return folder / f"{snapshot_id}.json"


def _read_manifest(datasets_dir: Path | str, snapshot_id: str) -> Snapshot:
    manifest_file = _manifest_path(datasets_dir, snapshot_id)
    if not manifest_file.exists():
        raise SnapshotError(f"snapshot {snapshot_id} not found")
    try:
        manifest = json.loads(manifest_file.read_text("utf-8"))
        expected = manifest_file.with_suffix(".csv.gz")
        if (not isinstance(manifest, dict) or manifest.get("schema") != 1
                or manifest.get("dataset_root") != str(snapshot_dir(datasets_dir).parent)
                or manifest.get("id") != snapshot_id or manifest.get("path") != str(expected)
                or not isinstance(manifest.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"])
                or snapshot_id != f"DS-{manifest['sha256'][:10].upper()}"):
            raise ValueError("invalid identity")
        snapshot = Snapshot(**manifest)
        if (any(type(manifest[k]) is not int for k in ("rows", "first_t", "last_t", "bytes", "created_at"))
                or snapshot.rows <= 0 or snapshot.bytes <= 0
                or not all(isinstance(manifest[k], str) for k in ("symbol", "timeframe", "source"))):
            raise ValueError("invalid shape")
        return snapshot
    except (OSError, ValueError, TypeError, KeyError):
        raise SnapshotError("snapshot manifest provenance invalid; artifact quarantined") from None


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
    if manifest_file.exists() or data_file.exists():
        existing, _ = load_snapshot(datasets_dir, snapshot_id)
        if (existing.sha256 != sha or existing.symbol != symbol or existing.timeframe != timeframe
                or existing.source != source):
            raise SnapshotError("snapshot identity conflict; refusing reuse")
        return existing

    raw = canonical_bytes(ordered)
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
        dataset_root=str(snapshot_dir(datasets_dir).parent),
    )
    try:
        data_file.parent.mkdir(parents=True, exist_ok=True)
        with data_file.open("xb") as output:
            output.write(gzip.compress(raw, mtime=0))
        with manifest_file.open("x", encoding="utf-8") as output:
            output.write(json.dumps(snapshot.as_dict(), indent=2))
    except OSError:
        raise SnapshotError("snapshot artifact write failed; incomplete artifacts quarantined") from None
    return snapshot


def load_snapshot(datasets_dir: Path | str, snapshot_id: str) -> tuple[Snapshot, pd.DataFrame]:
    """Load a snapshot and verify it still hashes to its recorded digest.

    A mismatch means the file was edited or replaced; refusing is the only honest
    answer, because a "reproduction" on different data is not a reproduction.
    """
    snapshot = _read_manifest(datasets_dir, snapshot_id)
    data_file = _manifest_path(datasets_dir, snapshot_id).with_suffix(".csv.gz")
    try:
        raw = gzip.decompress(data_file.read_bytes())
        if hashlib.sha256(raw).hexdigest() != snapshot.sha256 or len(raw) != snapshot.bytes:
            raise SnapshotError("snapshot is corrupted; refusing changed data")
        frame = pd.read_csv(io.BytesIO(raw))
        if (fingerprint(frame) != snapshot.sha256 or len(frame) != snapshot.rows
                or int(frame["t"].iloc[0]) != snapshot.first_t or int(frame["t"].iloc[-1]) != snapshot.last_t):
            raise SnapshotError("snapshot metadata does not match verified bars")
    except (OSError, ValueError, EOFError, KeyError, IndexError, zlib.error):
        raise SnapshotError("snapshot artifact corrupted or unreadable; quarantined") from None
    return snapshot, frame


def list_snapshots(datasets_dir: Path | str, limit: int = 50) -> list[dict[str, Any]]:
    files = sorted((p for p in snapshot_dir(datasets_dir).glob("DS-*.json") if not p.is_symlink()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            snapshot = _read_manifest(datasets_dir, path.stem)
            if not Path(snapshot.path).is_file():
                continue
            out.append(snapshot.as_dict())
        except SnapshotError:
            continue
    return out
