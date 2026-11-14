from __future__ import annotations

import ctypes
import json
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pynput import keyboard
from pynput.mouse import Button

from kodlar import platform_win
from kodlar.config import AppConfig
from kodlar.engine import RandomizedAutoClicker
from kodlar.gui import ClickerApp
from kodlar.models import KeyConfig, key_config_from_dict, key_config_to_dict
from kodlar.workers import KeyClickerWorker


class PhysicalCaptureTests(unittest.TestCase):
    def test_pixel_reader_refreshes_desktop_dc_on_every_read(self):
        user32 = Mock()
        user32.GetDC.side_effect = [101, 202]
        gdi32 = Mock()
        gdi32.GetPixel.side_effect = [0x332211, 0x665544]
        with patch.object(platform_win, 'os', SimpleNamespace(name='nt')):
            with patch.object(platform_win, '_user32', user32, create=True), patch.object(platform_win, '_gdi32', gdi32, create=True):
                with patch.object(platform_win, 'screen_bounds', return_value=(0, 0, 1920, 1080)):
                    with platform_win.PixelSampler() as pixels:
                        self.assertEqual(pixels.get(10, 20), '#112233')
                        self.assertEqual(pixels.get(10, 20), '#445566')
        self.assertEqual(user32.GetDC.call_count, 2)
        self.assertEqual([call.args[1] for call in user32.ReleaseDC.call_args_list], [101, 202])

    def test_pixel_outside_changed_resolution_is_not_read(self):
        user32 = Mock()
        with patch.object(platform_win, 'os', SimpleNamespace(name='nt')):
            with patch.object(platform_win, '_user32', user32, create=True):
                with patch.object(platform_win, 'screen_bounds', return_value=(0, 0, 1024, 768)):
                    self.assertEqual(platform_win.PixelSampler().get(1400, 900), '')
        user32.GetDC.assert_not_called()

    def test_dpi_v2_is_preferred_and_failed_hresult_uses_fallback(self):
        user32 = Mock()
        shcore = Mock()
        with patch.object(platform_win, 'os', SimpleNamespace(name='nt')):
            with patch.object(platform_win, '_user32', user32, create=True):
                with patch.object(platform_win.ctypes, 'windll', SimpleNamespace(shcore=shcore), create=True):
                    user32.SetProcessDpiAwarenessContext.return_value = True
                    platform_win.enable_dpi_awareness()
                    shcore.SetProcessDpiAwareness.assert_not_called()
                    self.assertEqual(user32.SetProcessDpiAwarenessContext.call_args.args[0].value, ctypes.c_void_p(-4).value)
                    user32.SetProcessDpiAwarenessContext.return_value = False
                    shcore.SetProcessDpiAwareness.return_value = -2147024891
                    platform_win.enable_dpi_awareness()
                    user32.SetProcessDPIAware.assert_called_once()

    def test_click_selection_offsets_sample_without_window_or_focus_change(self):
        app = ClickerApp.__new__(ClickerApp)
        app.clicker = Mock(is_running=False)
        app._pending_pixel_pick = None
        app.markers = {}
        app.config_widgets = {}
        app.input_bg, app.text_primary, app.accent_color = '#000000', '#ffffff', '#0000ff'
        app.root = Mock()
        app.log_queue = queue.Queue()
        button = Mock()
        config = KeyConfig('a', 1, 0)
        with patch('kodlar.gui.tk.Toplevel') as overlay:
            app.start_pixel_capture(config, button, Mock(), Mock())
            with patch('kodlar.gui.foreground_is_ours', return_value=False):
                with patch('kodlar.gui.screen_bounds', return_value=(0, 0, 1920, 1080)):
                    with patch('kodlar.gui.get_pixel_color_win32', return_value='#123456') as read:
                        app.clicker.pixel_capture_callback(960, 540)
                        kind, data = app.log_queue.get_nowait()
                        self.assertEqual(kind, 'pixel_pick_point')
                        app.sample_picked_pixel(*data)
                        read.assert_called_once_with(952, 532)
            overlay.assert_not_called()
        kind, data = app.log_queue.get_nowait()
        self.assertEqual(kind, 'pixel_pick_result')
        self.assertEqual(data[1:], (952, 532, '#123456', (0, 0, 1920, 1080)))
        app.root.focus_set.assert_not_called()

    def test_display_bounds_survive_json_roundtrip_and_negative_monitor_coordinates(self):
        config = KeyConfig('a', 1, 0, pixel_x=-1200, pixel_y=200, target_color='#123456', pixel_screen_bounds=(-1920, 0, 3840, 1080))
        self.assertTrue(config.has_pixel_target)
        restored = key_config_from_dict(json.loads(json.dumps(key_config_to_dict(config))))
        self.assertEqual(restored.pixel_screen_bounds, (-1920, 0, 3840, 1080))

    def test_changed_resolution_pauses_instead_of_pressing_wrong_pixel(self):
        config = KeyConfig('a', 1, 0, screen_mode=True, target_color='#ffffff', pixel_screen_bounds=(0, 0, 1920, 1080))
        engine = Mock()
        engine.mute_all_keys_until = 0
        worker = KeyClickerWorker(config, Mock(), engine)
        worker.wait = lambda seconds: worker.stop() or True
        worker.press_key = Mock()
        pixels = Mock()
        with patch('kodlar.workers.screen_bounds', return_value=(0, 0, 1024, 768)):
            worker._run_screen_mode(pixels)
        pixels.get.assert_not_called()
        worker.press_key.assert_not_called()

    def test_monitor_uses_saved_offset_point_without_shifting_it_again(self):
        config = KeyConfig('a', 1, 0, screen_mode=True, pixel_x=952, pixel_y=532, target_color='#123456')
        engine = Mock(mute_all_keys_until=0)
        worker = KeyClickerWorker(config, Mock(), engine)
        worker.wait = lambda seconds: worker.stop() or True
        worker.press_key = Mock()
        pixels = Mock()
        pixels.get.return_value = '#123456'
        worker._run_screen_mode(pixels)
        pixels.get.assert_called_once_with(952, 532)
        worker.press_key.assert_not_called()

    def test_markers_are_click_through_non_activating_and_excluded_from_capture(self):
        user32 = Mock()
        user32.GetAncestor.return_value = 123
        flags = 0x00080000 | 0x20 | 0x08000000 | 0x80
        user32.GetWindowLongPtrW.side_effect = [0, flags]
        with patch.object(platform_win, 'os', SimpleNamespace(name='nt')):
            with patch.object(platform_win, '_user32', user32, create=True):
                self.assertEqual(platform_win.make_overlay_passive(99), 123)
        self.assertEqual(user32.SetWindowLongPtrW.call_args.args, (123, -20, flags))
        user32.SetWindowDisplayAffinity.assert_called_once_with(123, 0x11)
        user32.SetForegroundWindow.assert_not_called()

    def test_click_capture_waits_for_release_and_is_one_shot(self):
        with patch('kodlar.engine.Controller'), patch('kodlar.engine.keyboard.Controller'):
            engine = RandomizedAutoClicker(AppConfig())
        callback = Mock()
        engine.pixel_capture_callback = callback
        engine.on_key_press(keyboard.Key.f8)
        callback.assert_not_called()
        engine.on_mouse_click(960, 540, Button.left, True)
        callback.assert_not_called()
        engine.on_mouse_click(961, 541, Button.left, False)
        callback.assert_called_once_with(960, 540)
        self.assertIsNone(engine.pixel_capture_callback)
        engine.on_mouse_click(960, 540, Button.left, False)
        callback.assert_called_once()
        self.assertFalse(engine.is_running)
        engine.stop()

    def test_escape_cancels_click_capture_without_starting_macro(self):
        with patch('kodlar.engine.Controller'), patch('kodlar.engine.keyboard.Controller'):
            engine = RandomizedAutoClicker(AppConfig())
        engine.pixel_capture_callback = Mock()
        cancel = engine.pixel_capture_cancel_callback = Mock()
        engine.on_key_press(keyboard.Key.esc)
        cancel.assert_called_once()
        self.assertIsNone(engine.pixel_capture_callback)
        self.assertFalse(engine.is_running)
        engine.stop()


if __name__ == '__main__':
    unittest.main()
