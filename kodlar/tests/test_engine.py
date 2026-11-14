from __future__ import annotations

import unittest
import threading
from copy import deepcopy
from unittest.mock import Mock, patch

from pynput import keyboard
from pynput.mouse import Button

from kodlar.config import AppConfig
from kodlar.engine import RandomizedAutoClicker
from kodlar.models import KeyConfig
from kodlar.sequences import SequenceGroup, SequenceItem


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

    def test_global_start_launches_all_root_groups_and_resets_grouped_macros(self):
        first = KeyConfig('a', 1, 0)
        later = KeyConfig('b', 1, 0)
        independent = KeyConfig('c', 1, 0)
        nested = SequenceGroup(children=[SequenceItem(kind='macro', macro_id=later.id_token)])
        root = SequenceGroup(children=[
            SequenceItem(kind='macro', macro_id=first.id_token),
            SequenceItem(kind='group', group=nested, delay_seconds=1),
        ])
        other = SequenceGroup(children=[SequenceItem(kind='macro', macro_id='other')])
        self.engine.key_configs = [first, later, independent]
        self.engine.sequence_groups = [root, other]
        with patch.object(self.engine.sequence_runner, 'start_group') as start:
            self.engine.set_enabled(True)
            self.engine.set_enabled(True)
            self.assertEqual([call.args[0] for call in start.call_args_list],
                             [root.id_token, other.id_token])
            self.assertTrue(first.enabled)
            self.assertTrue(later.enabled)
            self.assertFalse(self.engine.is_config_enabled(first))
            self.assertFalse(self.engine.is_config_enabled(later))
            self.assertTrue(independent.enabled)
            self.engine.set_enabled(False)
            self.engine.set_enabled(True)
            self.assertEqual(start.call_count, 4)

    def test_group_sequence_only_changes_runtime_not_saved_configurations(self):
        first = KeyConfig('a', 0.2, 0.01, enabled=False)
        later = KeyConfig('b', 0.3, 0.02, enabled=True)
        before = deepcopy([first, later])
        group = SequenceGroup(children=[
            SequenceItem(kind='macro', macro_id=first.id_token),
            SequenceItem(kind='macro', macro_id=later.id_token, delay_seconds=0.02),
        ])
        finished = threading.Event()
        self.engine.sequence_state_callback = lambda token, active: finished.set() if not active else None
        self.engine.persist_callback = Mock()
        with patch('kodlar.engine.KeyClickerWorker', DummyWorker):
            self.engine.configure([first, later], sequence_groups=[group])
            self.engine.set_enabled(True)
            self.assertTrue(finished.wait(1))
            self.assertTrue(self.engine.is_config_enabled(first))
            self.assertTrue(self.engine.is_config_enabled(later))
            self.assertEqual([first, later], before)
            self.engine.persist_callback.assert_not_called()
            self.engine.set_enabled(False)
            self.assertEqual([first, later], before)
            self.assertFalse(self.engine.is_config_enabled(first))

    def test_late_runtime_activation_cannot_modify_saved_settings_after_stop(self):
        config = KeyConfig('a', 1, 0, enabled=False)
        self.engine.key_configs = [config]
        self.assertFalse(self.engine._activate_macro_by_id(config.id_token))
        self.assertFalse(self.engine.set_config_enabled(config, True, runtime_only=True))
        self.assertFalse(config.enabled)

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
