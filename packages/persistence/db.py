"""SQLite persistence for No7 AI Trading Pro.

SQLite keeps the local-first promise (one file under ``storage/db``), needs no
server on a Windows box, and is easily swapped for PostgreSQL/TimescaleDB by
replacing this class. All writes are serialised through a lock because the
FastAPI event loop, the strategy thread and the simulator thread share it.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL, tf TEXT NOT NULL, t INTEGER NOT NULL,
    o REAL, h REAL, l REAL, c REAL, v REAL,
    PRIMARY KEY (symbol, tf, t)
);
CREATE INDEX IF NOT EXISTS idx_candles ON candles(symbol, tf, t DESC);

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY, t INTEGER, symbol TEXT, action TEXT, score REAL,
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_t ON signals(t DESC);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, created_at REAL, idempotency_key TEXT UNIQUE,
    state TEXT, broker_id TEXT, symbol TEXT, payload TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    ticket TEXT PRIMARY KEY, opened_at INTEGER, closed_at INTEGER,
    symbol TEXT, direction TEXT, volume REAL, entry REAL, exit REAL,
    pnl REAL, points REAL, exit_reason TEXT, strategy TEXT, mode TEXT,
    broker_id TEXT, payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_closed ON trades(closed_at DESC);

CREATE TABLE IF NOT EXISTS open_positions (
    ticket TEXT PRIMARY KEY, payload TEXT, updated_at REAL
);

CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY, t INTEGER, level TEXT, title TEXT, message TEXT,
    channel TEXT, payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_t ON alerts(t DESC);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, t REAL, actor TEXT, action TEXT,
    detail TEXT, ip TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY, value TEXT, updated_at REAL
);

CREATE TABLE IF NOT EXISTS models (
    version TEXT PRIMARY KEY, created_at INTEGER, method TEXT, path TEXT,
    metrics TEXT, approved INTEGER DEFAULT 0, samples INTEGER, notes TEXT
);

CREATE TABLE IF NOT EXISTS equity (
    t REAL PRIMARY KEY, balance REAL, equity REAL, note TEXT
);

CREATE TABLE IF NOT EXISTS news (
    id TEXT PRIMARY KEY, t INTEGER, currency TEXT, impact TEXT, title TEXT
);

CREATE TABLE IF NOT EXISTS backtests (
    id TEXT PRIMARY KEY, created_at INTEGER, symbol TEXT, strategy TEXT,
    payload TEXT
);

CREATE TABLE IF NOT EXISTS journal (
    ticket TEXT PRIMARY KEY, created_at INTEGER, payload TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, password_hash TEXT,
    role TEXT DEFAULT 'trader', created_at REAL
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT, updated_at REAL
);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=15.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=8000")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ------------------------------------------------------------------ core
    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        with self.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    def executemany(self, sql: str, rows: list[tuple]) -> int:
        with self.cursor() as cur:
            cur.executemany(sql, rows)
            return cur.rowcount

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------- kv
    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value FROM kv WHERE key = ?", (key,))
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value, default=str), time.time()),
        )

    # --------------------------------------------------------------- audit
    def audit(self, actor: str, action: str, detail: Any = None, ip: str = "") -> None:
        self.execute(
            "INSERT INTO audit(t, actor, action, detail, ip) VALUES(?,?,?,?,?)",
            (time.time(), actor, action, json.dumps(detail, default=str)[:8000] if detail is not None else "", ip),
        )

    # -------------------------------------------------------------- equity
    def record_equity(self, t: float, balance: float, equity: float, note: str = "") -> None:
        self.execute(
            "INSERT OR REPLACE INTO equity(t, balance, equity, note) VALUES(?,?,?,?)",
            (t, balance, equity, note),
        )
