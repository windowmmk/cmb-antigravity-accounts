"""Command-line interface for headless Antigravity account operations via CMB desktop.py."""
from pathlib import Path
import argparse
import json
import sys
import time

from .bridge_client import BridgeCommandError, call_desktop_sessions
from .config import default_config_path, load_config, resolve_paths, save_config
from .doctor import observe_local_antigravity_pids, run_doctor


def resolve_saved_account(accounts: list[dict], selector: str) -> dict:
    """Match a saved CMB Antigravity account by 1-based index, ID, email, or name."""
    needle = str(selector or '').strip()
    if not needle:
        raise ValueError('請指定目標帳號序號、ID、信箱或顯示名稱')
    saved = [row for row in accounts if row.get('saved') is not False]
    if needle.isdigit():
        idx = int(needle) - 1
        if 0 <= idx < len(saved):
            return saved[idx]
    for field in ('id', 'email', 'name'):
        matches = [row for row in saved if str(row.get(field) or '').casefold() == needle.casefold()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f'存在多個符合「{selector}」的已保存帳號，請改用帳號 ID 或序號')
    raise ValueError(f'找不到已保存帳號「{selector}」；請先執行 list 查看')


def format_accounts(result: dict) -> str:
    lines = []
    gateway = '運行中' if result.get('gatewayRunning') else '未運行（離線模式）'
    current = (result.get('current') or {}).get('name') or '暫未識別'
    lines.append(f'網關：{gateway} | 當前接入：{current}')
    if result.get('message'):
        lines.append(f"狀態提示：{result['message']}")
    active_ids = set(result.get('activeIds') or [])
    accounts = result.get('accounts') or []
    if not accounts:
        lines.append('帳號清單：暫無（請先在原客戶端登入，正常關閉後執行 save 保存）')
        return '\n'.join(lines)
    lines.append('帳號清單：')
    saved_index = 0
    for row in accounts:
        is_saved = row.get('saved') is not False
        if is_saved:
            saved_index += 1
            prefix = f'  {saved_index}. '
        else:
            prefix = '  -. '
        tags = []
        if row.get('id') in active_ids:
            tags.append('當前接入')
        tags.append('已保存' if is_saved else '尚未保存')
        email = row.get('email') or ''
        name = row.get('name') or email or row.get('id')
        tag_text = ' / '.join(tags)
        lines.append(f"{prefix}{name} <{email}> [{tag_text}] id={row.get('id')}")
    return '\n'.join(lines)


def format_doctor(report: dict) -> str:
    lines = [
        f"CMB 路徑：{report['cmbDir']} ({'正常' if report['desktopEntryExists'] else '缺少 desktop.py'})",
        f"資料目錄：{report['dataDir']} ({'存在' if report['dataDirExists'] else '尚未建立'})",
    ]
    kr = report['keyringBackends']
    lines.append(
        f"系統憑證庫（{kr['platform']}）："
        f"secretstorage={'有' if kr['secretstorage'] else '無'} / "
        f"libsecret GI={'有' if kr['giSecret'] else '無'}"
    )
    pids = report['observedAntigravityPids']
    lines.append(f"本機 Antigravity 相關進程：{len(pids)} 個" + (f' {pids}' if pids else '（已全部退出）'))
    cs = report.get('clientsStatus') or {}
    if 'error' in cs:
        lines.append(f"CMB 客戶端狀態：讀取失敗（{cs['error']}）")
    elif cs:
        agy = cs.get('antigravity') or {}
        lines.append(
            f"CMB 網關：{'運行中' if cs.get('gatewayRunning') else '未運行'} | "
            f"Antigravity：啟用={'是' if agy.get('enabled') else '否'} / "
            f"連線={'是' if agy.get('connected') else '否'} / "
            f"狀態={agy.get('reason') or agy.get('setupStatus') or '未知'}"
        )
    acc = report.get('accountsStatus') or {}
    if 'error' in acc:
        lines.append(f"CMB 帳號狀態：讀取失敗（{acc['error']}）")
    elif acc:
        lines.append(
            f"已保存帳號：{acc.get('savedCount', 0)} 個 | "
            f"當前識別：{acc.get('currentName') or '暫未識別'} | "
            f"允許保存={'是' if acc.get('canImport') else '否'} / 允許切換={'是' if acc.get('canSwitch') else '否'}"
        )
    warnings = report.get('warnings') or []
    if warnings:
        lines.append('提示：')
        for item in warnings:
            lines.append(f'  - {item}')
    else:
        lines.append('檢查結果：一切就緒。')
    return '\n'.join(lines)


