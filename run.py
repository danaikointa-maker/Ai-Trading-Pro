#!/usr/bin/env python3
"""Cross-platform launcher for the isolated local simulation."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
DEFAULT_JWT_SECRET = "no7-local-development-secret-key-change-me-48chars"


def venv_python() -> Path:
    if os.name == "nt":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def local_environment() -> dict[str, str]:
    env = os.environ.copy()
    credential_vault_key = env.get("NO7_CREDENTIAL_VAULT_KEY")
    for name in list(env):
        if name.upper().startswith(("NO7_", "MT5_")):
            env.pop(name)

    local_root = ROOT / "storage" / "local-dev"
    env.update(
        {
            "NO7_ENV": "development",
            "NO7_ROOT": str(ROOT),
            "NO7_FEED_MODE": "simulate",
            "NO7_LOCAL_SIMULATION": "true",
            "NO7_ALLOW_FULL_AUTO": "false",
            "NO7_BRIDGE_ENABLED": "false",
            "NO7_TELEGRAM_ENABLED": "false",
            "NO7_LINE_ENABLED": "false",
            "NO7_WEBHOOK_ENABLED": "false",
            "NO7_CLUSTER_BACKEND": "local",
            "NO7_ALLOW_MULTI_RUNTIME": "false",
            "NO7_AUTO_TRAIN_ON_BOOT": "false",
            "NO7_RATELIMIT_STORE": "memory",
            "NO7_DB_PATH": str(local_root / "db" / "no7-local-simulation.sqlite3"),
            "NO7_DATA_DIR": str(local_root / "datasets"),
            "NO7_MODEL_DIR": str(local_root / "models"),
            "NO7_BACKTEST_DIR": str(local_root / "backtests"),
            "NO7_LOG_DIR": str(local_root / "logs"),
            "MT5_LOGIN": "",
            "MT5_PASSWORD": "",
            "MT5_SERVER": "",
            "MT5_TERMINAL_PATH": str(local_root / "NO_TERMINAL.exe"),
        }
    )
    if credential_vault_key:
        env["NO7_CREDENTIAL_VAULT_KEY"] = credential_vault_key
    return env


def setup_command() -> list[str]:
    if os.name == "nt":
        powershell = shutil.which("pwsh") or shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            raise RuntimeError("PowerShell was not found; install PowerShell and retry.")
        return [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "setup-windows.ps1"),
        ]

    bash = shutil.which("bash")
    if not bash:
        raise RuntimeError("Bash was not found; install Bash and retry.")
    return [bash, str(ROOT / "scripts" / "dev_setup.sh")]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Set up or run No7 locally in simulated/paper mode on Windows, macOS, or Linux."
    )
    result.add_argument(
        "--setup",
        action="store_true",
        help="install local dependencies and build the dashboard, then continue",
    )
    result.add_argument(
        "--check",
        action="store_true",
        help="validate the local safety configuration without starting the server",
    )
    result.add_argument("--port", type=int, default=8000, help="loopback server port (default: 8000)")
    return result


def run_setup(port: int, check_only: bool) -> int:
    try:
        subprocess.run(setup_command(), cwd=ROOT, check=True)
    except (OSError, RuntimeError) as exc:
        print(f"Setup could not start: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1

    python = venv_python()
    if not python.is_file():
        print(f"Setup finished without creating the expected environment: {python}", file=sys.stderr)
        return 2

    command = [str(python), str(Path(__file__).resolve()), "--port", str(port)]
    if check_only:
        command.append("--check")
    return subprocess.run(command, cwd=ROOT, env=local_environment()).returncode


def validate_local_settings() -> None:
    try:
        from packages.shared_schemas.settings import Settings
    except ImportError as exc:
        raise RuntimeError("Python dependencies are missing; run `python run.py --setup`.") from exc

    settings = Settings()
    if settings.market_data.get("feed_mode") != "simulate":
        raise ValueError("local launcher requires simulated market data")
    if not settings.brokers.get("brokers") or any(
        profile.get("adapter", "simulated_mt5") not in ("paper", "simulated_mt5")
        for profile in settings.brokers["brokers"]
    ):
        raise ValueError("local launcher allows paper/simulated broker profiles only")
    if settings.security.get("allow_full_auto"):
        raise ValueError("full-auto trading must remain disabled")
    if not settings.security.get("require_auth", True):
        raise ValueError("authentication must remain enabled")

    secret = settings.security.get("jwt_secret", "")
    if len(secret) < 32 or secret == DEFAULT_JWT_SECRET:
        raise ValueError("set a private NO7_JWT_SECRET in the repository .env file")


def main() -> int:
    args = parser().parse_args()
    if not 1024 <= args.port <= 65535:
        parser().error("--port must be between 1024 and 65535")

    if args.setup:
        return run_setup(args.port, args.check)

    python = venv_python()
    if not python.is_file():
        print("Local environment is missing; run `python run.py --setup` first.", file=sys.stderr)
        return 2

    if Path(sys.executable).resolve() != python.resolve():
        command = [str(python), str(Path(__file__).resolve()), *sys.argv[1:]]
        return subprocess.run(command, cwd=ROOT, env=local_environment()).returncode

    os.environ.update(local_environment())
    try:
        validate_local_settings()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Local startup check failed: {exc}", file=sys.stderr)
        return 2

    dashboard = ROOT / "apps" / "web-dashboard" / "dist" / "index.html"
    if not dashboard.is_file():
        print("Dashboard bundle is missing; run `python run.py --setup` first.", file=sys.stderr)
        return 2

    if args.check:
        print("Local checks passed: simulated feed, paper brokers, authentication, and dashboard.")
        return 0

    print(f"Local simulated trading only: http://127.0.0.1:{args.port} (Ctrl+C to stop)", flush=True)
    return subprocess.run(
        [
            str(python),
            "-m",
            "uvicorn",
            "services.api_gateway.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
            "--workers",
            "1",
            "--no-proxy-headers",
        ],
        cwd=ROOT,
        env=os.environ.copy(),
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
