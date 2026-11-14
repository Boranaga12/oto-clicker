from __future__ import annotations

import threading
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
        worker._run_screen_mode(pixels)
        return worker

    def test_color_change_fires_once_until_reference_returns(self):
        worker = self.run_colors([
            '#000000', '#000000',  # change and final check -> fire
            '#000000', '#ffffff',  # still changed, then rearm
            '#000000', '#000000',  # next change -> fire
        ])
        self.assertEqual(worker.press_key.call_count, 2)

    def test_reference_return_at_deadline_cancels_click(self):
        worker = self.run_colors(['#000000', '#ffffff'])
        worker.press_key.assert_not_called()

    def test_failed_pixel_read_at_deadline_cancels_click(self):
        worker = self.run_colors(['#000000', ''])
        worker.press_key.assert_not_called()

    def test_inverted_condition_triggers_when_color_matches(self):
        worker = self.run_colors(['#ffffff', '#ffffff'], invert_color=True)
        worker.press_key.assert_called_once()


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
        config = KeyConfig('a', 1, 0, target_color='#123456')
        overlay = Mock()
        overlay._click_count = 1
        button = Mock()
        event = Mock(x_root=100, y_root=200)
        with patch('kodlar.gui.get_pixel_color_win32', return_value='') as read:
            app.on_overlay_clicked(event, overlay, config, button, Mock(), Mock())
            overlay.destroy.assert_called_once()
            read.assert_not_called()
            app.root.after.call_args.args[1]()
        self.assertEqual(config.target_color, '#123456')
        self.assertTrue(app.log_queue.empty())

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
