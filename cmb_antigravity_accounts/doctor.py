"""Read-only environment diagnostics and process-wait hints (never kills or reads secrets)."""
from pathlib import Path
import importlib.util
import os
import sys

from .bridge_client import BridgeCommandError, call_desktop_sessions

_WRITER_NAMES = frozenset({
    'agy', 'agy.exe', 'antigravity', 'antigravity.exe',
    'antigravity ide', 'antigravity ide.exe', 'antigravity-ide',
})


def observe_local_antigravity_pids(*, proc_root: Path = Path('/proc')) -> list[int]:
    """Best-effort read-only Linux /proc hint used for `--wait` UX and `doctor`.

    Authoritative stop verification is always enforced inside CMB's desktop.py.
    """
    if not sys.platform.startswith('linux') or not proc_root.is_dir():
        return []
    uid = os.getuid()
    pids: list[int] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
        except OSError:
            continue
        pid = int(entry.name)
        try:
            raw_exe = os.readlink(entry / 'exe')
        except FileNotFoundError:
            continue
        except PermissionError:
            try:
                comm = (entry / 'comm').read_text(encoding='utf-8', errors='replace').strip().casefold()
            except OSError:
                continue
            if comm in _WRITER_NAMES or comm.startswith(('antigravity', 'language_server')):
                pids.append(pid)
            continue
        except OSError:
            continue

        clean = Path(raw_exe.removesuffix(' (deleted)'))
        name = clean.name.casefold()
        if name in _WRITER_NAMES:
            pids.append(pid)
            continue
        if name.startswith('language_server'):
            if any('antigravity' in part.casefold() for part in clean.parts):
                pids.append(pid)
                continue
            try:
                cmd = (entry / 'cmdline').read_bytes().decode('utf-8', errors='replace').casefold()
            except OSError:
                continue
            if 'antigravity' in cmd:
                pids.append(pid)
    return sorted(pids)


def detect_keyring_backends() -> dict:
    """Purely check Python module availability without opening or reading any secret."""
    has_secretstorage = importlib.util.find_spec('secretstorage') is not None
    has_gi_secret = False
    if importlib.util.find_spec('gi') is not None:
        try:
            import gi
            gi.require_version('Secret', '1')
            from gi.repository import Secret  # noqa: F401
            has_gi_secret = True
        except Exception:
            has_gi_secret = False
    return {
        'platform': sys.platform,
        'secretstorage': has_secretstorage,
        'giSecret': has_gi_secret,
        'ready': (not sys.platform.startswith('linux')) or has_secretstorage or has_gi_secret,
    }


def run_doctor(cmb_dir: Path, data_dir: Path, *, python_executable: str | None = None) -> dict:
    """Collect a read-only health report of CMB pointing, keyring readiness, and Antigravity state."""
    backends = detect_keyring_backends()
    local_pids = observe_local_antigravity_pids()
    report: dict = {
        'cmbDir': str(cmb_dir),
        'dataDir': str(data_dir),
        'desktopEntryExists': (cmb_dir / 'desktop.py').is_file(),
        'dataDirExists': data_dir.is_dir(),
        'keyringBackends': backends,
        'observedAntigravityPids': local_pids,
        'clientsStatus': None,
        'accountsStatus': None,
        'warnings': [],
    }

    if sys.platform.startswith('linux') and not backends['ready']:
        report['warnings'].append(
            '未偵測到 Linux Secret Service Python 後端（請安裝 python3-secretstorage 或 python3-gi + gir1.2-secret-1）'
        )
    if local_pids:
        report['warnings'].append(
            f'目前偵測到 {len(local_pids)} 個本機 Antigravity 相關進程；執行 save 前請先在桌面正常關閉，switch 會走 CMB 原生安全重啟'
        )

    try:
        clients = call_desktop_sessions(
            cmb_dir, data_dir, {'action': 'clients'}, python_executable=python_executable, timeout=30.0
        )
        agy = next((row for row in (clients.get('clients') or []) if row.get('id') == 'antigravity'), None)
        report['clientsStatus'] = {
            'gatewayRunning': bool(clients.get('gatewayRunning')),
            'antigravity': {
                'installed': bool(agy.get('installed')) if isinstance(agy, dict) else False,
                'enabled': bool(agy.get('enabled')) if isinstance(agy, dict) else False,
                'connected': bool(agy.get('connected')) if isinstance(agy, dict) else False,
                'setupStatus': agy.get('setupStatus', '') if isinstance(agy, dict) else '',
                'reason': agy.get('reason', '') if isinstance(agy, dict) else '未出現在客戶端清單中',
            },
        }
        if not report['clientsStatus']['antigravity']['installed']:
            report['warnings'].append('CMB 尚未偵測到 Antigravity 客戶端，請先在 CMB 掃描或確認資料目錄')
    except BridgeCommandError as exc:
        report['clientsStatus'] = {'error': str(exc)}
        report['warnings'].append(f'讀取 CMB 客戶端狀態失敗：{exc}')

    try:
        accounts = call_desktop_sessions(
            cmb_dir,
            data_dir,
            {'action': 'accounts', 'provider': 'antigravity', 'operation': 'list'},
            python_executable=python_executable,
            timeout=30.0,
        )
        saved_count = sum(1 for row in (accounts.get('accounts') or []) if row.get('saved') is not False)
        report['accountsStatus'] = {
            'gatewayRunning': bool(accounts.get('gatewayRunning')),
            'canImport': bool(accounts.get('canImport')),
            'canSwitch': bool(accounts.get('canSwitch')),
            'readOnly': bool(accounts.get('readOnly')),
            'savedCount': saved_count,
            'activeIds': list(accounts.get('activeIds') or []),
            'currentName': (accounts.get('current') or {}).get('name') or '',
        }
    except BridgeCommandError as exc:
        report['accountsStatus'] = {'error': str(exc)}
        report['warnings'].append(f'讀取 CMB Antigravity 帳號狀態失敗：{exc}')

    return report
