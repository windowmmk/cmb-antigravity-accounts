"""Unit tests for cmb-antigravity-accounts companion CLI."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from cmb_antigravity_accounts import bridge_client, cli, config, doctor


class CompanionCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cmb_dir = self.root / 'codex-mobile-bridge'
        self.cmb_dir.mkdir()
        (self.cmb_dir / 'desktop.py').write_text('# stub\n', encoding='utf-8')
        self.data_dir = self.cmb_dir / '.local'
        self.data_dir.mkdir()
        self.cfg_path = self.root / 'config.json'

    def test_config_save_and_resolve_priority(self):
        rc = cli.main(['--config', str(self.cfg_path), 'config', '--cmb-dir', str(self.cmb_dir)])
        self.assertEqual(rc, 0)
        cmb, data = config.resolve_paths(config_path=self.cfg_path)
        self.assertEqual(cmb, self.cmb_dir.resolve())
        self.assertEqual(data, self.data_dir.resolve())

        alt_data = self.root / 'custom-data'
        with mock.patch.dict(os.environ, {'CMB_DATA_DIR': str(alt_data)}, clear=False):
            _, data_env = config.resolve_paths(config_path=self.cfg_path)
            self.assertEqual(data_env, alt_data.resolve())

    def test_resolve_paths_rejects_directory_without_desktop_py(self):
        empty = self.root / 'not-cmb'
        empty.mkdir()
        with self.assertRaisesRegex(ValueError, 'desktop.py'):
            config.resolve_paths(cmb_dir=empty, config_path=self.cfg_path)

    def test_call_desktop_sessions_passes_json_and_surfaces_errors(self):
        ok_proc = mock.Mock(returncode=0, stdout=json.dumps({'ok': True, 'result': {'accounts': []}}), stderr='')
        with mock.patch('subprocess.run', return_value=ok_proc) as run_mock:
            res = bridge_client.call_desktop_sessions(self.cmb_dir, self.data_dir, {'action': 'list'})
        self.assertEqual(res, {'accounts': []})
        cmd = run_mock.call_args[0][0]
        self.assertIn(str(self.cmb_dir / 'desktop.py'), cmd)
        self.assertIn('--data-dir', cmd)

        err_proc = mock.Mock(returncode=1, stdout=json.dumps({'ok': False, 'error': '請先正常退出'}), stderr='')
        with mock.patch('subprocess.run', return_value=err_proc):
            with self.assertRaisesRegex(bridge_client.BridgeCommandError, '請先正常退出'):
                bridge_client.call_desktop_sessions(self.cmb_dir, self.data_dir, {'action': 'list'})

    def test_resolve_saved_account_by_index_id_email_and_name(self):
        rows = [
            {'id': 'a' * 32, 'name': 'Main', 'email': 'main@example.invalid', 'saved': True},
            {'id': 'unsaved', 'name': 'Unsaved', 'email': 'temp@example.invalid', 'saved': False},
            {'id': 'b' * 32, 'name': 'Backup', 'email': 'backup@example.invalid', 'saved': True},
        ]
        self.assertEqual(cli.resolve_saved_account(rows, '1')['id'], 'a' * 32)
        self.assertEqual(cli.resolve_saved_account(rows, '2')['id'], 'b' * 32)
        self.assertEqual(cli.resolve_saved_account(rows, 'MAIN@example.invalid')['id'], 'a' * 32)
        self.assertEqual(cli.resolve_saved_account(rows, 'backup')['id'], 'b' * 32)
        with self.assertRaisesRegex(ValueError, '找不到'):
            cli.resolve_saved_account(rows, 'temp@example.invalid')

    def test_save_wait_and_switch_delegate_exclusively_to_desktop_py(self):
        calls = []

        def fake_call(cmb, data, payload, **kwargs):
            calls.append(payload)
            if payload.get('operation') == 'import-current':
                return {'gatewayRunning': True, 'current': {'name': 'Work'}, 'activeIds': [],
                        'accounts': [{'id': 'a' * 32, 'name': 'Work', 'email': 'w@example.invalid', 'saved': True}]}
            if payload.get('operation') == 'list':
                return {'gatewayRunning': True, 'current': {'name': 'Work'}, 'activeIds': [],
                        'switchConfirmation': '確認切換？',
                        'accounts': [{'id': 'a' * 32, 'name': 'Work', 'email': 'w@example.invalid', 'saved': True}]}
            if payload.get('operation') == 'switch':
                return {'gatewayRunning': True, 'message': '已請求重開', 'activeIds': [], 'accounts': []}
            raise AssertionError(f'unexpected payload: {payload}')

        pid_polls = iter([[101], []])
        buf = io.StringIO()
        with mock.patch.object(cli, 'call_desktop_sessions', side_effect=fake_call), \
                mock.patch.object(cli, 'observe_local_antigravity_pids', side_effect=lambda: next(pid_polls)), \
                mock.patch.object(cli.time, 'sleep'), \
                mock.patch('sys.stdout', buf):
            self.assertEqual(
                cli.main(['--cmb-dir', str(self.cmb_dir), 'save', 'Work', '--wait']),
                0,
            )
            self.assertEqual(
                cli.main(['--cmb-dir', str(self.cmb_dir), 'switch', '1', '--yes']),
                0,
            )
        self.assertEqual(calls[0]['operation'], 'import-current')
        self.assertEqual(calls[0]['name'], 'Work')
        self.assertEqual(calls[1]['operation'], 'list')
        self.assertEqual(calls[2]['operation'], 'switch')
        self.assertEqual(calls[2]['id'], 'a' * 32)

    def test_doctor_is_read_only_and_reports_warnings(self):
        def fake_call(cmb, data, payload, **kwargs):
            if payload == {'action': 'clients'}:
                return {'gatewayRunning': True, 'clients': [
                    {'id': 'antigravity', 'installed': True, 'enabled': True, 'connected': True,
                     'installations': {'app': {'executable': '/opt/Antigravity/antigravity'}}}
                ]}
            return {'gatewayRunning': True, 'canImport': True, 'canSwitch': True, 'readOnly': False,
                    'activeIds': ['a' * 32], 'current': {'name': 'Work'},
                    'accounts': [{'id': 'a' * 32, 'saved': True}]}

        with mock.patch.object(doctor, 'call_desktop_sessions', side_effect=fake_call), \
                mock.patch.object(doctor, 'observe_local_antigravity_pids', return_value=[]), \
                mock.patch.object(doctor, 'detect_keyring_backends',
                                  return_value={'platform': 'linux', 'secretstorage': False, 'giSecret': True, 'ready': True}):
            report = doctor.run_doctor(self.cmb_dir, self.data_dir)
        self.assertEqual(report['warnings'], [])
        self.assertEqual(report['accountsStatus']['savedCount'], 1)
        self.assertIn('一切就緒', cli.format_doctor(report))


if __name__ == '__main__':
    unittest.main()
