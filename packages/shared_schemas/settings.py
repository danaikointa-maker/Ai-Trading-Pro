"""Single source of truth for configuration.

Every path is resolved against ``NO7_ROOT`` (env) so the whole project can be
moved from ``C:\\`` to ``D:\\`` without editing source code. Config files live
in ``config/`` and support ``${ENV_VAR:default}`` interpolation.
"""
from __future__ import annotations

import copy
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _cast_scalar(text: str) -> Any:
    """Env vars arrive as strings; restore the YAML scalar type."""
    lowered = text.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", ""}:
        return None if lowered != "" else text
    try:
        if re.fullmatch(r"[+-]?\d+", text.strip()):
            return int(text)
        if re.fullmatch(r"[+-]?\d*\.\d+", text.strip()):
            return float(text)
    except (TypeError, ValueError):
        pass
    return text


def _interpolate(value: Any) -> Any:
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            return os.environ.get(match.group(1), match.group(2) or "")

        # A value that is exactly one placeholder keeps its natural type.
        whole = _ENV_PATTERN.fullmatch(value.strip())
        if whole:
            raw = os.environ.get(whole.group(1), whole.group(2) or "")
            return _cast_scalar(raw)
        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    return value


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Typed access to the YAML configs with env interpolation applied."""

    def __init__(self, config_dir: Path | None = None) -> None:
        _load_dotenv(REPO_ROOT / ".env")
        self.config_dir = Path(config_dir or CONFIG_DIR)
        self.root = Path(os.environ.get("NO7_ROOT", REPO_ROOT)).expanduser().resolve()
        if not self.root.is_absolute():
            self.root = (REPO_ROOT / self.root).resolve()
        self.app = self._read("app.yaml")
        workspace = self.security["workspace_id"]
        if not isinstance(workspace, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", workspace):
            raise ValueError("invalid workspace identity")
        self.brokers = self._read("brokers.yaml")
        if _as_bool(os.environ.get("NO7_LOCAL_SIMULATION", "false")):
            # Local development must never initialise terminal or bridge adapters.
            self.brokers["brokers"] = [
                p for p in self.brokers.get("brokers", [])
                if p.get("adapter", "simulated_mt5") in ("paper", "simulated_mt5")
            ]
            profiles = self.brokers["brokers"]
            if not profiles:
                raise ValueError("local simulation requires at least one paper broker")
            if self.brokers.get("default_broker") not in {p["id"] for p in profiles}:
                self.brokers["default_broker"] = profiles[0]["id"]
        self.risk = self._read("risk.yaml")
        self.strategies = self._read("strategies.yaml")
        self.paths = self._resolve_paths()
        for key in ("datasets", "models", "backtests", "logs"):
            self.paths[key].mkdir(parents=True, exist_ok=True)
        self.paths["database"].parent.mkdir(parents=True, exist_ok=True)
        self.env = os.environ.get("NO7_ENV", "development")

    # ------------------------------------------------------------------ io
    def _read(self, name: str) -> dict[str, Any]:
        path = self.config_dir / name
        if not path.exists():
            raise FileNotFoundError(f"missing config file: {path}")
        with path.open("r", encoding="utf-8") as fh:
            return _interpolate(copy.deepcopy(yaml.safe_load(fh) or {}))

    def _resolve_paths(self) -> dict[str, Path]:
        raw = self.app.get("paths", {})
        out: dict[str, Path] = {}
        for key, value in raw.items():
            candidate = Path(str(value)).expanduser()
            out[key] = candidate if candidate.is_absolute() else (self.root / candidate)
        out.setdefault("database", self.root / "storage/db/no7.sqlite3")
        out.setdefault("datasets", self.root / "storage/datasets")
        out.setdefault("models", self.root / "storage/models")
        out.setdefault("backtests", self.root / "storage/backtests")
        out.setdefault("logs", self.root / "storage/logs")
        # Private artifacts are never adopted from an unscoped legacy directory.
        # Keep the configured database path unchanged: its singleton is the guard.
        for key in ("datasets", "models", "backtests", "logs"):
            out[key] = out[key] / "workspaces" / self.security["workspace_id"]
        return out

    # -------------------------------------------------------------- access
    @property
    def database_path(self) -> Path:
        return self.paths["database"]

    @property
    def security(self) -> dict[str, Any]:
        sec = dict(self.app.get("security", {}))
        sec["workspace_id"] = os.environ.get("NO7_WORKSPACE_ID", sec.get("workspace_id", "local"))
        sec["jwt_secret"] = os.environ.get(sec.get("jwt_secret_env", "NO7_JWT_SECRET"), "") or "no7-local-development-secret-key-change-me-48chars"
        sec["allow_full_auto"] = _as_bool(os.environ.get("NO7_ALLOW_FULL_AUTO", sec.get("allow_full_auto", False)))
        sec["demo_user"] = os.environ.get("NO7_DEMO_USER", sec.get("demo_user", "demo@no7.ai"))
        sec["demo_password"] = os.environ.get("NO7_DEMO_PASSWORD", sec.get("demo_password", "no7demo1234"))
        return sec

    @property
    def cors_origins(self) -> list[str]:
        """Cross-origin callers we answer with CORS headers.

        Default is empty: the dashboard is served from this same origin, and the Vite
        dev server proxies `/api` too, so nothing legitimate needs a wildcard. Set
        `NO7_CORS_ORIGINS=https://dash.example.com,http://localhost:5173` to open a
        specific list, or `*` to open everything (the health endpoint then says so).
        """
        raw = os.environ.get("NO7_CORS_ORIGINS")
        if raw is None:
            raw = (self.app.get("cors") or {}).get("allow_origins", [])
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",")]
        return [str(item).strip().rstrip("/") for item in raw if str(item).strip()]

    @property
    def trusted_proxies(self) -> list[str]:
        """Peers whose X-Forwarded-* headers are believed (CIDRs)."""
        raw = os.environ.get("NO7_TRUSTED_PROXIES")
        if raw is None:
            raw = self.app.get("trusted_proxies", ["127.0.0.1/32", "::1/128"])
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",")]
        return [str(item).strip() for item in raw if str(item).strip()]

    @property
    def security_headers(self) -> dict[str, Any]:
        cfg = dict(self.app.get("security_headers") or {})
        cfg["csp_mode"] = os.environ.get("NO7_CSP_MODE", cfg.get("csp_mode", "enforce"))
        cfg["hsts"] = _as_bool(os.environ.get("NO7_HSTS", cfg.get("hsts", True)))
        return cfg

    @property
    def market_data(self) -> dict[str, Any]:
        return self.app.get("market_data", {})

    @property
    def ai(self) -> dict[str, Any]:
        return self.app.get("ai", {})

    @property
    def execution(self) -> dict[str, Any]:
        return self.app.get("execution", {})

    @property
    def alerts(self) -> dict[str, Any]:
        return self.app.get("alerts", {})

    @property
    def cluster(self) -> dict[str, Any]:
        cfg = dict(self.app.get("cluster", {}))
        cfg["key_prefix"] = f"{cfg.get('key_prefix') or 'no7'}:workspace:{self.security['workspace_id']}"
        return cfg

    # ------------------------------------------------------------- brokers
    def broker(self, broker_id: str) -> dict[str, Any]:
        for profile in self.brokers.get("brokers", []):
            if profile["id"] == broker_id:
                return profile
        raise KeyError(f"unknown broker profile: {broker_id}")

    def default_broker_id(self) -> str:
        return self.brokers.get("default_broker", "connext-demo")

    def broker_symbols(self, broker_id: str) -> dict[str, Any]:
        return self.broker(broker_id).get("symbols", {})

    def symbol_spec(self, broker_id: str, symbol: str) -> dict[str, Any]:
        symbols = self.broker_symbols(broker_id)
        # A broker may expose a different ticker for the same instrument.
        if symbol in symbols:
            return {"symbol": symbol, "source": "declared", **symbols[symbol]}
        for canonical, mapped in (self.broker(broker_id).get("symbol_mapping") or {}).items():
            if mapped == symbol:
                spec = symbols.get(canonical)
                if spec:
                    return {"symbol": canonical, "broker_symbol": symbol, "source": "declared", **spec}
        raise KeyError(f"symbol {symbol} not declared for broker {broker_id}")

    def risk_cfg(self) -> dict[str, Any]:
        return self.risk

    def strategy_cfg(self) -> dict[str, Any]:
        return self.strategies

    def as_public_dict(self) -> dict[str, Any]:
        """Config surfaced to the dashboard (never includes secrets)."""
        return {
            "app": self.app.get("app", {}),
            "market_data": {
                k: v for k, v in self.market_data.items() if k != "simulation"
            },
            "ai": self.ai,
            "paths": {k: str(v) for k, v in self.paths.items()},
            "env": self.env,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
