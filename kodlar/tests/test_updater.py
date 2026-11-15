from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from kodlar import updater


class UpdateTests(unittest.TestCase):
    def package(self, extras=None):
        contents = {
            'baslat.bat': b'new launcher',
            'kodlar/__init__.py': b'__version__ = "2.1.2"\n',
            'kodlar/launcher.py': b'# new code',
            'kodlar/requirements.txt': b'pynput>=1.7.6,<2.0\n',
        }
        contents.update(extras or {})
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as bundle:
            for name, data in contents.items():
                bundle.writestr('oto-clicker/' + name, data)
        return output.getvalue()

    def installed(self, directory):
        root = Path(directory) / 'app'
        (root / 'kodlar').mkdir(parents=True)
        (root / 'kodlar/requirements.txt').write_bytes(b'pynput>=1.7.6,<2.0\n')
        (root / 'baslat.bat').write_bytes(b'old launcher')
        return root

    def prepare(self, root, directory, data=None, **manifest):
        data = data or self.package()
        info = {'version': '2.1.2', 'sha256': hashlib.sha256(data).hexdigest(), **manifest}
        with patch.object(updater, 'fetch', side_effect=[json.dumps(info).encode(), data]):
            return updater.prepare_update(root, '2.1.1', Path(directory) / 'cache')

    def test_verified_release_installs_without_touching_settings_or_virtualenv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.installed(directory)
            (root / 'kodlar/profiles.json').write_text('my profiles')
            (root / 'kodlar/.venv').mkdir()
            (root / 'kodlar/.venv/marker').write_text('dependencies')
            stage = self.prepare(root, directory)
            updater.install_payload(stage, root)
            self.assertEqual((root / 'baslat.bat').read_bytes(), b'new launcher')
            self.assertEqual((root / 'kodlar/profiles.json').read_text(), 'my profiles')
            self.assertEqual((root / 'kodlar/.venv/marker').read_text(), 'dependencies')

    def test_no_download_for_installed_or_older_version(self):
        with patch.object(updater, 'fetch', return_value=b'{"version":"2.1.1"}') as fetch:
            self.assertIsNone(updater.prepare_update(Path('.'), '2.1.1', Path('unused')))
            fetch.assert_called_once_with('update.json')

    def test_banner_notification_precedes_version_pinned_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.installed(directory)
            archive = self.package()
            events = []
            manifest = json.dumps({'version': '2.1.2', 'sha256': hashlib.sha256(archive).hexdigest()}).encode()

            def fetch(name, **options):
                events.append((name, options))
                return manifest if name == 'update.json' else archive

            with patch.object(updater, 'fetch', side_effect=fetch):
                updater.prepare_update(root, '2.1.1', Path(directory)/'cache',
                                       on_available=lambda version: events.append(('available', version)))
            self.assertEqual(events, [('update.json', {}), ('available', '2.1.2'),
                                      ('arik-makro.zip', {'version': '2.1.2'})])

    def test_tampered_archive_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.installed(directory)
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                self.prepare(root, directory, sha256='0' * 64)
            self.assertEqual((root / 'baslat.bat').read_bytes(), b'old launcher')

    def test_paths_cannot_escape_or_overwrite_user_data(self):
        for name in ('../escape.py', 'oto-clicker/../escape.py',
                     'oto-clicker/.venv/file.py', 'oto-clicker/kodlar/profiles.json',
                     'oto-clicker/kodlar/settings.ini', 'oto-clicker/C:/x.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                updater.allowed_path(name)

    def test_partial_install_rolls_back_replaced_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.installed(directory)
            stage = self.prepare(root, directory)
            replace = os.replace

            def fail_on_code(source, target):
                if Path(target).name == '__init__.py':
                    raise OSError('file locked')
                return replace(source, target)

            with patch.object(updater.os, 'replace', side_effect=fail_on_code):
                with self.assertRaisesRegex(OSError, 'file locked'):
                    updater.install_payload(stage, root)
            self.assertEqual((root / 'baslat.bat').read_bytes(), b'old launcher')
            self.assertFalse((root / 'kodlar/__init__.py').exists())

    def test_git_checkout_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.installed(directory)
            (root / '.git').mkdir()
            stage = self.prepare(root, directory)
            with self.assertRaisesRegex(ValueError, 'Git'):
                updater.install_payload(stage, root)

    def test_dependency_change_requires_normal_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.installed(directory)
            with self.assertRaisesRegex(ValueError, 'Bağımlılıklar'):
                self.prepare(root, directory, self.package({'kodlar/requirements.txt': b'new dependency'}))
            self.assertEqual(list((Path(directory) / 'cache').iterdir()), [])

    def test_update_waits_while_macros_are_running(self):
        from unittest.mock import Mock
        from kodlar.gui import ClickerApp
        app = ClickerApp.__new__(ClickerApp)
        app._update_stage = Path('staged')
        app.clicker = Mock(is_running=True)
        with patch('kodlar.gui.schedule_install') as launch:
            app.apply_pending_update()
            launch.assert_not_called()
        self.assertEqual(app._update_stage, Path('staged'))


class UpdateMonitorTests(unittest.TestCase):
    def monitor(self, notify=lambda event: None):
        monitor = updater.UpdateMonitor(Path('.'), '2.5.2', Path('unused'), notify, interval=0.01)
        self.addCleanup(lambda: monitor.thread.join(2) if monitor.thread else None)
        self.addCleanup(monitor.stop)
        return monitor

    def test_checks_repeatedly_without_reopening_application(self):
        monitor = self.monitor()
        checked = threading.Event()
        calls = []

        def prepare(*args, **kwargs):
            calls.append(args[1])
            if len(calls) >= 3:
                monitor.stop()
                checked.set()

        with patch.object(updater, 'prepare_update', side_effect=prepare):
            monitor.start()
            first_thread = monitor.thread
            monitor.start()
            self.assertIs(monitor.thread, first_thread)
            self.assertTrue(checked.wait(2))
            monitor.thread.join(2)
        self.assertEqual(calls, ['2.5.2'] * 3)

    def test_ready_release_is_not_downloaded_again_at_next_poll(self):
        events, baselines = [], []
        monitor = self.monitor(events.append)
        checked = threading.Event()

        def prepare(install, baseline, cache, *, on_available):
            baselines.append(baseline)
            if len(baselines) == 1:
                on_available('2.6.0')
                return Path('prepared')
            monitor.stop()
            checked.set()

        with patch.object(updater, 'prepare_update', side_effect=prepare):
            monitor.start()
            self.assertTrue(checked.wait(2))
            monitor.thread.join(2)
        self.assertEqual(baselines, ['2.5.2', '2.6.0'])
        self.assertEqual(events, [('update_available', '2.6.0'),
                                  ('update_ready', ('2.6.0', Path('prepared')))])

    def test_shutdown_discards_late_network_results(self):
        events = []
        monitor = self.monitor(events.append)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def prepare(*args, on_available, **kwargs):
            entered.set()
            release.wait(2)
            on_available('2.6.0')
            return Path('prepared')

        with patch.object(updater, 'prepare_update', side_effect=prepare):
            monitor.start()
            self.assertTrue(entered.wait(2))
            monitor.stop()
            release.set()
            monitor.thread.join(2)
        self.assertEqual(events, [])

    def test_network_failure_does_not_stop_later_checks(self):
        events = []
        monitor = self.monitor(events.append)
        checked = threading.Event()
        attempts = []

        def prepare(*args, on_available, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError('offline')
            on_available('2.6.0')
            checked.set()
            return Path('prepared')

        with patch.object(updater, 'prepare_update', side_effect=prepare):
            monitor.start()
            self.assertTrue(checked.wait(2))
            monitor.stop()
            monitor.thread.join(2)
        self.assertEqual(events[0], ('update_failed', 'offline'))
        self.assertIn(('update_available', '2.6.0'), events)


if __name__ == '__main__':
    unittest.main()
