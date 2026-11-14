from __future__ import annotations

import ctypes
import json
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pynput import keyboard

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

    def test_f8_selection_does_not_create_a_window_or_change_focus(self):
        app = ClickerApp.__new__(ClickerApp)
        app.clicker = Mock(is_running=False)
        app._pending_pixel_pick = None
        app.markers = {}
        app.input_bg, app.text_primary, app.accent_color = '#000000', '#ffffff', '#0000ff'
        app.root = Mock()
        app.log_queue = queue.Queue()
        button = Mock()
        config = KeyConfig('a', 1, 0)
        with patch('kodlar.gui.tk.Toplevel') as overlay:
            app.start_pixel_capture(config, button, Mock(), Mock())
            with patch('kodlar.gui.physical_cursor_position', return_value=(960, 540)):
                with patch('kodlar.gui.screen_bounds', return_value=(0, 0, 1920, 1080)):
                    with patch('kodlar.gui.get_pixel_color_win32', return_value='#123456') as read:
                        app.clicker.pixel_capture_callback('f8')
                        read.assert_called_once_with(960, 540)
            overlay.assert_not_called()
        kind, data = app.log_queue.get_nowait()
        self.assertEqual(kind, 'log')
        kind, data = app.log_queue.get_nowait()
        self.assertEqual(kind, 'pixel_pick_result')
        self.assertEqual(data[1:], (960, 540, '#123456', (0, 0, 1920, 1080)))
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

    def test_capture_f8_is_suppressed_only_while_selecting(self):
        with patch('kodlar.engine.Controller'), patch('kodlar.engine.keyboard.Controller'):
            engine = RandomizedAutoClicker(AppConfig())
        listener = Mock()
        engine._keyboard_listener = listener
        engine.pixel_capture_callback = Mock()
        data = SimpleNamespace(vkCode=0x77)
        self.assertFalse(engine.filter_capture_hotkey(0x0100, data))
        self.assertFalse(engine.filter_capture_hotkey(0x0101, data))
        self.assertEqual(listener.suppress_event.call_count, 2)
        self.assertTrue(engine.filter_capture_hotkey(0x0100, data))
        self.assertEqual(listener.suppress_event.call_count, 2)
        engine.stop()

    def test_f8_is_one_shot_and_does_not_toggle_engine(self):
        with patch('kodlar.engine.Controller'), patch('kodlar.engine.keyboard.Controller'):
            engine = RandomizedAutoClicker(AppConfig(panic_key='f8'))
        callback = Mock()
        engine.pixel_capture_callback = callback
        engine.on_key_press(keyboard.Key.f8)
        callback.assert_called_once_with('f8')
        self.assertIsNone(engine.pixel_capture_callback)
        self.assertFalse(engine.is_running)
        engine.on_key_press(keyboard.Key.f8)  # OS key repeat must not start a macro.
        callback.assert_called_once()
        self.assertFalse(engine.is_running)
        engine.on_key_release(keyboard.Key.f8)
        engine.stop()


if __name__ == '__main__':
    unittest.main()
