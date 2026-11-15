from __future__ import annotations

import threading
import unittest
from unittest.mock import Mock, patch

from kodlar.models import KeyConfig
from kodlar.workers import KeyClickerWorker
from kodlar.tests.test_engine import EngineTests as EngineFixture


class MacroBehaviourTests(unittest.TestCase):
    setUp = EngineFixture.setUp
    tearDown = EngineFixture.tearDown

    def test_toggle_macro_reverses_color_condition_and_stops_after_release(self):
        config = KeyConfig(self.engine.app_config.panic_key, 1, 0, screen_mode=True,
                           target_color='#ffffff')
        worker = KeyClickerWorker(config, self.engine.keyboard, self.engine)
        self.assertTrue(worker.color_allows('#ffffff', config.target_color))
        self.assertFalse(worker.color_allows('#000000', config.target_color))
        self.assertFalse(worker.color_allows('', config.target_color))
        trace = []
        self.engine.keyboard.release.side_effect = lambda _key: trace.append(self.engine.is_running)
        self.engine.set_enabled(True)
        worker.wait = Mock(return_value=False)
        self.assertTrue(worker.press_key())
        self.assertEqual(trace, [True])
        self.assertFalse(self.engine.is_running)
        self.assertFalse(self.engine.manual_enabled)

    def test_regular_macro_retains_different_color_condition(self):
        config = KeyConfig('tab', 1, 0)
        worker = KeyClickerWorker(config, self.engine.keyboard, self.engine)
        self.assertFalse(worker.color_allows('#ffffff', '#ffffff'))
        self.assertTrue(worker.color_allows('#000000', '#ffffff'))

    def test_tab_timeout_excludes_writing_and_movement_pause(self):
        timer = self.engine.tab_watchdog
        gate = self.engine.writing_gate
        config = KeyConfig('tab', 1, 0, screen_mode=True, target_color='#ffffff')
        now = [100.0]
        with patch('kodlar.writing.time.monotonic', side_effect=lambda: now[0]):
            timer.start_session()
            now[0] = 104
            self.assertTrue(timer.due(config))
            timer.record(config)
            self.assertFalse(timer.due(config))
            gate.set_position_blocked(True)
            now[0] = 160
            self.assertFalse(timer.due(config))
            gate.set_position_blocked(False)
            gate.owner = -1
            gate.clock()
            now[0] = 200
            self.assertFalse(timer.due(config))
            gate.owner = None
            gate.clock()
            now[0] = 204
            self.assertTrue(timer.due(config))

    def test_grouped_tab_can_fallback_without_changing_saved_active_preference(self):
        config = KeyConfig('tab', 1, 0, screen_mode=True, target_color='#ffffff')
        worker = KeyClickerWorker(config, self.engine.keyboard, self.engine)
        self.engine.set_enabled(True)
        self.engine._runtime_enabled[config.id_token] = False
        self.assertFalse(worker._can_run())
        worker.watchdog_owner = threading.get_ident()
        self.assertTrue(worker._can_run())
        self.assertTrue(config.enabled)
        self.assertFalse(self.engine._runtime_enabled[config.id_token])


del EngineFixture
