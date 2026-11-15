from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from kodlar.tests.test_edit_lock import EditLockTests as Fixture


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'A desktop display is required')
class UpdateBannerTests(unittest.TestCase):
    setUp = Fixture.setUp
    close = Fixture.close
    process_queue_now = Fixture.process_queue_now
    start = Fixture.start

    def stage(self):
        stage = Path(self.directory.name)/'update'
        (stage/'payload').mkdir(parents=True, exist_ok=True)
        return stage

    def ready(self):
        stage = self.stage()
        self.app.log_queue.put(('update_available', '9.0.0'))
        self.app.log_queue.put(('update_ready', ('9.0.0', stage)))
        self.process_queue_now()
        self.root.update()
        return stage

    def test_banner_appears_during_macros_but_never_installs_without_click(self):
        self.assertEqual(self.app.update_button.winfo_manager(), '')
        self.start()
        with patch('kodlar.gui.schedule_install') as install, patch.object(self.app, 'close_for_update') as close:
            stage = self.ready()
            self.assertEqual(self.app.update_button.winfo_manager(), 'pack')
            self.assertEqual(str(self.app.update_button.cget('state')), 'normal')
            self.assertEqual(self.app.update_button.cget('text'), 'GÜNCELLEME VAR')
            self.assertEqual(self.app._update_stage, stage)
            install.assert_not_called()
            close.assert_not_called()
            self.assertTrue(self.engine.enabled_event.is_set())

    def test_click_stops_running_macros_saves_and_restarts_only_once(self):
        self.start()
        stage = self.ready()
        with patch('kodlar.gui.schedule_install') as install, patch.object(self.app, 'close_for_update') as close, \
                patch.object(self.app, 'save_current_configs_to_profiles', wraps=self.app.save_current_configs_to_profiles) as save:
            self.app.update_button.invoke()
            self.app.request_update_install()
            self.assertFalse(self.engine.enabled_event.is_set())
            self.assertEqual(install.call_args.args[0], stage)
            install.assert_called_once()
            save.assert_called_once_with(update_workers=False)
            close.assert_called_once()

    def test_click_while_downloading_installs_when_ready(self):
        self.app._update_monitor = Mock()
        self.app.log_queue.put(('update_available', '9.0.0'))
        self.process_queue_now()
        with patch('kodlar.gui.schedule_install') as install, patch.object(self.app, 'close_for_update') as close:
            self.app.update_button.invoke()
            install.assert_not_called()
            self.app._update_monitor.request_check.assert_called_once_with(retry=True)
            self.app.log_queue.put(('update_ready', ('9.0.0', self.stage())))
            self.process_queue_now()
            install.assert_called_once()
            close.assert_called_once()

    def test_install_failure_retains_download_and_allows_retry(self):
        stage = self.ready()
        with patch('kodlar.gui.schedule_install', side_effect=OSError('cannot start helper')), \
                patch.object(self.app, 'close_for_update') as close:
            self.app.update_button.invoke()
            self.assertEqual(self.app._update_stage, stage)
            self.assertEqual(str(self.app.update_button.cget('state')), 'normal')
            self.assertFalse(self.app._update_requested)
            close.assert_not_called()


del Fixture
