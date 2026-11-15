from __future__ import annotations

import base64
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from kodlar.coordinate_ocr import CoordinateOCR
from kodlar.position_model import PositionConfig, ReadingFilter, parse_coordinates
from kodlar.position_controller import PositionController, Steering
from kodlar.profile_store import _normalise
from kodlar.writing import WritingGate
from kodlar.config import AppConfig
from kodlar.engine import RandomizedAutoClicker
from kodlar.models import KeyConfig
from kodlar.sequences import SequenceGroup, SequenceItem, WritingBlock


class PositionModelTests(unittest.TestCase):
    def test_coordinates_require_two_numbers_with_decimal_points(self):
        self.assertEqual(parse_coordinates('67.6 77.5'), (67.6, 77.5))
        self.assertEqual(parse_coordinates('69.0 87.1'), (69.0, 87.1))
        for text in ('676 77.5', '67.6', '67.6 77.5 10.0', '67.6 77.5\n69.0 87.1'):
            self.assertIsNone(parse_coordinates(text))

    def test_migration_preserves_position_preferences(self):
        settings = PositionConfig(True, (1, 2, 90, 20), (0, 0, 1920, 1080), (67.6, 77.5))
        data = _normalise({'profiles': {'Karos': []}, 'positions': {'Karos': settings.to_dict()}})
        restored = PositionConfig.from_dict(data['positions']['Karos'])
        self.assertEqual(restored, settings)
        self.assertFalse(PositionConfig.from_dict(_normalise({'profiles': {'Old': []}})['positions']['Old']).enabled)

    def test_invalid_limits_and_region_cannot_enable_movement(self):
        config = PositionConfig.from_dict({'enabled': True, 'maximum': float('nan'),
                                          'minimum': -5, 'region': [0, 0, 900, 500]})
        self.assertEqual((config.maximum, config.minimum), (10, 2))
        self.assertFalse(config.enabled)

    def test_stationary_center_requires_three_readings_and_jumps_are_rejected(self):
        samples = ReadingFilter()
        for stamp in (1, 1.25, 1.5):
            self.assertTrue(samples.accept((67.6, 77.5), stamp))
        self.assertEqual(len(samples.stable), 3)
        self.assertFalse(samples.accept((176.6, 177.5), 1.75))
        self.assertEqual(samples.stable, [])

    def test_center_request_resets_previous_teleport_failure(self):
        controller = PositionController(SimpleNamespace(writing_gate=WritingGate()))
        controller.filter.accept((0, 0), time.monotonic())
        controller.failure = 'Konum değişti'
        controller.request_center()
        self.assertIsNone(controller.failure)
        self.assertTrue(controller.filter.accept((100, 100), time.monotonic()))
        self.assertEqual(len(controller.filter.stable), 1)

    def test_monitor_arrangement_is_persisted(self):
        config = PositionConfig(monitors=((-1920, 0, 0, 1080), (0, 0, 1920, 1080)))
        self.assertEqual(PositionConfig.from_dict(config.to_dict()).monitors, config.monitors)

    def test_turns_are_rotation_followed_by_forward_motion(self):
        steering = Steering()
        config = PositionConfig(center=(0, 0))
        self.assertEqual(steering.commands((12, 0), config)[0][0], 'w')
        steering.observe((12, 0), (13, 0), (0, 0))
        commands = steering.commands((13, 0), config)
        self.assertEqual([key for key, _ in commands], ['a', 'w'])
        steering.observe((13, 0), (13, 1), (0, 0), ('a', .08))
        self.assertIsNotNone(steering.a_rate)
        self.assertTrue(all(0 < duration <= .3 for _, duration in steering.commands((13, 1), config)))


