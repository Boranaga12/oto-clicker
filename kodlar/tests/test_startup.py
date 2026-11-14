from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from kodlar import main


class StartupTests(unittest.TestCase):
    def test_launch_failure_prints_traceback_and_returns_failure(self):
        output = io.StringIO()
        with patch.object(main, 'main', side_effect=RuntimeError('startup failed')):
            with redirect_stderr(output):
                result = main.cli()
        self.assertEqual(result, 1)
        self.assertIn('Traceback', output.getvalue())
        self.assertIn('RuntimeError: startup failed', output.getvalue())

    def test_normal_shutdown_returns_success(self):
        with patch.object(main, 'main'):
            self.assertEqual(main.cli(), 0)


class HiddenLauncherTests(unittest.TestCase):
    def test_import_failure_is_reported_without_console(self):
        import sys
        from kodlar import launcher

        with patch.dict(sys.modules, {'kodlar.main': None}):
            with patch.object(launcher, 'report_startup_error') as report:
                self.assertEqual(launcher.main(), 1)
        self.assertIsInstance(report.call_args.args[0], ImportError)

    def test_hidden_startup_reports_runtime_failure(self):
        from kodlar import launcher

        with patch.object(main, 'main', side_effect=RuntimeError('startup failed')):
            with patch.object(launcher, 'report_startup_error') as report:
                self.assertEqual(launcher.main(), 1)
        self.assertEqual(str(report.call_args.args[0]), 'startup failed')

    def test_error_dialog_and_log_do_not_require_tkinter_or_console(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from kodlar import launcher

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'startup-error.log'
            user32 = unittest.mock.Mock()
            with patch.object(launcher, 'writable_data_file', return_value=destination):
                with patch.object(launcher, 'os', SimpleNamespace(name='nt')):
                    with patch.object(launcher.ctypes, 'windll', SimpleNamespace(user32=user32), create=True):
                        try:
                            raise RuntimeError('no console')
                        except RuntimeError as error:
                            launcher.report_startup_error(error)
            self.assertIn('RuntimeError: no console', destination.read_text())
            self.assertIn(str(destination), user32.MessageBoxW.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