def wait_until_antigravity_stopped(timeout: float, *, poll_interval: float = 0.5) -> None:
    """Wait until local Antigravity processes exit before delegating save to CMB."""
    deadline = None if timeout <= 0 else time.monotonic() + timeout
    announced = False
    while True:
        pids = observe_local_antigravity_pids()
        if not pids:
            return
        if not announced:
            print(
                f'偵測到 Antigravity 仍在執行（{len(pids)} 個相關進程），請先在桌面正常關閉視窗…',
                file=sys.stderr,
                flush=True,
            )
            announced = True
        if deadline is not None and time.monotonic() >= deadline:
            raise ValueError('等待 Antigravity 退出逾時，尚未保存帳號')
        time.sleep(poll_interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='cmb-agy-accounts',
        description='無頭 Linux 伴生工具：僅經由 codex-mobile-bridge 官方 desktop.py 通道管理 Antigravity 帳號快照',
    )
    parser.add_argument('--cmb-dir', default=None, help='codex-mobile-bridge 倉庫路徑（可改由環境變數 CMB_DIR 或 config 設定）')
    parser.add_argument('--data-dir', default=None, help='CMB 網關資料目錄（預設 <cmb-dir>/.local）')
    parser.add_argument('--python', dest='python_bin', default=None, help='用來執行 CMB desktop.py 的 Python 路徑')
    parser.add_argument('--config', dest='config_path', default=None, help='自訂設定檔路徑')
    sub = parser.add_subparsers(dest='command')

    p_cfg = sub.add_parser('config', help='檢視或保存預設 CMB 指向路徑')
    p_cfg.add_argument('--cmb-dir', dest='sub_cmb_dir', default=None, help='要保存的 codex-mobile-bridge 倉庫路徑')
    p_cfg.add_argument('--data-dir', dest='sub_data_dir', default=None, help='要保存的 CMB 網關資料目錄')
    p_cfg.add_argument('--show', action='store_true', help='只顯示目前設定')
    p_cfg.add_argument('--json', action='store_true', help='輸出 JSON')

    p_doc = sub.add_parser('doctor', help='唯讀檢查 CMB 指向、系統憑證庫後端、Antigravity 進程與帳號狀態')
    p_doc.add_argument('--json', action='store_true', help='輸出 JSON')

    p_list = sub.add_parser('list', help='查看當前接入與已保存帳號清單')
    p_list.add_argument('--json', action='store_true', help='輸出 JSON')

    p_save = sub.add_parser('save', help='保存當前原生登入為 CMB 帳號快照（須先正常關閉 Antigravity）')
    p_save.add_argument('name', nargs='?', default='', help='顯示名稱（省略時使用信箱）')
    p_save.add_argument('--wait', action='store_true', help='若 Antigravity 仍在運行，等待手動關閉後自動保存')
    p_save.add_argument('--timeout', type=float, default=0.0, help='--wait 逾時秒數（0 表示持續等待直至 Ctrl+C）')
    p_save.add_argument('--json', action='store_true', help='輸出 JSON')

    p_switch = sub.add_parser('switch', help='經由 CMB 安全生命週期切換至指定已保存帳號')
    p_switch.add_argument('target', help='目標帳號序號（1 起算）、ID、信箱或顯示名稱')
    p_switch.add_argument('--yes', '-y', action='store_true', help='略過互動確認（腳本模式）')
    p_switch.add_argument('--json', action='store_true', help='輸出 JSON')

    p_rename = sub.add_parser('rename', help='修改已保存帳號顯示名稱')
    p_rename.add_argument('target', help='目標帳號序號、ID、信箱或顯示名稱')
    p_rename.add_argument('name', help='新的顯示名稱')
    p_rename.add_argument('--json', action='store_true', help='輸出 JSON')

    p_remove = sub.add_parser('remove', help='刪除 CMB 保存的帳號快照（不影響系統目前登入）')
    p_remove.add_argument('target', help='目標帳號序號、ID、信箱或顯示名稱')
    p_remove.add_argument('--yes', '-y', action='store_true', help='略過互動確認')
    p_remove.add_argument('--json', action='store_true', help='輸出 JSON')

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or 'list'
    cfg_path = Path(args.config_path).expanduser().resolve() if args.config_path else default_config_path()

    try:
        if command == 'config':
            current = load_config(cfg_path)
            target_cmb = getattr(args, 'sub_cmb_dir', None) or args.cmb_dir
            target_data = getattr(args, 'sub_data_dir', None) or args.data_dir
            if not args.show and (target_cmb or target_data):
                updated = dict(current)
                if target_cmb:
                    cmb = Path(target_cmb).expanduser().resolve()
                    if not (cmb / 'desktop.py').is_file():
                        raise ValueError(f'在 {cmb} 找不到 desktop.py')
                    updated['cmbDir'] = str(cmb)
                if target_data:
                    updated['dataDir'] = str(Path(target_data).expanduser().resolve())
                save_config(updated, cfg_path)
                current = updated
            if getattr(args, 'json', False):
                print(json.dumps({'configPath': str(cfg_path), **current}, ensure_ascii=False, indent=2))
            else:
                print(f'設定檔：{cfg_path}')
                print(f"cmbDir ：{current.get('cmbDir') or '（未設定，將嘗試自動偵測）'}")
                print(f"dataDir：{current.get('dataDir') or '（預設 <cmbDir>/.local）'}")
            return 0

        cmb_dir, data_dir = resolve_paths(
            cmb_dir=args.cmb_dir,
            data_dir=args.data_dir,
            config_path=cfg_path,
        )

        if command == 'doctor':
            report = run_doctor(cmb_dir, data_dir, python_executable=args.python_bin)
            if getattr(args, 'json', False):
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(format_doctor(report))
            return 0

        if command == 'list':
            result = call_desktop_sessions(
                cmb_dir,
                data_dir,
                {'action': 'accounts', 'provider': 'antigravity', 'operation': 'list'},
                python_executable=args.python_bin,
            )
            if getattr(args, 'json', False):
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(format_accounts(result))
            return 0

        if command == 'save':
            if args.wait:
                wait_until_antigravity_stopped(args.timeout)
            result = call_desktop_sessions(
                cmb_dir,
                data_dir,
                {'action': 'accounts', 'provider': 'antigravity', 'operation': 'import-current', 'name': args.name},
                python_executable=args.python_bin,
            )
            if getattr(args, 'json', False):
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print('已透過 CMB 官方通道保存當前帳號快照。')
                print(format_accounts(result))
            return 0

        listing = call_desktop_sessions(
            cmb_dir,
            data_dir,
            {'action': 'accounts', 'provider': 'antigravity', 'operation': 'list'},
            python_executable=args.python_bin,
        )
        row = resolve_saved_account(listing.get('accounts') or [], args.target)

        if command == 'switch':
            if not args.yes:
                hint = listing.get('switchConfirmation') or '確認透過 CMB 切換 Antigravity 帳號？'
                print(f"即將切換至：{row.get('name') or row.get('email')} <{row.get('email', '')}>")
                print(hint)
                reply = input('輸入 y 確認執行，其他鍵取消：').strip().lower()
                if reply not in ('y', 'yes'):
                    print('已取消切換。')
                    return 0
            result = call_desktop_sessions(
                cmb_dir,
                data_dir,
                {'action': 'accounts', 'provider': 'antigravity', 'operation': 'switch', 'id': row['id']},
                python_executable=args.python_bin,
            )
            if getattr(args, 'json', False):
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(result.get('message') or '已完成帳號切換。')
                print(format_accounts(result))
            return 0

        if command == 'rename':
            result = call_desktop_sessions(
                cmb_dir,
                data_dir,
                {'action': 'accounts', 'provider': 'antigravity', 'operation': 'rename', 'id': row['id'], 'name': args.name},
                python_executable=args.python_bin,
            )
            if getattr(args, 'json', False):
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(format_accounts(result))
            return 0

        if command == 'remove':
            if not args.yes:
                print(f"即將刪除 CMB 保存的快照：{row.get('name') or row.get('email')} <{row.get('email', '')}>")
                reply = input('僅刪除網關副本，不影響電腦目前登入。輸入 y 確認：').strip().lower()
                if reply not in ('y', 'yes'):
                    print('已取消刪除。')
                    return 0
            result = call_desktop_sessions(
                cmb_dir,
                data_dir,
                {'action': 'accounts', 'provider': 'antigravity', 'operation': 'remove', 'id': row['id']},
                python_executable=args.python_bin,
            )
            if getattr(args, 'json', False):
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(format_accounts(result))
            return 0

        parser.print_help()
        return 2
    except KeyboardInterrupt:
        print('\n已取消。', file=sys.stderr)
        return 130
    except (ValueError, BridgeCommandError) as exc:
        print(f'錯誤：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
