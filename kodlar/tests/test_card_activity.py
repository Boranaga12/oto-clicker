from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from kodlar.tests.test_edit_lock import EditLockTests as Fixture


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'A desktop display is required')
class CardActivityTests(unittest.TestCase):
    setUp = Fixture.setUp
    close = Fixture.close
    start = Fixture.start
    process_queue_now = Fixture.process_queue_now

    def test_actual_input_pulses_card_and_restores_colors_with_one_timer(self):
        self.start()
        activity = self.app.card_activity
        widgets = self.app.config_widgets[id(self.config)]
        original = widgets['card'].cget('highlightbackground')
        stripe = widgets['stripe'].cget('bg')
        with patch('kodlar.card_activity.time.monotonic', return_value=10):
            activity.pulse(widgets)
            job = activity.job
            activity.pulse(widgets)
            self.assertEqual(activity.job, job)
            self.assertEqual(len(activity.cards), 1)
        self.root.after_cancel(activity.job)
        with patch('kodlar.card_activity.time.monotonic', return_value=10.1):
            activity.tick()
            self.assertNotEqual(widgets['card'].cget('highlightbackground'), original)
        activity.clear()
        self.assertEqual(widgets['card'].cget('highlightbackground'), original)
        self.assertEqual(widgets['stripe'].cget('bg'), stripe)
        self.assertIsNone(activity.job)

    def test_queue_ignores_old_profile_and_stopped_inputs(self):
        self.start()
        with patch.object(self.app.card_activity, 'pulse') as pulse:
            self.app.on_macro_input('another-profile', self.config.id_token)
            self.process_queue_now()
            pulse.assert_not_called()
            self.app.on_macro_input(self.app.active_profile, self.config.id_token)
            self.process_queue_now()
            pulse.assert_called_once()
            pulse.reset_mock()
            self.engine.set_enabled(False)
            self.app.on_macro_input(self.app.active_profile, self.config.id_token)
            self.process_queue_now()
            pulse.assert_not_called()


del Fixture
