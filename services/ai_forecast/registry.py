"""Model registry: versioned artifacts on disk + metadata in SQLite."""
from __future__ import annotations

import json
import time
from services.ai_forecast.approval import APPROVAL_RULE_VERSION
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from packages.persistence.db import Database
from packages.shared_schemas.models import ModelInfo
from services.ai_forecast.trainer import TrainingResult


class ModelRegistry:
    def __init__(self, model_dir: Path, db: Database) -> None:
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.db = db

    def save(self, result: TrainingResult, symbol: str, activate: bool = True) -> Path:
        target = self.model_dir / result.version
        target.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": result.version,
            "symbol": symbol,
            "models": result.models,
            "feature_columns": result.feature_columns,
            "trained_at": result.trained_at,
            "metrics": result.metrics,
            "approved": result.approved,
            "notes": result.notes,
            "deadband_atr": result.metrics.get("deadband_atr", 0.25),
        }
        joblib.dump(payload, target / "models.joblib", compress=3)
        np.savez_compressed(target / "pathprob.npz", **result.path_table.arrays())
        (target / "metadata.json").write_text(json.dumps({
            "version": result.version,
            "symbol": symbol,
            "trained_at": result.trained_at,
            "metrics": result.metrics,
            "approved": result.approved,
            "notes": result.notes,
            "features": result.feature_columns,
        }, indent=2, default=str), encoding="utf-8")
        self.db.execute(
            "INSERT OR REPLACE INTO models(version, created_at, method, path, metrics, approved, samples, notes) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (result.version, result.trained_at, "lightgbm-multiclass+isotonic+quantile",
             str(target / "models.joblib"), json.dumps(result.metrics, default=str),
             int(result.approved and activate), result.samples, f"{symbol}: {result.notes}"),
        )
        return target

    def load(self, version: str) -> tuple[dict[str, Any], dict[str, np.ndarray]] | None:
        path = self.model_dir / version / "models.joblib"
        if not path.exists():
            return None
        payload = joblib.load(path)
        npz_path = self.model_dir / version / "pathprob.npz"
        arrays: dict[str, np.ndarray] = {}
        if npz_path.exists():
            with np.load(npz_path) as data:
                arrays = {k: data[k] for k in data.files}
        return payload, arrays

    def latest(self) -> str | None:
        """Newest model on disk, approved or not.

        The predictor loads this so the numbers on screen belong to the most recent
        training run. Loading only the newest *approved* model went wrong twice: after
        a tighter approval rule it kept serving a stale model's metrics, and after a
        fresh (rejected) run it still showed the previous one's.
        """
        row = self.db.query_one("SELECT version FROM models ORDER BY created_at DESC LIMIT 1")
        return row["version"] if row else None

    def latest_approved(self) -> str | None:
        row = self.db.query_one(
            "SELECT version FROM models WHERE approved = 1 ORDER BY created_at DESC LIMIT 1")
        return row["version"] if row else None

    def list(self) -> list[ModelInfo]:
        rows = self.db.query("SELECT * FROM models ORDER BY created_at DESC LIMIT 20")
        out: list[ModelInfo] = []
        for row in rows:
            try:
                metrics = json.loads(row["metrics"] or "{}")
            except json.JSONDecodeError:
                metrics = {}
            out.append(ModelInfo(
                version=row["version"],
                created_at=int(row["created_at"] or 0),
                method=row["method"] or "",
                # demote approvals granted under an older rule, same as the predictor
                approved=bool(row["approved"]) and int(metrics.get("approval_rule") or 0)
                >= APPROVAL_RULE_VERSION,
                horizons=[int(h) for h in metrics.get("horizons", {}).keys()],
                metrics=metrics,
                samples=int(row["samples"] or 0),
                notes=row["notes"] or "",
            ))
        return out

    def approve(self, version: str, approved: bool = True) -> bool:
        self.db.execute("UPDATE models SET approved = ? WHERE version = ?", (int(approved), version))
        self.db.audit("system", "model.approve" if approved else "model.revoke", {"version": version})
        return True

    def new_version(self, prefix: str = "no7") -> str:
        return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}"
