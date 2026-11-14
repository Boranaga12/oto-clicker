from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import Mock, patch

from pynput.mouse import Button

from kodlar.models import KeyConfig
from kodlar.workers import KeyClickerWorker


class WorkerTests(unittest.TestCase):
    def worker(self, **settings):
        config = KeyConfig('sol klik', 0, 0, **settings)
        engine = Mock()
        engine.enabled_event = threading.Event()
        engine.enabled_event.set()
        engine.input_lock = threading.RLock()
        engine.mute_all_keys_until = 0
        worker = KeyClickerWorker(config, Mock(), engine)
        return worker, engine

    def test_target_move_settles_before_press_and_restores_on_release_error(self):
        worker, engine = self.worker(click_x=100, click_y=200)
        trace = []

        class Mouse:
            position = (10, 20)

            def press(self, button):
                trace.append(('press', button, self.position))

            def release(self, button):
                trace.append(('release', button))
                raise OSError('release failed')

        engine.mouse = Mouse()
        worker.wait = lambda seconds: trace.append(('wait', seconds)) or False
        worker.press_key()
        self.assertEqual(trace[0], ('wait', 0.03))
        self.assertEqual(trace[1], ('press', Button.left, (100, 200)))
        self.assertGreaterEqual(trace[2][1], 0.06)
        self.assertEqual(engine.mouse.position, (10, 20))
        engine.log_activity.assert_called_once()

    def test_target_cursor_stays_until_button_up_can_be_processed(self):
        worker, engine = self.worker(click_x=100, click_y=200)
        trace = []

        class Mouse:
            position = (10, 20)

            def press(self, button):
                trace.append(('down', self.position))

            def release(self, button):
                trace.append(('up', self.position))

        engine.mouse = Mouse()
        worker.wait = lambda seconds: trace.append(('wait', seconds, engine.mouse.position)) or False
        self.assertTrue(worker.press_key())
        self.assertEqual(trace[-2], ('up', (100, 200)))
        self.assertEqual(trace[-1], ('wait', 0.05, (100, 200)))
        self.assertEqual(engine.mouse.position, (10, 20))

    def run_colors(self, colors, **settings):
        worker, engine = self.worker(screen_mode=True, target_color='#ffffff', **settings)
        pixels = Mock()
        values = iter(colors)

        def sample(*args):
            try:
                return next(values)
            except StopIteration:
                worker.stop()
                return ''

        pixels.get.side_effect = sample
        worker.wait = lambda seconds: worker.stop_event.is_set()
        worker.press_key = Mock()
        worker._interruptible_delay = Mock(return_value=True)
        worker._run_screen_mode(pixels)
        return worker

    def test_different_color_repeats_without_reference_return(self):
        worker = self.run_colors(['#000000'] * 6)
        self.assertEqual(worker.press_key.call_count, 3)

    def test_repeated_presses_enforce_left_click_minimum_at_runtime(self):
        worker, engine = self.worker(screen_mode=True, target_color='#ffffff')
        worker.config.interval_seconds = 0.02
        pixels = Mock()
        pixels.get.return_value = '#000000'
        pressed = []

        def press(before_press):
            self.assertTrue(before_press())
            pressed.append(time.monotonic())
            if len(pressed) == 3:
                worker.stop()
            return True

        worker.press_key = press
        worker._run_screen_mode(pixels)
        self.assertEqual(len(pressed), 3)
        self.assertTrue(all(b - a >= 0.049 for a, b in zip(pressed, pressed[1:])))

    def test_recovery_during_cursor_settle_cancels_mouse_down(self):
        worker, engine = self.worker(click_x=100, click_y=200)
        engine.mouse.position = (10, 20)
        worker.wait = Mock(return_value=False)
        allowed = Mock(side_effect=[True, False])
        self.assertFalse(worker.press_key(before_press=allowed))
        engine.mouse.press.assert_not_called()
        engine.mouse.release.assert_not_called()
        self.assertEqual(engine.mouse.position, (10, 20))

    def test_recovery_while_waiting_for_input_lock_cancels_press(self):
        worker, engine = self.worker()
        allowed = Mock(return_value=False)
        self.assertFalse(worker.press_key(before_press=allowed))
        engine.mouse.press.assert_not_called()

    def test_reference_return_at_deadline_cancels_click(self):
        worker = self.run_colors(['#000000', '#ffffff'])
        worker.press_key.assert_not_called()

    def test_failed_pixel_read_at_deadline_cancels_click(self):
        worker = self.run_colors(['#000000', ''])
        worker.press_key.assert_not_called()

    def test_legacy_invert_flag_cannot_press_when_reference_matches(self):
        worker = self.run_colors(['#ffffff', '#ffffff'], invert_color=True)
        worker.press_key.assert_not_called()
        worker = self.run_colors(['#000000', '#000000'], invert_color=True)
        worker.press_key.assert_called_once()

    def test_single_rgb_step_is_a_different_color(self):
        worker = self.run_colors(['#fffffe', '#fffffe', '#ffffff'])
        worker.press_key.assert_called_once()

    def test_new_pixel_selection_cancels_pending_press_for_old_target(self):
        worker, engine = self.worker(screen_mode=True, target_color='#ffffff')
        pixels = Mock()
        pixels.get.return_value = '#000000'
        def change_target(*args):
            worker.config.target_color = '#000000'
            return True
        worker._interruptible_delay = change_target
        worker.press_key = Mock()
        def finish(seconds):
            worker.stop()
            return True
        worker.wait = finish
        worker._run_screen_mode(pixels)
        worker.press_key.assert_not_called()


