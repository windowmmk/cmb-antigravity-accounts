"""Pointer configuration for locating an existing codex-mobile-bridge installation."""
from pathlib import Path
import json
import os


def default_config_path() -> Path:
    xdg = os.environ.get('XDG_CONFIG_HOME')
    base = Path(xdg).expanduser() if xdg else (Path.home() / '.config')
    return base / 'cmb-antigravity-accounts' / 'config.json'


def load_config(config_path: Path | None = None) -> dict:
    path = Path(config_path) if config_path else default_config_path()
    try:
        raw = path.read_text(encoding='utf-8')
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(values: dict, config_path: Path | None = None) -> Path:
    path = Path(config_path) if config_path else default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix('.json.tmp')
    payload = json.dumps(values, ensure_ascii=False, indent=2) + '\n'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(payload)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    return path


def resolve_paths(
    *,
    cmb_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    config_path: Path | None = None,
    repo_root: Path | None = None,
) -> tuple[Path, Path]:
    """Resolve CMB directory and gateway data directory without importing CMB internals."""
    saved = load_config(config_path)
    raw_cmb = cmb_dir or os.environ.get('CMB_DIR') or saved.get('cmbDir')
    if not raw_cmb:
        anchor = (Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]).parent
        sibling = anchor / 'codex-mobile-bridge'
        if (sibling / 'desktop.py').is_file():
            raw_cmb = sibling
    if not raw_cmb:
        raise ValueError(
            '未指定 codex-mobile-bridge 路徑；請使用 --cmb-dir、設定環境變數 CMB_DIR，'
            '或先執行 `cmb-agy-accounts config --cmb-dir <路徑>`'
        )
    resolved_cmb = Path(raw_cmb).expanduser().resolve()
    if not (resolved_cmb / 'desktop.py').is_file():
        raise ValueError(f'在 {resolved_cmb} 找不到 codex-mobile-bridge 的 desktop.py 入口')

    raw_data = data_dir or os.environ.get('CMB_DATA_DIR') or saved.get('dataDir')
    resolved_data = Path(raw_data).expanduser().resolve() if raw_data else (resolved_cmb / '.local')
    return resolved_cmb, resolved_data