class PositionPriorityTests(unittest.TestCase):
    def controller(self):
        engine = SimpleNamespace(writing_gate=WritingGate(), is_running=True,
            _writing_target=None, input_lock=threading.RLock(), keyboard=Mock(), mark_injected_key=Mock())
        controller = PositionController(engine)
        controller.config = PositionConfig(True, (1, 2, 90, 20), (0, 0, 1920, 1080), (0, 0))
        controller.generation = 1
        controller.gate.position_enabled = True
        controller.gate.position_valid_until = time.monotonic()+.75
        return controller

    def test_writing_end_keeps_normal_input_blocked_until_new_position(self):
        controller = self.controller()
        old = time.monotonic()
        with controller.gate.exclusive(lambda: False) as admitted:
            self.assertTrue(admitted)
            self.assertTrue(controller.gate.allowed())
        self.assertFalse(controller.gate.allowed())
        controller.allow_normal(1, old)
        self.assertFalse(controller.gate.allowed())
        epoch = controller.gate.position_epoch
        with patch('kodlar.position_controller.time.monotonic', return_value=epoch+.01):
            controller.allow_normal(1, epoch+.001)
        self.assertTrue(controller.gate.allowed())

    def test_stale_measurement_cannot_unblock_normal_macros(self):
        controller = self.controller()
        controller.gate.set_position_blocked(True)
        controller.allow_normal(1, time.monotonic()-1)
        self.assertFalse(controller.gate.allowed())

    def test_expired_measurement_closes_previously_open_gate(self):
        controller = self.controller()
        self.assertTrue(controller.gate.allowed())
        controller.gate.position_valid_until = time.monotonic()-1
        self.assertFalse(controller.gate.allowed())

    def test_stop_cancels_walking_without_releasing_unowned_keys(self):
        controller = self.controller()
        controller.engine.is_running = False
        self.assertFalse(controller.pulse('w', .12, 1, time.monotonic()))
        controller.engine.keyboard.press.assert_not_called()
        controller.engine.keyboard.release.assert_not_called()

    def test_failure_limits_keep_normal_macros_blocked(self):
        for reason in ('stationary', 'unproductive', 'timeout'):
            with self.subTest(reason=reason):
                controller = self.controller()
                controller.target = 100
                controller.pulse = Mock()
                if reason == 'timeout':
                    controller.spent = 20
                else:
                    setattr(controller.steering, reason, 3 if reason == 'stationary' else 8)
                with patch('kodlar.position_controller.foreground_window', return_value=100), \
                     patch('kodlar.position_controller.foreground_is_ours', return_value=False):
                    controller.evaluate((12, 0), time.monotonic(), 1)
                controller.pulse.assert_not_called()
                self.assertIsNotNone(controller.failure)
                self.assertFalse(controller.gate.allowed())

    def test_late_result_from_another_profile_cannot_unblock(self):
        controller = self.controller()
        controller.gate.set_position_blocked(True)
        controller.allow_normal(0, time.monotonic())
        self.assertFalse(controller.gate.allowed())

    def test_focus_loss_prevents_wasd_and_preserves_other_keys(self):
        controller = self.controller()
        controller.target = 100
        with patch('kodlar.position_controller.foreground_window', return_value=200):
            self.assertFalse(controller.pulse('w', .12, 1, time.monotonic()))
        controller.engine.keyboard.press.assert_not_called()
        controller.engine.keyboard.release.assert_not_called()

    def test_writer_request_cancels_walk_and_only_owned_key_is_released(self):
        controller = self.controller()
        controller.target = 100
        stop = threading.Event()
        pressed = threading.Event()
        entered = threading.Event()
        controller.engine.keyboard.press.side_effect = lambda _key: pressed.set()
        with patch('kodlar.position_controller.foreground_window', return_value=100):
            movement = threading.Thread(target=lambda: controller.pulse('w', .3, 1, time.monotonic()))
            movement.start()
            self.assertTrue(pressed.wait(1))
            def write():
                with controller.gate.exclusive(stop.is_set) as admitted:
                    if admitted:
                        entered.set()
            writer = threading.Thread(target=write)
            writer.start()
            self.assertTrue(entered.wait(1))
            movement.join(1)
            writer.join(1)
        controller.engine.keyboard.release.assert_called_once_with('w')

    def test_maximum_entry_and_minimum_exit_use_two_readings(self):
        controller = self.controller()
        controller.pulse = Mock(return_value=True)
        with patch('kodlar.position_controller.foreground_window', return_value=100), \
             patch('kodlar.position_controller.foreground_is_ours', return_value=False), \
             patch('kodlar.position_controller.window_at_point', return_value=100):
            controller.evaluate((11, 0), time.monotonic(), 1)
            self.assertFalse(controller.returning)
            controller.evaluate((11, 0), time.monotonic(), 1)
            self.assertTrue(controller.returning)
            controller.pending_observation = None
            controller.evaluate((1, 0), time.monotonic(), 1)
            self.assertTrue(controller.returning)
            controller.evaluate((1, 0), time.monotonic(), 1)
            self.assertFalse(controller.returning)
            self.assertTrue(controller.gate.allowed())


class PositionEngineTests(unittest.TestCase):
    def test_wasd_suppression_preserves_preferences_and_exempts_text_members(self):
        with patch('kodlar.engine.Controller'), patch('kodlar.engine.keyboard.Controller'):
            engine = RandomizedAutoClicker(AppConfig())
        try:
            standalone = KeyConfig('w', 1, 0, enabled=True)
            opening = KeyConfig('enter', 1, 0)
            body = KeyConfig('a', 1, 0)
            closing = KeyConfig('enter', 1, 0)
            engine.sequence_groups = [SequenceGroup(
                children=[SequenceItem('macro', macro_id=c.id_token) for c in (opening, body, closing)],
                writing_blocks=[WritingBlock(opening.id_token, closing.id_token)])]
            engine.position_controller.config.enabled = True
            self.assertFalse(engine.is_config_enabled(standalone))
            self.assertTrue(standalone.enabled)
            self.assertFalse(engine.position_manages_config(body))
            engine.position_controller.config.enabled = False
            self.assertTrue(engine.is_config_enabled(standalone))
        finally:
            engine.stop()


@unittest.skipUnless(os.name == 'nt', 'Windows OCR required')
class KarosScreenshotOCRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = CoordinateOCR()
        try:
            cls.reader.start()
        except Exception as error:
            cls.reader.close()
            if 'language is not installed' in str(error):
                raise unittest.SkipTest(f'Windows OCR dili hazır değil: {error}')
            raise

    @classmethod
    def tearDownClass(cls):
        cls.reader.close()

    def test_provided_karos_screenshots(self):
        fixtures = Path(__file__).with_name('fixtures')
        for name, region, expected in (
            ('karos-67.png', (15, 16, 82, 16), (67.6, 77.5)),
            ('karos-69.png', (39, 23, 81, 17), (69.0, 87.1)),
        ):
            with self.subTest(image=name):
                encoded = base64.b64encode((fixtures/name).read_bytes()).decode('ascii')
                point = self.reader.read(region, encoded)
                self.assertEqual(point, expected, repr(self.reader.last_texts))
