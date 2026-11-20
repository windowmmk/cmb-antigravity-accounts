"""Thin subprocess client for codex-mobile-bridge's public desktop.py channel."""
from pathlib import Path
import json
import subprocess
import sys


class BridgeCommandError(RuntimeError):
    """Raised when CMB desktop.py rejects an operation or fails."""


def call_desktop_sessions(
    cmb_dir: Path,
    data_dir: Path,
    payload: dict,
    *,
    python_executable: str | None = None,
    timeout: float = 90.0,
) -> dict:
    """Invoke `<cmb>/desktop.py desktop-sessions --data-dir <data_dir>` over JSON stdin/stdout."""
    desktop_script = Path(cmb_dir) / 'desktop.py'
    if not desktop_script.is_file():
        raise BridgeCommandError(f'找不到 desktop.py：{desktop_script}')
    cmd = [
        python_executable or sys.executable,
        '-B',
        str(desktop_script),
        'desktop-sessions',
        '--data-dir',
        str(data_dir),
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeCommandError(f'呼叫 CMB desktop.py 逾時（>{int(timeout)}s）') from exc
    except OSError as exc:
        raise BridgeCommandError(f'無法執行 CMB desktop.py：{exc}') from exc

    raw = (proc.stdout or '').strip()
    try:
        response = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        response = {}

    if proc.returncode != 0 or not isinstance(response, dict) or not response.get('ok'):
        detail = (
            (response.get('error') if isinstance(response, dict) else None)
            or (proc.stderr or '').strip()
            or raw
            or f'desktop.py 結束碼 {proc.returncode}'
        )
        raise BridgeCommandError(str(detail))

    result = response.get('result')
    return result if isinstance(result, dict) else {}
