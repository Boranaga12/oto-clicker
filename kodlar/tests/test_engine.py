from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from pynput import keyboard
from pynput.mouse import Button

from kodlar.config import AppConfig
from kodlar.engine import RandomizedAutoClicker
from kodlar.models import KeyConfig


class DummyWorker:
    def __init__(self, *args, **kwargs) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self, timeout=None) -> None:
        return None

    def is_alive(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "dummy-worker"


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        controller = patch("kodlar.engine.Controller", return_value=Mock())
        keyboard_controller = patch("kodlar.engine.keyboard.Controller", return_value=Mock())
        self.addCleanup(controller.stop)
        self.addCleanup(keyboard_controller.stop)
        controller.start()
        keyboard_controller.start()
        self.engine = RandomizedAutoClicker(AppConfig())

    def tearDown(self) -> None:
        self.engine.stop()

    def test_state_changes_are_published(self) -> None:
        states: list[bool] = []
        self.engine.state_callback = states.append
        with patch.object(self.engine, "update_key_workers"):
            self.engine.toggle_manual()
            self.engine.toggle_manual()
        self.assertEqual(states, [True, False])

    def test_disabled_configs_also_get_waiting_worker(self) -> None:
        configs = [
            KeyConfig("a", 1.0, 0.0, enabled=True),
            KeyConfig("b", 1.0, 0.0, enabled=False),
        ]
        with patch("kodlar.engine.KeyClickerWorker", DummyWorker):
            self.engine.update_key_workers(configs)
            self.assertEqual(len(self.engine.key_workers), 2)
            self.assertTrue(all(worker.started for worker in self.engine.key_workers))

    def test_activity_logging_is_throttled(self) -> None:
        with patch.object(self.engine, "log") as log:
            self.engine.log_activity("macro", "ilk")
            self.engine.log_activity("macro", "ikinci")
        log.assert_called_once_with("ilk")

    def test_injected_panic_key_does_not_toggle_engine(self) -> None:
        self.engine.mark_injected_key("esc")
        self.engine.on_key_press(keyboard.Key.esc)
        self.assertFalse(self.engine.is_running)

        self.engine.on_key_press(keyboard.Key.esc)
        self.assertTrue(self.engine.is_running)

    def test_injected_middle_click_does_not_toggle_engine(self) -> None:
        self.engine.mark_injected_mouse(Button.middle)
        self.engine.on_mouse_click(10, 10, Button.middle, True)
        self.assertFalse(self.engine.is_running)

        with patch.object(self.engine, "update_key_workers"):
            self.engine.on_mouse_click(10, 10, Button.middle, True)
        self.assertTrue(self.engine.is_running)

    def test_concurrent_identical_injected_keys_are_all_consumed(self) -> None:
        key = keyboard.KeyCode.from_char("x")
        self.engine.mark_injected_key("x")
        self.engine.mark_injected_key("x")
        self.engine.app_config.panic_key = "x"

        with patch.object(self.engine, "toggle_manual") as toggle:
            self.engine.on_key_press(key)
            self.engine.on_key_press(key)

        toggle.assert_not_called()

    def test_next_real_key_is_not_swallowed_after_injected_events(self) -> None:
        key = keyboard.KeyCode.from_char("x")
        self.engine.app_config.panic_key = "x"
        self.engine.mark_injected_key("x")

        with patch.object(self.engine, "toggle_manual") as toggle:
            self.engine.on_key_press(key)
            self.engine.on_key_press(key)

        toggle.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
