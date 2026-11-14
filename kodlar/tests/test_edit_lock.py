from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from pynput import keyboard

from kodlar.app_paths import data_directory
from kodlar.config import AppConfig
from kodlar.engine import RandomizedAutoClicker
from kodlar.gui import ClickerApp
from kodlar.models import KeyConfig
from kodlar.sequences import SequenceGroup, SequenceItem


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'A desktop display is required')
class EditLockTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {'APPDATA': self.directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        workers = patch('kodlar.engine.KeyClickerWorker', side_effect=lambda *args: Mock(is_alive=Mock(return_value=False)))
        workers.start()
        self.addCleanup(workers.stop)
        self.root = tk.Tk()
        self.engine = RandomizedAutoClicker(AppConfig())
        self.app = ClickerApp(self.root, self.engine)
        self.config = KeyConfig('a', 0.2, 0.01, enabled=True)
        self.grouped = KeyConfig('b', 0.3, 0.02, enabled=False)
        self.group = SequenceGroup(children=[SequenceItem(kind='macro', macro_id=self.grouped.id_token)])
        self.app.key_configs = [self.config, self.grouped]
        self.app.sequence_groups = [self.group]
        self.app.save_current_configs_to_profiles(update_workers=True, update_sequences=True)
        self.app.refresh_keys_list_ui()
        self.root.update()
        self.addCleanup(self.close)

    def close(self):
        self.app.shutdown()
        self.engine.stop()
        self.root.destroy()

    def process_queue_now(self):
        if self.app._queue_job is not None:
            self.root.after_cancel(self.app._queue_job)
        self.app._queue_job = None
        self.app.process_queue()

    def start(self):
        self.engine.set_enabled(True)
        self.app.update_running_ui(True)
        self.root.update()

    def test_controls_lock_and_ignore_edits_then_unlock_without_config_changes(self):
        saved = deepcopy(self.app.key_configs)
        profile_file = data_directory() / 'profiles.json'
        original_bytes = profile_file.read_bytes()
        widgets = self.app.config_widgets[id(self.config)]
        widgets['int_entry'].delete(0, 'end')
        widgets['int_entry'].insert(0, '9')  # An unfinished edit must not be committed by a macro.
        self.start()
        self.assertEqual(widgets['int_entry'].get(), '0.200')
        for name in ('int_entry', 'rand_entry', 'key_btn', 'pixel_btn', 'loc_btn'):
            self.assertEqual(str(widgets[name].cget('state')), 'disabled')
        self.assertEqual(str(self.app.profile_menu.cget('state')), 'disabled')
        self.assertEqual(str(self.app.panic_btn.cget('state')), 'disabled')
        self.assertEqual(str(self.app.add_key_btn.cget('state')), 'disabled')
        self.assertEqual(str(self.app.status_badge.cget('state')), 'normal')
        widgets['int_entry'].insert(0, '5')
        widgets['key_btn'].invoke()
        self.app.add_key_btn.invoke()
        self.app.toggle_key_enabled(self.config, Mock(get=Mock(return_value=0)))
        self.app.toggle_screen_mode(self.config, Mock(get=Mock(return_value=1)))
        self.app.auto_save_timing(self.config, Mock(get=Mock(return_value='7')), 'interval')
        self.app.start_pixel_capture(self.config, Mock(), Mock(), Mock())
        self.app.log_queue.put(('pixel_capture', (self.config, 99, 99, '#123456', Mock(), Mock(), Mock())))
        self.process_queue_now()
        self.app.save_current_configs_to_profiles()
        self.assertEqual(self.app.key_configs, saved)
        self.assertEqual(profile_file.read_bytes(), original_bytes)
        self.assertIsNone(self.app.capturing_target)
        self.engine.set_enabled(False)
        self.app.update_running_ui(False)
        self.root.update()
        self.assertEqual(self.app.key_configs, saved)
        self.assertEqual(profile_file.read_bytes(), original_bytes)
        self.assertEqual(str(widgets['int_entry'].cget('state')), 'normal')
        self.assertEqual(str(self.app.profile_menu.cget('state')), 'normal')
        self.app.auto_save_timing(self.config, Mock(get=Mock(return_value='0.4')), 'interval')
        self.assertEqual(self.config.interval_seconds, 0.4)

    def test_f8_captures_physical_game_point_and_display_mode(self):
        widgets = self.app.config_widgets[id(self.config)]
        self.app.start_pixel_capture(self.config, widgets['pixel_btn'], widgets['coord_lbl'], widgets['color_preview'])
        self.assertIsNone(self.app._capture_overlay)
        with patch('kodlar.gui.physical_cursor_position', return_value=(1200, 700)):
            with patch('kodlar.gui.screen_bounds', return_value=(0, 0, 1920, 1080)):
                with patch('kodlar.gui.get_pixel_color_win32', return_value='#123456'):
                    with patch('kodlar.gui.foreground_is_ours', return_value=False):
                        self.engine.on_key_press(keyboard.Key.f8)
                        self.process_queue_now()
        self.assertEqual((self.config.pixel_x, self.config.pixel_y), (1200, 700))
        self.assertEqual(self.config.target_color, '#123456')
        self.assertEqual(self.config.pixel_screen_bounds, (0, 0, 1920, 1080))
        self.assertIsNone(self.app._pending_pixel_pick)

    def test_start_cancels_pending_key_and_pixel_capture(self):
        self.app.start_key_capture('key', self.config, self.app.config_widgets[id(self.config)]['key_btn'])
        overlay = tk.Toplevel(self.root)
        self.app._capture_overlay = overlay
        self.start()
        self.assertIsNone(self.app.capturing_target)
        self.assertIsNone(self.engine.capturing_callback)
        self.assertFalse(overlay.winfo_exists())
        self.app.handle_captured_key('z')
        self.assertEqual(self.config.key, 'a')


if __name__ == '__main__':
    unittest.main()
