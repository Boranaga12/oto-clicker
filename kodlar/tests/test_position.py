from __future__ import annotations

import base64
import os
from pathlib import Path
import threading
import time
import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from kodlar.coordinate_ocr import CoordinateOCR, ocr_error_message
from kodlar.position_model import PositionConfig, ReadingFilter, parse_coordinates
from kodlar.position_controller import PositionController, Steering
from kodlar.profile_store import _normalise
from kodlar.writing import WritingGate
from kodlar.config import AppConfig
from kodlar.engine import RandomizedAutoClicker
from kodlar.models import KeyConfig
from kodlar.sequences import SequenceGroup, SequenceItem, WritingBlock
from kodlar.walking_input import ContinuousWalker, WalkRequest


class PositionModelTests(unittest.TestCase):
    def test_ocr_errors_explain_missing_language_and_security_separately(self):
        self.assertIn('Metin Tanıma', ocr_error_message(RuntimeError('Windows OCR language is not installed')))
        self.assertIn('PowerShell bulunamadı', ocr_error_message(FileNotFoundError('missing powershell.exe')))
        self.assertIn('güvenlik', ocr_error_message(RuntimeError('only core types in this language mode')))

    def test_coordinates_require_two_numbers_with_decimal_points(self):
        self.assertEqual(parse_coordinates('67.6 77.5'), (67.6, 77.5))
        self.assertEqual(parse_coordinates('69.0 87.1'), (69.0, 87.1))
        self.assertEqual(parse_coordinates('71.9 / 57.2'), (71.9, 57.2))
        self.assertEqual(parse_coordinates('71.9/57.2'), (71.9, 57.2))
        self.assertEqual(parse_coordinates('71 .9 57.2'), (71.9, 57.2))
        for text in ('676 77.5', '67.6', '67.6 77.5 10.0', '67.6 77.5\n10.0', '67.6 77.5\n69.0 87.1'):
            self.assertIsNone(parse_coordinates(text))

    def test_ocr_can_read_a_labelled_panel_without_ignoring_extra_numbers(self):
        self.assertEqual(CoordinateOCR.parse_frame('Konum\n71.9 / 57.2'), (71.9, 57.2))
        self.assertIsNone(CoordinateOCR.parse_frame('71.9 / 57.2\n10.0'))
        self.assertIsNone(CoordinateOCR.parse_frame('71.9 / 57.2\n75.7 / 53.0'))

    def test_enabled_preference_survives_missing_region_round_trip(self):
        config = PositionConfig(enabled=True, center=(71.9, 57.2))
        restored = PositionConfig.from_dict(config.to_dict())
        self.assertTrue(restored.enabled)
        self.assertFalse(restored.ready)

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
        self.assertTrue(config.enabled)
        self.assertFalse(config.ready)

    def test_stationary_center_requires_three_readings_and_jumps_are_rejected(self):
        samples = ReadingFilter()
        for stamp in (1, 1.25, 1.5):
            self.assertTrue(samples.accept((67.6, 77.5), stamp))
        self.assertEqual(len(samples.stable), 3)
        self.assertFalse(samples.accept((176.6, 177.5), 1.75))
        self.assertEqual(samples.stable, [])

    def test_slow_consistent_center_reads_survive_brief_ocr_gaps(self):
        samples = ReadingFilter()
        self.assertTrue(samples.accept((71.9, 57.2), 1))
        self.assertFalse(samples.accept(None, 2))
        self.assertTrue(samples.accept((71.9, 57.2), 2.5))
        self.assertFalse(samples.accept(None, 3.5))
        self.assertTrue(samples.accept((71.9, 57.2), 4))
        self.assertEqual(len(samples.stable), 3)
        self.assertFalse(samples.accept(None, 9))
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

    def test_digit_holes_reject_six_eight_confusion_without_rewriting_digits(self):
        self.assertFalse(CoordinateOCR.shape_allows('78.6 61.2', [[0, 1, 1, 1, 0, 0]]*2))
        self.assertFalse(CoordinateOCR.shape_allows('76.6 61.2', [[0, 2, 1, 1, 0, 0]]*2))
        self.assertTrue(CoordinateOCR.shape_allows('76.6 61.2', [[0, 1, 1, 1, 0, 0]]*2))

    def test_single_stationary_digit_jump_requires_confirmation(self):
        samples = ReadingFilter()
        self.assertTrue(samples.accept((76.6, 61.2), 1))
        self.assertFalse(samples.accept((78.6, 61.2), 1.25))
        self.assertTrue(samples.accept((76.6, 61.2), 1.5))
        self.assertEqual(samples.last[0], (76.6, 61.2))

    def test_corrections_only_turn_while_w_is_managed_by_walker(self):
        steering = Steering()
        config = PositionConfig(center=(0, 0))
        self.assertIsNone(steering.correction((12, 0), config))
        steering.observe((12, 0), (13, 0), (0, 0))
        self.assertEqual(steering.correction((13, 0), config)[0], 'a')
        steering.observe((13, 0), (13, 1), (0, 0), ('a', .08))
        self.assertIsNotNone(steering.a_rate)
        self.assertTrue(.1 <= steering.correction((13, 1), config)[1] <= .4)


