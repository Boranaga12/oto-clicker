from __future__ import annotations

import os
import gc
import tempfile
import tkinter as tk
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from pynput.mouse import Button

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
        # Repeated Tk interpreters in this test process must be collected on the
        # UI thread, before a later sequence thread can trigger cyclic GC.
        self.app = self.engine = self.root = None
        gc.collect()

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

    def test_log_mouse_drag_selection_and_native_copy_keep_focus(self):
        self.start()
        self.app.clear_console_logs()
        self.app.append_log_to_widget('ABCDEFGH')
        self.root.focus_force()
        self.root.update()
        text = self.app.log_text
        start = text.bbox('1.1')
        finish = text.bbox('1.6')
        self.assertIsNotNone(start)
        self.assertIsNotNone(finish)
        x, y = start[0] + 1, start[1] + start[3] // 2
        end_x = finish[0] + 1
        text.event_generate('<ButtonPress-1>', x=x, y=y)
        text.event_generate('<B1-Motion>', x=end_x, y=y)
        text.event_generate('<ButtonRelease-1>', x=end_x, y=y)
        self.root.update()
        self.assertIs(self.root.focus_get(), text)
        self.assertTrue(text.tag_ranges('sel'))
        selected = text.get('sel.first', 'sel.last')
        self.assertGreaterEqual(len(selected), 3)
        text.event_generate('<<Copy>>')
        self.root.update()
        self.assertEqual(self.root.clipboard_get(), selected)
        original = text.get('1.0', 'end')
        self.app.append_log_to_widget('new log during selection')
        self.assertEqual(text.get('1.0', 'end'), original)
        self.assertEqual(text.get('sel.first', 'sel.last'), selected)
        text.tag_remove('sel', '1.0', 'end')
        self.app.end_log_selection(None)
        self.assertIn('new log during selection', text.get('1.0', 'end'))
        self.assertEqual(str(text.cget('state')), 'disabled')

    def test_live_pixel_preview_changes_point_and_swatch_without_saving_reference(self):
        self.config.target_color = '#123456'
        self.app.refresh_keys_list_ui()
        self.app.save_current_configs_to_profiles()
        original_file = (data_directory() / 'profiles.json').read_bytes()
        original = deepcopy(self.config)
        widgets = self.app.config_widgets[id(self.config)]
        with patch('kodlar.gui.physical_cursor_position', return_value=(600, 400)) as pointer:
            with patch('kodlar.gui.get_pixel_color_win32', return_value='#abcdef') as read, \
                 patch('kodlar.gui.SelectionMagnifier.show_point', side_effect=lambda *_: read.return_value):
                self.app.start_pixel_capture(self.config, widgets['pixel_btn'], widgets['coord_lbl'], widgets['color_preview'])
                self.root.update()
                preview = self.app._selection_preview
                self.assertEqual(preview.point, (592, 392))
                self.assertEqual(preview.color, '#abcdef')
                self.assertEqual(widgets['color_preview'].cget('bg'), '#abcdef')
                pointer.return_value = (640, 430)
                read.return_value = '#ff2200'
                self.root.after_cancel(self.app._preview_job)
                self.app.update_point_preview()
                self.assertEqual(preview.point, (632, 422))
                self.assertEqual(preview.color, '#ff2200')
                self.assertEqual(self.config, original)
                self.assertEqual((data_directory() / 'profiles.json').read_bytes(), original_file)
                self.app.cancel_pixel_pick()
                self.assertFalse(preview.winfo_exists())
                self.assertEqual(widgets['color_preview'].cget('bg'), '#123456')
                self.assertIsNone(self.app._preview_job)

    def test_click_target_preview_is_exact_and_does_not_replace_watch_reference(self):
        self.config.key = 'sol klik'
        self.config.target_color = '#112233'
        self.app.refresh_keys_list_ui()
        widgets = self.app.config_widgets[id(self.config)]
        with patch('kodlar.gui.physical_cursor_position', return_value=(600, 400)):
            with patch('kodlar.gui.get_pixel_color_win32', return_value='#bb9900'), \
                 patch('kodlar.gui.SelectionMagnifier.show_point', return_value='#bb9900'):
                self.app.start_click_capture(self.config, widgets['loc_btn'], widgets['loc_lbl'])
                self.root.update()
                self.assertEqual(self.app._selection_preview.point, (600, 400))
                self.assertEqual(widgets['color_preview'].cget('bg'), '#bb9900')
                with patch('kodlar.gui.foreground_is_ours', return_value=False):
                    self.engine.on_mouse_click(600, 400, Button.left, True)
                    self.engine.on_mouse_click(600, 400, Button.left, False)
                    self.process_queue_now()
        self.assertEqual((self.config.click_x, self.config.click_y), (600, 400))
        self.assertEqual(self.config.target_color, '#112233')
        self.assertEqual(widgets['color_preview'].cget('bg'), '#112233')
        self.assertIsNone(self.app._selection_preview)

    def test_marker_centers_and_nearby_sample_points_stay_transparent(self):
        from kodlar.ui_widgets import PointMarker
        marker = PointMarker(self.root, 300, 300, '#ff0000', protected_points=((300, 300), (304, 300)))
        try:
            rectangles = [marker.canvas.coords(item) for item in marker.canvas.find_all()
                          if marker.canvas.type(item) == 'rectangle' and marker.canvas.itemcget(item, 'fill') == PointMarker.TRANSPARENT]
            for x, y in ((4, 4), (8, 4)):
                self.assertTrue(any(left <= x < right and top <= y < bottom for left, top, right, bottom in rectangles))
        finally:
            marker.destroy()

    def test_saved_markers_remain_visible_when_running(self):
        self.config.key = 'sol klik'
        self.config.target_color = '#123456'
        self.config.pixel_x, self.config.pixel_y = 300, 300
        self.config.click_x, self.config.click_y = 400, 300
        self.app.refresh_keys_list_ui()
        self.root.update()
        markers = list(self.app.markers.values())
        self.assertEqual(len(markers), 2)
        self.start()
        self.assertTrue(all(marker.winfo_viewable() for marker in markers))
        self.assertEqual(set(self.app.markers.values()), set(markers))

    def test_click_captures_offset_game_point_and_display_mode(self):
        widgets = self.app.config_widgets[id(self.config)]
        self.app.start_pixel_capture(self.config, widgets['pixel_btn'], widgets['coord_lbl'], widgets['color_preview'])
        self.assertIsNone(self.app._capture_overlay)
        with patch('kodlar.gui.screen_bounds', return_value=(0, 0, 1920, 1080)):
            with patch('kodlar.gui.get_pixel_color_win32', return_value='#123456') as read:
                with patch('kodlar.gui.foreground_is_ours', return_value=False):
                    self.engine.on_mouse_click(1200, 700, Button.left, True)
                    self.engine.on_mouse_click(1200, 700, Button.left, False)
                    self.process_queue_now()
                    read.assert_called_once_with(1192, 692)
        self.assertEqual((self.config.pixel_x, self.config.pixel_y), (1192, 692))
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
