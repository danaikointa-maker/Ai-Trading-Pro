from __future__ import annotations

from packages.persistence.db import Database


def _evidence(digest: str, received: int) -> dict:
    return {
        "source": "tradingview_ai_agent_lens", "source_schema": "ai-agent-lens/v1",
        "event": "BAR_CLOSE", "source_symbol": "OANDA:XAUUSD", "mapped_symbol": "XAUUSD",
        "timeframe": "5", "bar_close_utc": received, "received_at_utc": received,
        "payload_sha256": digest, "regime": "RANGE", "long_score": 20,
        "short_score": 25, "score_threshold": 70, "features": {},
        "quality": "unverified", "executable": False,
    }


def test_evidence_deduplicates_survives_reopen_and_prunes_old_rows(tmp_path):
    path = tmp_path / "tradingview.sqlite3"
    db = Database(path, workspace_id="tradingview-tests")
    first = _evidence("a" * 64, 1000)
    assert db.store_tradingview_evidence(first, max_age_seconds=10000, max_rows=10) is True
    assert db.store_tradingview_evidence(first, max_age_seconds=10000, max_rows=10) is False
    db.close()

    db = Database(path, workspace_id="tradingview-tests")
    assert len(db.query("SELECT * FROM tradingview_evidence")) == 1
    second = _evidence("b" * 64, 1200)
    assert db.store_tradingview_evidence(second, max_age_seconds=100, max_rows=10) is True
    rows = db.query("SELECT payload_sha256 FROM tradingview_evidence ORDER BY received_at_utc")
    assert [row["payload_sha256"] for row in rows] == ["b" * 64]
    db.close()


def test_evidence_retention_has_hard_row_bound(tmp_path):
    db = Database(tmp_path / "tradingview.sqlite3", workspace_id="tradingview-tests")
    for index, digest in enumerate(("c" * 64, "d" * 64, "e" * 64), start=1):
        assert db.store_tradingview_evidence(_evidence(digest, 1000 + index),
                                             max_age_seconds=10000, max_rows=2)
    rows = db.query("SELECT payload_sha256 FROM tradingview_evidence ORDER BY received_at_utc")
    assert [row["payload_sha256"] for row in rows] == ["d" * 64, "e" * 64]
    db.close()