class PositionPriorityTests(unittest.TestCase):
    def controller(self):
        engine = SimpleNamespace(writing_gate=WritingGate(), is_running=True,
            _writing_target=None, input_lock=threading.RLock(), keyboard=Mock(), mark_injected_key=Mock())
        controller = PositionController(engine)
        controller.config = PositionConfig(True, (1, 2, 90, 20), (0, 0, 1920, 1080), (0, 0))
        controller.generation = 1
        controller.gate.position_enabled = True
        controller.gate.position_valid_until = time.monotonic()+.75
        controller.motion = Mock(holding=False, turning=False, total=0.0)
        return controller

    def test_activation_explains_missing_settings_without_disabling_preference(self):
        controller = self.controller()
        controller.config.region = None
        self.assertIn('Konumu Seç', controller.activation_issue())
        self.assertTrue(controller.config.enabled)

    def test_activation_explains_ocr_error_and_pending_startup(self):
        controller = self.controller()
        with patch('kodlar.position_controller.screen_bounds', return_value=controller.config.display):
            self.assertIn('OCR hazırlanıyor', controller.activation_issue({'available': None}))
            self.assertEqual(controller.activation_issue({'available': False, 'ocr_message': 'OCR dili eksik'}), 'OCR dili eksik')
            self.assertIsNone(controller.activation_issue({'available': True}))
        self.assertTrue(controller.config.enabled)

    def test_writing_end_keeps_normal_input_blocked_until_new_position(self):
        controller = self.controller()
        controller.gate.navigation_active = True
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
        controller.allow_normal(1, time.monotonic()-2)
        self.assertFalse(controller.gate.allowed())

    def test_expired_measurement_alone_does_not_close_normal_gate(self):
        controller = self.controller()
        self.assertTrue(controller.gate.allowed())
        controller.gate.position_valid_until = time.monotonic()-1
        self.assertTrue(controller.gate.allowed())

    def test_ocr_loss_keeps_latched_w_and_normal_macros_paused(self):
        controller = self.controller()
        controller.target = 100
        controller.returning = True
        controller.filter.accept((11, 0), time.monotonic())
        controller.gate.set_position_blocked(True)
        controller.missing_reading(1)
        self.assertFalse(controller.gate.allowed())
        self.assertTrue(controller.returning)
        self.assertEqual(controller.motion.drive.call_args.args[3], float('inf'))
        controller.motion.halt.assert_not_called()

    def test_read_loss_before_latch_does_not_stop_other_macros(self):
        controller = self.controller()
        controller.target = 100
        controller.returning = False
        controller.motion.holding = False
        controller.gate.set_position_blocked(True)
        controller.missing_reading(1)
        self.assertTrue(controller.gate.allowed())
        controller.motion.drive.assert_not_called()

    def test_stop_cancels_walking_without_releasing_unowned_keys(self):
        controller = self.controller()
        controller.engine.is_running = False
        motion = ContinuousWalker(controller)
        motion.request = WalkRequest(1, 100, 0, time.monotonic()+5)
        self.assertTrue(motion.cancelled())
        controller.engine.keyboard.press.assert_not_called()
        controller.engine.keyboard.release.assert_not_called()

    def test_prolonged_return_does_not_cancel_the_latched_goal(self):
        controller = self.controller()
        controller.target = 100
        controller.returning = True
        controller.motion.total = 900
        with patch('kodlar.position_controller.foreground_window', return_value=100), \
             patch('kodlar.position_controller.foreground_is_ours', return_value=False):
            controller.evaluate((12, 0), time.monotonic(), 1)
        controller.motion.drive.assert_called()
        self.assertIsNone(controller.failure)
        self.assertFalse(controller.gate.allowed())

    def test_stationary_evidence_is_required_before_a_detour(self):
        controller = self.controller()
        controller.target = 100
        controller.returning = True
        controller.best_gap = 12
        controller.motion.holding = True
        controller.steering.heading = math.pi
        clock = [time.monotonic()]
        with patch('kodlar.position_controller.foreground_window', return_value=100), \
             patch('kodlar.position_controller.foreground_is_ours', return_value=False), \
             patch('kodlar.position_controller.time.monotonic', side_effect=lambda: clock[0]):
            for index in range(18):
                controller.motion.total = index*.25
                controller.evaluate((12, 0), clock[0], 1)
                clock[0] += .25
            turns = [call.args[-1] for call in controller.motion.drive.call_args_list if call.args[-1] is not None]
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0][0], 'a')
            controller.evaluate((10.9, 0), clock[0], 1)
            self.assertIsNone(controller.obstacles.escape_origin)
        self.assertIsNone(controller.failure)

    def test_missing_frame_does_not_erase_outside_max_confirmation(self):
        controller = self.controller()
        with patch('kodlar.position_controller.foreground_window', return_value=100), \
             patch('kodlar.position_controller.foreground_is_ours', return_value=False), \
             patch('kodlar.position_controller.window_at_point', return_value=100):
            controller.evaluate((12, 0), time.monotonic(), 1)
            self.assertEqual(controller.outside, 1)
            controller.missing_reading(1)
            controller.evaluate((12, 0), time.monotonic(), 1)
        self.assertTrue(controller.returning)
        controller.motion.drive.assert_called()

    def test_writing_pause_cannot_complete_old_obstacle_evidence(self):
        controller = self.controller()
        controller.target = 100
        controller.returning = True
        controller.motion.holding = True
        controller.steering.heading = math.pi
        now = time.monotonic()
        controller.gate.position_epoch = now-.1
        for index in range(16):
            controller.obstacles.samples.append((now-4+index*.25, (12, 0)))
        with patch('kodlar.position_controller.foreground_window', return_value=100), \
             patch('kodlar.position_controller.foreground_is_ours', return_value=False):
            controller.evaluate((12, 0), now, 1)
        self.assertIsNone(controller.obstacles.escape_origin)
        self.assertEqual(len(controller.obstacles.samples), 0)
        self.assertIsNone(controller.motion.drive.call_args.args[-1])

    def test_moving_character_can_be_tracked_before_auto_walk_starts(self):
        controller = self.controller()
        self.assertFalse(controller.motion.holding)
        for index in range(4):
            self.assertTrue(controller.filter_reading((10+index, 0), 1+index*.25))
        self.assertEqual(controller.filter.last[0], (13, 0))

    def test_center_capture_still_requires_stationary_readings(self):
        controller = self.controller()
        controller.center_requested = True
        self.assertTrue(controller.filter_reading((10, 0), 1))
        self.assertFalse(controller.filter_reading((11, 0), 1.25))
        self.assertFalse(controller.filter_reading((12, 0), 1.5))
        self.assertEqual(len(controller.filter.stable), 0)

    def test_late_result_from_another_profile_cannot_unblock(self):
        controller = self.controller()
        controller.gate.set_position_blocked(True)
        controller.allow_normal(0, time.monotonic())
        self.assertFalse(controller.gate.allowed())

    def test_focus_loss_prevents_wasd_and_preserves_other_keys(self):
        controller = self.controller()
        controller.target = 100
        motion = ContinuousWalker(controller)
        motion.request = WalkRequest(1, 100, 0, time.monotonic()+5)
        with patch('kodlar.walking_input.foreground_window', return_value=200):
            self.assertTrue(motion.cancelled())
        controller.engine.keyboard.press.assert_not_called()
        controller.engine.keyboard.release.assert_not_called()

    def test_writer_request_cancels_walk_and_only_owned_key_is_released(self):
        controller = self.controller()
        controller.target = 100
        stop = threading.Event()
        pressed = threading.Event()
        entered = threading.Event()
        controller.engine.keyboard.press.side_effect = lambda _key: pressed.set()
        motion = ContinuousWalker(controller)
        with patch('kodlar.walking_input.foreground_window', return_value=100):
            self.addCleanup(motion.stop)
            motion.drive(1, 100, 0, time.monotonic()+5)
            self.assertTrue(pressed.wait(1))
            def write():
                with controller.gate.exclusive(stop.is_set) as admitted:
                    if admitted:
                        entered.set()
            writer = threading.Thread(target=write)
            writer.start()
            self.assertTrue(entered.wait(1))
            writer.join(1)
            motion.stop()
        controller.engine.keyboard.release.assert_called_once_with('w')

    def test_maximum_latches_return_until_a_real_below_minimum_reading(self):
        controller = self.controller()
        with patch('kodlar.position_controller.foreground_window', return_value=100), \
             patch('kodlar.position_controller.foreground_is_ours', return_value=False), \
             patch('kodlar.position_controller.window_at_point', return_value=100):
            controller.evaluate((11, 0), time.monotonic(), 1)
            self.assertTrue(controller.returning)
            controller.evaluate((11, 0), time.monotonic(), 1)
            self.assertTrue(controller.returning)
            controller.evaluate((1, 0), time.monotonic(), 1)
            self.assertFalse(controller.returning)
            controller.evaluate((1, 0), time.monotonic(), 1)
            self.assertFalse(controller.returning)
            self.assertTrue(controller.gate.allowed())

    def test_latched_return_resumes_w_after_writing_without_any_ocr_result(self):
        controller = self.controller()
        controller.target = 100
        controller.returning = True
        controller.motion = ContinuousWalker(controller)
        self.addCleanup(controller.motion.stop)
        first = threading.Event()
        resumed = threading.Event()
        calls = []
        def pressed(key):
            calls.append(key)
            (first if len(calls) == 1 else resumed).set()
        controller.engine.keyboard.press.side_effect = pressed
        with patch('kodlar.walking_input.foreground_window', return_value=100):
            controller.drive(1, time.monotonic())
            self.assertTrue(first.wait(1))
            with controller.gate.exclusive(lambda: False) as admitted:
                self.assertTrue(admitted)
                controller.engine.keyboard.release.assert_called_once_with('w')
            self.assertTrue(resumed.wait(1))
            self.assertTrue(controller.returning)
            controller.motion.stop()

    def test_w_is_held_across_updates_and_a_correction(self):
        controller = self.controller()
        motion = ContinuousWalker(controller)
        down = threading.Event()
        corrected = threading.Event()
        def press(key):
            if key == 'w':
                down.set()
        controller.engine.keyboard.press.side_effect = press
        controller.engine.keyboard.release.side_effect = lambda key: corrected.set() if key == 'a' else None
        with patch('kodlar.walking_input.foreground_window', return_value=100):
            try:
                motion.drive(1, 100, 0, time.monotonic()+5)
                self.assertTrue(down.wait(1))
                motion.drive(1, 100, 0, time.monotonic()+5, ('a', .08))
                self.assertTrue(corrected.wait(1))
                motion.drive(1, 100, 0, time.monotonic()+5)
                self.assertTrue(motion.holding)
                self.assertEqual(sum(call.args == ('w',) for call in controller.engine.keyboard.press.call_args_list), 1)
                controller.engine.keyboard.release.assert_called_once_with('a')
            finally:
                motion.stop()
        self.assertEqual(controller.engine.keyboard.release.call_args.args, ('w',))


