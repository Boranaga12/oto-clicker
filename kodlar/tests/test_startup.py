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


if __name__ == '__main__':
    unittest.main()
