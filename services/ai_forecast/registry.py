"""Model registry: versioned artifacts on disk + metadata in SQLite."""
from __future__ import annotations

import hashlib
import io
import json
import re
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
        if any(part.is_symlink() for part in (self.model_dir, *self.model_dir.parents)):
            raise ValueError("artifact root path is linked")
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self._model_root = self.model_dir.resolve()
        self.db = db

    def _artifact_paths(self, version: str) -> tuple[Path, Path]:
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", version):
            raise ValueError("invalid artifact version")
        root = self.model_dir.resolve()
        if self.model_dir.is_symlink() or root != self._model_root:
            raise ValueError("artifact root changed")
        target = self.model_dir / version
        paths = (target / "models.joblib", target / "pathprob.npz")
        # Validate both artifacts before deserializing either. Existing junctions
        # and symlinks must not redirect even a syntactically valid version.
        for path in (target, *paths, target / "metadata.json"):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("artifact path outside model root")
        return paths

    def save(self, result: TrainingResult, symbol: str, activate: bool = True) -> Path:
        model_path, npz_path = self._artifact_paths(result.version)
        target = model_path.parent
        # Exclusive directory creation: never overwrite or adopt a legacy version.
        try:
            target.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise ValueError("artifact version exists; immutable versions cannot be adopted") from None
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
        joblib.dump(payload, model_path, compress=3)
        np.savez_compressed(npz_path, **result.path_table.arrays())
        (target / "metadata.json").write_text(json.dumps({
            "version": result.version,
            "symbol": symbol,
            "trained_at": result.trained_at,
            "metrics": result.metrics,
            "approved": result.approved,
            "notes": result.notes,
            "features": result.feature_columns,
        }, indent=2, default=str), encoding="utf-8")
        provenance = {"schema": 1, "workspace_id": self.db.workspace_id, "version": result.version,
                      "symbol": symbol, "root": str(self.model_dir.resolve()),
                      "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (model_path, npz_path, target / "metadata.json")}}
        # Register metadata and hashes together only after every artifact is written.
        # A failed save leaves unregistered bytes, which load() refuses to adopt.
        with self.db.cursor() as cur:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute(
                "INSERT INTO models(version, created_at, method, path, metrics, approved, samples, notes) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (result.version, result.trained_at, "lightgbm-multiclass+isotonic+quantile",
                 str(model_path), json.dumps(result.metrics, default=str),
                 int(result.approved and activate), result.samples, f"{symbol}: {result.notes}"),
            )
            cur.execute("INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)",
                        (f"model.provenance:{result.version}", json.dumps(provenance), time.time()))
        return target

    def _verified_blobs(self, version: str) -> dict[str, bytes] | None:
        """Check registration and bytes without invoking executable deserializers."""
        # Existence, not decoded truthiness: even a corrupt latch fails closed.
        if self.db.query_one("SELECT key FROM kv WHERE key=?", (f"model.quarantine:{version}",)):
            return None
        try:
            blobs = self._read_registered_blobs(version)
        except (ValueError, OSError):
            self._quarantine(version)
            raise
        if blobs is None:
            self._quarantine(version)
        return blobs

    def _quarantine(self, version: str) -> None:
        # Only registered rows create durable records. No paths, raw exceptions,
        # artifact moves, approval rewrites or automatic release on byte repair.
        if not self.db.query_one("SELECT version FROM models WHERE version=?", (version,)):
            return
        record = {"schema": 1, "workspace_id": self.db.workspace_id,
                  "version": version, "state": "quarantined",
                  "reason": "artifact_verification_failed", "detected_at": time.time()}
        self.db.execute("INSERT OR IGNORE INTO kv(key,value,updated_at) VALUES(?,?,?)",
                        (f"model.quarantine:{version}", json.dumps(record), time.time()))

    def _read_registered_blobs(self, version: str) -> dict[str, bytes] | None:
        path, npz_path = self._artifact_paths(version)
        evidence = self.db.kv_get(f"model.provenance:{version}")
        row = self.db.query_one("SELECT path FROM models WHERE version=?", (version,))
        if (not isinstance(evidence, dict) or evidence.get("schema") != 1
                or evidence.get("workspace_id") != self.db.workspace_id or evidence.get("version") != version
                or evidence.get("root") != str(self.model_dir.resolve())
                or not isinstance(evidence.get("files"), dict)
                or not row or row["path"] != str(path)):
            return None
        # Hash and deserialize the same in-memory bytes. No second open of an
        # artifact path after validation, including the NPZ companion.
        blobs: dict[str, bytes] = {}
        try:
            for artifact in (path, npz_path, path.parent / "metadata.json"):
                blob = artifact.read_bytes()
                if hashlib.sha256(blob).hexdigest() != evidence.get("files", {}).get(artifact.name):
                    return None
                blobs[artifact.name] = blob
        except OSError:
            return None
        return blobs

    def load(self, version: str) -> tuple[dict[str, Any], dict[str, np.ndarray]] | None:
        blobs = self._verified_blobs(version)
        if blobs is None:
            return None
        try:
            payload = joblib.load(io.BytesIO(blobs["models.joblib"]))
            arrays: dict[str, np.ndarray] = {}
            with np.load(io.BytesIO(blobs["pathprob.npz"]), allow_pickle=False) as data:
                arrays = {k: data[k] for k in data.files}
            self._validate_payload(version, payload, arrays)
        except Exception:
            # Verified hashes do not guarantee a decodable model. Preserve a
            # durable refusal without exposing decoder details or retrying it.
            self._quarantine(version)
            return None
        # A database revocation must survive reload. Conversely a research DB
        # approval cannot promote a payload rejected by the training gate.
        row = self.db.query_one("SELECT approved FROM models WHERE version=?", (version,))
        payload = dict(payload)
        payload["approved"] = bool(payload.get("approved")) and bool(row and row["approved"])
        return payload, arrays

    def _validate_payload(self, version: str, payload: Any, arrays: dict[str, np.ndarray]) -> None:
        """Reject decoded structures before they can partially install model state.

        This is a schema check, not a sandbox for executable joblib objects.
        Unknown NPZ keys remain available for compatible research metadata.
        """
        evidence = self.db.kv_get(f"model.provenance:{version}")
        if (not isinstance(payload, dict) or payload.get("version") != version
                or payload.get("symbol") != evidence.get("symbol")
                or type(payload.get("approved")) is not bool
                or not isinstance(payload.get("models"), dict)
                or not isinstance(payload.get("metrics"), dict)
                or type(payload.get("trained_at")) is not int or payload["trained_at"] < 0):
            raise ValueError("invalid model payload")
        rule = payload["metrics"].get("approval_rule", 0)
        if type(rule) is not int or rule < 0:
            raise ValueError("invalid approval rule")
        horizons: set[int] = set()
        for key, model in payload["models"].items():
            if type(key) not in (int, str) or not re.fullmatch(r"[1-9][0-9]*", str(key)):
                raise ValueError("invalid horizon")
            horizon = int(key)
            if (horizon in horizons or type(getattr(model, "approved", None)) is not bool
                    or not isinstance(getattr(model, "metrics", None), dict)
                    or not callable(getattr(model, "predict_proba", None))
                    or not callable(getattr(model, "predict_quantiles", None))):
                raise ValueError("invalid horizon model")
            horizons.add(horizon)
        for key, high in arrays.items():
            if not key.startswith(("high_", "low_")):
                continue
            match = re.fullmatch(r"(high|low)_([1-9][0-9]*)", key)
            if not match:
                raise ValueError("invalid path horizon")
            horizon = int(match[2])
            low = arrays.get(f"low_{horizon}")
            high = arrays.get(f"high_{horizon}")
            if (not isinstance(high, np.ndarray) or not isinstance(low, np.ndarray)
                    or high.ndim != 2 or low.shape != high.shape
                    or high.shape[1] != horizon or high.shape[0] == 0
                    or high.dtype.kind not in "fiu" or low.dtype.kind not in "fiu"
                    or not np.isfinite(high).all() or not np.isfinite(low).all()):
                raise ValueError("invalid path arrays")

    def inference_allowed(self, version: str) -> bool:
        """Recheck persisted authority and artifacts without executing a decoder."""
        row = self.db.query_one("SELECT approved FROM models WHERE version=?", (version,))
        if row is None or row["approved"] != 1:
            return False
        return self._verified_blobs(version) is not None

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
                verified = self._verified_blobs(row["version"]) is not None
            except (ValueError, OSError):
                verified = False
            try:
                metrics = json.loads(row["metrics"] or "{}")
            except json.JSONDecodeError:
                metrics = {}
            out.append(ModelInfo(
                version=row["version"],
                created_at=int(row["created_at"] or 0),
                method=row["method"] or "",
                # demote approvals granted under an older rule, same as the predictor
                approved=verified and bool(row["approved"]) and int(metrics.get("approval_rule") or 0)
                >= APPROVAL_RULE_VERSION,
                horizons=[int(h) for h in metrics.get("horizons", {}).keys()],
                metrics=metrics,
                samples=int(row["samples"] or 0),
                notes=row["notes"] or "",
                artifact_status="verified" if verified else "quarantined",
                artifact_reason="" if verified else "artifact_verification_failed",
            ))
        return out

    def approve(self, version: str, approved: bool = True) -> bool:
        if not self.db.query_one("SELECT version FROM models WHERE version=?", (version,)):
            return False
        if approved:
            try:
                if self._verified_blobs(version) is None:
                    return False
            except (ValueError, OSError):
                return False
        self.db.execute("UPDATE models SET approved = ? WHERE version = ?", (int(approved), version))
        self.db.audit("system", "model.approve" if approved else "model.revoke", {"version": version})
        return True

    def new_version(self, prefix: str = "no7") -> str:
        return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}"