class PositionEngineTests(unittest.TestCase):
    def test_enabled_but_unreadable_position_does_not_prevent_normal_macros(self):
        with patch('kodlar.engine.Controller'), patch('kodlar.engine.keyboard.Controller'):
            engine = RandomizedAutoClicker(AppConfig())
        try:
            engine.position_controller.config = PositionConfig(enabled=True)
            engine.position_controller.snapshot['available'] = True
            engine.set_enabled(True)
            self.assertTrue(engine.is_running)
            self.assertTrue(engine.position_controller.config.enabled)
        finally:
            engine.stop()

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
            engine.position_controller.reading_lost = False
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

    def test_live_layered_coordinate_window_is_captured(self):
        import tkinter as tk
        import gc
        from kodlar.platform_win import flush_desktop
        root = tk.Tk()
        try:
            root.overrideredirect(True)
            root.attributes('-topmost', True)
            root.attributes('-alpha', .95)
            root.geometry('240x70+40+40')
            root.configure(bg='#333333')
            tk.Label(root, text='77.0 / 56.2', bg='#333333', fg='#eeeeee',
                     font=('Segoe UI', 16)).pack(expand=True)
            root.update()
            flush_desktop()
            point = self.reader.read((40, 40, 240, 70))
            self.assertEqual(point, (77.0, 56.2), repr(self.reader.last_texts))
        finally:
            root.destroy()
            root = None
            gc.collect()

    def test_provided_karos_screenshots(self):
        fixtures = Path(__file__).with_name('fixtures')
        for name, region, expected in (
            ('karos-67.png', (15, 16, 82, 16), (67.6, 77.5)),
            ('karos-69.png', (39, 23, 81, 17), (69.0, 87.1)),
            ('karos-76.png', (10, 10, 82, 18), (76.6, 61.2)),
            ('karos-75.png', (26, 25, 81, 17), (75.7, 53.0)),
            ('karos-stable.png', (33, 33, 96, 23), (71.9, 57.2)),
            ('karos-stable.png', (24, 29, 112, 32), (71.9, 57.2)),
            ('karos-stable.png', (0, 0, 148, 86), (71.9, 57.2)),
            ('karos-77.png', (12, 8, 97, 18), (77.0, 56.2)),
            ('karos-77.png', (0, 0, 120, 40), (77.0, 56.2)),
            ('karos-85.png', (0, 0, 118, 38), (85.3, 50.8)),
        ):
            with self.subTest(image=name):
                encoded = base64.b64encode((fixtures/name).read_bytes()).decode('ascii')
                point = self.reader.read(region, encoded)
                self.assertEqual(point, expected, repr(self.reader.last_texts))
                if name == 'karos-85.png':
                    self.assertTrue(self.reader.last_texts[0].startswith('Rakam tanıyıcı'), repr(self.reader.last_texts))
                self.assertEqual(self.reader.read(region, encoded), expected, 'Cached OCR preparation changed the reading')
