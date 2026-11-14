from __future__ import annotations

import os
import threading
import time
import tkinter as tk
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from kodlar.models import KeyConfig
from kodlar.profile_store import load_profiles
from kodlar.sequences import SequenceGroup, SequenceItem, WritingBlock, sequence_groups_from_list, sequence_group_to_dict
from kodlar.tests.test_edit_lock import EditLockTests as _Fixture
from kodlar.tests.test_engine import EngineTests as _EngineFixture


class GroupEnabledTests(unittest.TestCase):
    setUp = _EngineFixture.setUp
    tearDown = _EngineFixture.tearDown

    def test_disabled_group_never_runs_and_member_values_survive_restart(self):
        configs = [KeyConfig('a', 0.01, 0, enabled=True), KeyConfig('b', 0.01, 0, enabled=False)]
        group = SequenceGroup(children=[SequenceItem('macro', macro_id=c.id_token) for c in configs], enabled=False)
        before = deepcopy(configs)
        self.engine.configure(configs, sequence_groups=[group])
        self.engine.set_enabled(True)
        self.assertFalse(self.engine.start_sequence(group.id_token))
        self.assertFalse(self.engine.execute_group_step(configs[0].id_token, threading.Event()))
        time.sleep(0.03)
        self.engine.set_enabled(False)
        self.engine.keyboard.press.assert_not_called()
        self.assertEqual(configs, before)
        group.enabled = True
        self.engine.configure(configs, sequence_groups=[group])
        pressed = threading.Event()
        self.engine.keyboard.press.side_effect = lambda _key: pressed.set()
        self.engine.set_enabled(True)
        self.assertTrue(pressed.wait(1))
        self.engine.set_enabled(False)
        self.assertEqual(configs, before)
        self.assertTrue(all(str(c.args[0]) == 'a' for c in self.engine.keyboard.press.call_args_list))

    def test_disabled_group_with_incomplete_chat_does_not_block_other_groups(self):
        config = KeyConfig('a', 0.01, 0)
        disabled = SequenceGroup(enabled=False, writing_blocks=[WritingBlock('missing')])
        group = SequenceGroup(children=[SequenceItem('macro', macro_id=config.id_token)])
        self.engine.configure([config], sequence_groups=[disabled, group])
        fired = threading.Event()
        self.engine.keyboard.press.side_effect = lambda _key: fired.set()
        self.engine.set_enabled(True)
        self.assertTrue(fired.wait(1))
        self.engine.set_enabled(False)

    def test_enable_state_round_trips_and_old_groups_default_on(self):
        group = SequenceGroup(enabled=False)
        self.assertFalse(sequence_groups_from_list([sequence_group_to_dict(group)])[0].enabled)
        self.assertTrue(sequence_groups_from_list([{'name': 'Eski grup'}])[0].enabled)


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Desktop required')
class GroupAppearanceTests(unittest.TestCase):
    setUp = _Fixture.setUp
    close = _Fixture.close

    def test_group_checkbox_preserves_members_and_disables_contents_until_unlocked(self):
        before = deepcopy(self.app.key_configs)
        checkbox = self.app.group_widgets[self.group.id_token]['check']
        self.assertIsInstance(checkbox, tk.Checkbutton)
        normal_fg = self.app.config_widgets[id(self.grouped)]['key_btn'].cget('fg')
        checkbox.invoke()
        self.root.update()
        self.assertFalse(self.group.enabled)
        self.assertEqual(self.app.key_configs, before)
        key = self.app.config_widgets[id(self.grouped)]['key_btn']
        self.assertEqual(str(key.cget('state')), 'disabled')
        self.assertEqual(str(self.app.group_widgets[self.group.id_token]['check'].cget('state')), 'normal')
        self.app.add_key_to_group(self.group)
        self.assertEqual(len(self.group.children), 1)
        # A direct late callback cannot change a locked member either.
        self.app.toggle_key_enabled(self.grouped, Mock(get=lambda: 1))
        self.assertFalse(self.grouped.enabled)
        data = load_profiles()
        self.assertFalse(data['groups'][data['active_profile']][0]['enabled'])
        self.app.group_widgets[self.group.id_token]['check'].invoke()
        self.assertTrue(self.group.enabled)
        self.assertEqual(self.app.key_configs, before)
        self.assertEqual(self.app.config_widgets[id(self.grouped)]['key_btn'].cget('fg'), normal_fg)
        self.assertEqual(str(self.app.config_widgets[id(self.grouped)]['key_btn'].cget('state')), 'normal')

    def test_inactive_cards_are_faded_and_reenable_restores_their_colors(self):
        widgets = self.app.config_widgets[id(self.grouped)]
        self.assertNotEqual(widgets['key_btn'].cget('fg'), self.app.text_primary)
        self.app.toggle_key_enabled(self.grouped, Mock(get=lambda: 1))
        self.assertEqual(widgets['key_btn'].cget('fg'), self.app.text_primary)
        self.app.toggle_key_enabled(self.grouped, Mock(get=lambda: 0))
        self.assertNotEqual(widgets['key_btn'].cget('fg'), self.app.text_primary)
        self.assertEqual(str(widgets['key_btn'].cget('state')), 'normal')

    def test_color_swatch_is_hidden_until_monitoring_enabled(self):
        widgets = self.app.config_widgets[id(self.config)]
        self.assertFalse(widgets['color_preview'].winfo_manager())
        self.app.toggle_screen_mode(self.config, Mock(get=lambda: 1))
        self.assertEqual(widgets['color_preview'].winfo_manager(), 'pack')
        self.app.toggle_screen_mode(self.config, Mock(get=lambda: 0))
        self.assertFalse(widgets['color_preview'].winfo_manager())

    def test_default_profile_rename_preserves_macros_groups_and_persisted_name(self):
        old = self.app.active_profile
        before = deepcopy(self.app.key_configs)
        self.group.writing_blocks = [WritingBlock(self.grouped.id_token)]
        self.group.enabled = False
        with patch('kodlar.gui.simpledialog.askstring', return_value='Savaş'):
            self.app.rename_profile()
        self.assertEqual(self.app.active_profile, 'Savaş')
        self.assertNotIn(old, self.app.profiles_data['profiles'])
        self.assertNotIn(old, self.app.profiles_data['groups'])
        self.assertEqual(self.app.key_configs, before)
        stored = load_profiles()
        self.assertEqual(stored['active_profile'], 'Savaş')
        self.assertEqual(stored['groups']['Savaş'][0]['writing_blocks'][0]['opening'], self.grouped.id_token)
        self.assertFalse(stored['groups']['Savaş'][0]['enabled'])

    def test_rename_rejects_collision_and_keeps_names_when_cancelled(self):
        self.app.profiles_data['profiles']['Other'] = []
        old = self.app.active_profile
        for value in ('  ', 'oTHER', 'x'*41, None):
            with self.subTest(value=value), patch('kodlar.gui.simpledialog.askstring', return_value=value), patch('kodlar.gui.messagebox.showerror'):
                self.app.rename_profile()
                self.assertEqual(self.app.active_profile, old)
        with patch('kodlar.gui.simpledialog.askstring', return_value=old.upper()):
            self.app.rename_profile()
        self.assertEqual(self.app.active_profile, old.upper())

    def test_profile_menu_has_rename_and_no_reset_action(self):
        menu_button = next(w for w in self.app.profile_frame.winfo_children() if isinstance(w, tk.Menubutton) and w.cget('text') == '⋯')
        menu = menu_button.nametowidget(menu_button.cget('menu'))
        labels = [menu.entrycget(i, 'label') for i in range(menu.index('end')+1)]
        self.assertIn('İsmi değiştir', labels)
        self.assertNotIn('Tümünü sıfırla', labels)


del _Fixture, _EngineFixture
