"""Select an already running MT5 executable on its Windows host, without launching it."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


class TerminalDiscoveryError(RuntimeError):
    pass


def running_terminal_paths() -> list[Path]:
    if sys.platform != "win32":
        raise TerminalDiscoveryError("MT5 ต้องทำงานบน Windows PC · VM100 ใช้ข้อมูลผ่าน Windows bridge")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise TerminalDiscoveryError("ไม่พบตัวตรวจหา MT5 บน Windows PC")
    script = "@(Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path) | ConvertTo-Json -Compress"
    try:
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=8, check=False)
        if result.returncode != 0:
            raise TerminalDiscoveryError("ตรวจหา MT5 ที่เปิดอยู่ไม่สำเร็จ")
        paths = json.loads(result.stdout.strip() or "[]")
        if isinstance(paths, str):
            paths = [paths]
        if not isinstance(paths, list):
            raise TypeError("invalid process list")
        return list(dict.fromkeys(Path(value).resolve() for value in paths if isinstance(value, str) and value))
    except (OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
        raise TerminalDiscoveryError("ตรวจหา MT5 ที่เปิดอยู่ไม่สำเร็จ") from exc


def resolve_running_terminal(explicit: str = "", *, project_root: Path | None = None,
                             running_paths: list[Path] | None = None) -> Path:
    running = running_terminal_paths() if running_paths is None else running_paths
    running = list(dict.fromkeys(path.resolve() for path in running
                                if path.name.lower() == "terminal64.exe" and path.is_file()))
    configured = str(explicit or "").strip()
    if configured:
        selected = Path(configured).resolve()
        if selected not in running:
            raise TerminalDiscoveryError("MT5 ที่กำหนดไว้ยังไม่เปิด · เปิดและล็อกอิน Demo ก่อนเชื่อมต่อ")
        return selected
    root = project_root or Path(__file__).resolve().parents[2]
    managed = (root / "bridge" / "MetaTrader 5" / "terminal64.exe").resolve()
    if managed in running:
        return managed
    if len(running) == 1:
        return running[0]
    if not running:
        raise TerminalDiscoveryError("ยังไม่มี MT5 ที่เปิดอยู่ · เปิดและล็อกอิน Demo บน Windows PC แล้วลองใหม่")
    raise TerminalDiscoveryError("เปิด MT5 หลายตัว · ใช้ terminal ใน bridge หรือให้ผู้ดูแลเลือก terminal ประจำเครื่อง")
