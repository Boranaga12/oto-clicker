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

    def test_group_runs_one_press_per_turn_without_background_workers_or_saved_changes(self):
        first = KeyConfig('a', 0.001, 0, enabled=True)
        later = KeyConfig('b', 0.001, 0, enabled=True)
        before = deepcopy([first, later])
        group = SequenceGroup(children=[SequenceItem('macro', macro_id=first.id_token), SequenceItem('macro', macro_id=later.id_token)])
        finished = threading.Event()
        calls, states = [], []
        def pressed(key):
            calls.append(key)
            states.append([self.engine.is_config_enabled(first), self.engine.is_config_enabled(later)])
            if len(calls) == 4:
                finished.set()
        self.engine.keyboard.press.side_effect = pressed
        self.engine.persist_callback = Mock()
        self.engine.configure([first, later], sequence_groups=[group])
        self.assertEqual(self.engine.key_workers, [])
        self.assertFalse(any(worker.is_alive() for worker in self.engine._group_workers.values()))
        self.engine.set_enabled(True)
        self.assertTrue(finished.wait(2))
        self.engine.set_enabled(False)
        self.assertEqual(calls[:4], ['a', 'b', 'a', 'b'])
        self.assertTrue(all(sum(state) == 1 for state in states))
        self.assertEqual([first, later], before)
        self.engine.persist_callback.assert_not_called()

    def test_group_skips_matching_monitored_key_and_resumes_it_after_color_changes(self):
        first = KeyConfig('a', 0.001, 0, enabled=True, screen_mode=True, target_color='#ffffff')
        second = KeyConfig('b', 0.001, 0, enabled=True)
        group = SequenceGroup(children=[SequenceItem('macro', macro_id=first.id_token), SequenceItem('macro', macro_id=second.id_token)])
        calls = []
        matching_turns, changed_turn = threading.Event(), threading.Event()
        def pressed(key):
            calls.append(key)
            if calls.count('b') >= 2: matching_turns.set()
            if key == 'a': changed_turn.set()
        self.engine.keyboard.press.side_effect = pressed
        with patch('kodlar.workers.PixelSampler') as sampler:
            pixels = sampler.return_value.__enter__.return_value
            pixels.get.return_value = '#ffffff'
            self.engine.configure([first, second], sequence_groups=[group])
            self.engine.set_enabled(True)
            self.assertTrue(matching_turns.wait(2))
            self.assertNotIn('a', calls)
            pixels.get.return_value = '#000000'
            self.assertTrue(changed_turn.wait(2))
            self.engine.set_enabled(False)
        self.assertEqual(calls[:2], ['b', 'b'])

    def test_group_releases_mouse_before_pressing_next_key(self):
        mouse = KeyConfig('sol klik', 0.05, 0, enabled=True, click_x=600, click_y=400)
        key = KeyConfig('b', 0.001, 0, enabled=True)
        group = SequenceGroup(children=[SequenceItem('macro', macro_id=mouse.id_token), SequenceItem('macro', macro_id=key.id_token)])
        calls, finished = [], threading.Event()
        self.engine.mouse.position = (10, 20)
        self.engine.mouse.press.side_effect = lambda _button: calls.append('mouse-down')
        self.engine.mouse.release.side_effect = lambda _button: calls.append('mouse-up')
        self.engine.keyboard.press.side_effect = lambda _key: (calls.append('b'), finished.set())
        self.engine.configure([mouse, key], sequence_groups=[group])
        self.engine.set_enabled(True)
        self.assertTrue(finished.wait(2))
        self.engine.set_enabled(False)
        self.assertEqual(calls[:3], ['mouse-down', 'mouse-up', 'b'])
        self.assertEqual(self.engine.mouse.position, (10, 20))

    def test_automatic_group_delay_uses_key_interval_and_randomization(self):
        config = KeyConfig('sol klik', 0.01, 0.2)
        self.engine.key_configs = [config]
        with patch('kodlar.engine.random.uniform', return_value=0.12) as random:
            self.assertAlmostEqual(self.engine.macro_delay(config.id_token), 0.17)
            random.assert_called_once_with(0.0, 0.2)

    def test_disabled_group_step_is_skipped_without_changing_settings(self):
        config = KeyConfig('a', 1, 0, enabled=False)
        self.engine.key_configs = [config]
        worker = Mock(config=config)
        self.engine._group_workers = {config.id_token: worker}
        self.engine.set_enabled(True)
        self.assertFalse(self.engine.execute_group_step(config.id_token, threading.Event()))
        worker.press_once.assert_not_called()
        self.assertFalse(config.enabled)

    def test_late_runtime_activation_cannot_modify_saved_settings_after_stop(self):
        config = KeyConfig('a', 1, 0, enabled=False)
        self.engine.key_configs = [config]
        self.assertFalse(self.engine._activate_macro_by_id(config.id_token))
        self.assertFalse(self.engine.set_config_enabled(config, True, runtime_only=True))
        self.assertFalse(config.enabled)

    def test_running_stop_hotkey_ignores_a_stale_picker_callback(self):
        self.engine.set_enabled(True)
        callback = Mock()
        self.engine.pixel_capture_callback = callback
        self.engine.capturing_callback = callback
        self.engine.on_key_press(keyboard.Key.esc)
        self.assertFalse(self.engine.is_running)
        callback.assert_not_called()
        self.assertIsNone(self.engine.pixel_capture_callback)

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

    def test_every_sent_group_key_is_logged_and_published_without_throttling(self):
        config = KeyConfig('f1', 1, 0)
        self.engine.key_configs = [config]
        self.engine.sequence_groups = [SequenceGroup(name='Saldırı', children=[SequenceItem('macro', macro_id=config.id_token)])]
        self.engine.position_controller.profile = 'Karos'
        self.engine.input_callback = Mock()
        with patch.object(self.engine, 'log') as log:
            self.engine.macro_input_sent(config)
            self.engine.macro_input_sent(config)
        self.assertEqual(log.call_args_list, [unittest.mock.call('Saldırı · F1')]*2)
        self.assertEqual(self.engine.input_callback.call_args_list, [unittest.mock.call('Karos', config.id_token)]*2)

    def test_state_change_logs_only_its_reason(self):
        with patch.object(self.engine, 'log') as log:
            self.engine._publish_state(True, 'Sistem aktif edildi.')
            self.engine._publish_state(False, 'Sistem durduruldu.')
        self.assertEqual(log.call_args_list, [unittest.mock.call('Sistem aktif edildi.'),
                                              unittest.mock.call('Sistem durduruldu.')])

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