class TimingEditorTests(unittest.TestCase):
    def test_small_left_click_intervals_are_replaced_without_a_message(self):
        from kodlar.gui import ClickerApp
        for value in ('0', '0.001', '0,049', '-1'):
            with self.subTest(value=value):
                app = ClickerApp.__new__(ClickerApp)
                app.clicker = Mock()
                app.save_current_configs_to_profiles = Mock()
                entry = Mock()
                entry.get.return_value = value
                config = KeyConfig('sol klik', 1, 0)
                app.auto_save_timing(config, entry, 'interval')
                self.assertEqual(config.interval_seconds, 0.050)
                entry.insert.assert_called_once_with(0, '0.050')
                app.clicker.log.assert_not_called()
                app.save_current_configs_to_profiles.assert_called_once()


class CaptureTests(unittest.TestCase):
    def test_failed_capture_keeps_previous_target(self):
        import queue
        from kodlar.gui import ClickerApp

        app = ClickerApp.__new__(ClickerApp)
        app.input_bg = "#000000"
        app.text_primary = "#ffffff"
        app.root = Mock()
        app.clicker = Mock()
        app.log_queue = queue.Queue()
        app.markers = {}
        config = KeyConfig('a', 1, 0, target_color='#123456')
        overlay = Mock()
        overlay._click_count = 1
        button = Mock()
        event = Mock(x_root=100, y_root=200)
        with patch('kodlar.gui.get_pixel_color_win32', return_value='') as read:
            app.on_overlay_clicked(event, overlay, config, button, Mock(), Mock())
            overlay.destroy.assert_called_once()
            read.assert_called_once_with(100, 200)
        self.assertEqual(config.target_color, '#123456')
        self.assertTrue(app.log_queue.empty())

    def test_single_click_samples_uncovered_pixel_and_keeps_each_keys_reference(self):
        import queue
        from kodlar.gui import ClickerApp
        app = ClickerApp.__new__(ClickerApp)
        app.root = Mock()
        app.input_bg = '#000000'
        app.text_primary = '#ffffff'
        app.clicker = Mock()
        app.markers = {'marker': Mock()}
        app._shutting_down = False
        app.log_queue = queue.Queue()
        app.save_current_configs_to_profiles = Mock()
        app.draw_markers = Mock()
        app.apply_pending_update = Mock()
        first, second = KeyConfig('a', 1, 0), KeyConfig('b', 1, 0)
        trace = []
        overlay = Mock()
        overlay.withdraw.side_effect = lambda: trace.append('hidden')
        with patch('kodlar.gui.flush_desktop', side_effect=lambda: trace.append('flushed')):
            with patch('kodlar.gui.get_pixel_color_win32', side_effect=['#123456', '#abcdef']) as read:
                app.on_overlay_clicked(Mock(x_root=10, y_root=20), overlay, first, Mock(), Mock(), Mock())
                app.on_overlay_clicked(Mock(x_root=30, y_root=40), Mock(), second, Mock(), Mock(), Mock())
                app.process_queue()
        self.assertEqual(trace[:2], ['hidden', 'flushed'])
        self.assertEqual((first.pixel_x, first.pixel_y, first.target_color), (10, 20, '#123456'))
        self.assertEqual((second.pixel_x, second.pixel_y, second.target_color), (30, 40, '#abcdef'))
        self.assertEqual(read.call_count, 2)
        app.clicker.mouse.click.assert_not_called()
        app.markers['marker'].withdraw.assert_called()

    def test_running_engine_removes_editing_markers(self):
        from kodlar.gui import ClickerApp

        app = ClickerApp.__new__(ClickerApp)
        marker = Mock()
        app.markers = {'screen': marker}
        app.clicker = Mock(is_running=True)
        app.draw_markers()
        marker.destroy.assert_called_once()
        self.assertEqual(app.markers, {})


if __name__ == '__main__':
    unittest.main()
