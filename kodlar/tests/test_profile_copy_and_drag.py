from __future__ import annotations

import os
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from kodlar.models import KeyConfig
from kodlar.position_model import PositionConfig
from kodlar.profile_store import load_profiles
from kodlar.tests.test_edit_lock import EditLockTests as Fixture


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'A desktop display is required')
class ProfileCopyAndDragTests(unittest.TestCase):
    setUp = Fixture.setUp
    close = Fixture.close

    def test_copy_keeps_all_settings_and_creates_independent_objects(self):
        old = self.app.active_profile
        self.app.position_config = PositionConfig(enabled=True, center=(12.3, 45.6))
        self.app.save_current_configs_to_profiles()
        source = deepcopy(self.app.profiles_data)
        original_config, original_group = self.app.key_configs[0], self.app.sequence_groups[0]
        with patch('kodlar.gui.simpledialog.askstring', return_value='Kopya'):
            self.app.copy_profile()
        self.assertEqual(self.app.active_profile, 'Kopya')
        for section in ('profiles', 'groups', 'positions'):
            self.assertEqual(self.app.profiles_data[section]['Kopya'], source[section][old])
            self.assertEqual(load_profiles()[section]['Kopya'], json.loads(json.dumps(source[section][old])))
        self.assertIsNot(self.app.key_configs[0], original_config)
        self.assertIsNot(self.app.sequence_groups[0], original_group)
        self.app.key_configs[0].key = 'z'
        self.assertEqual(original_config.key, 'a')

    def test_copy_cancel_and_duplicate_name_leave_profile_unchanged(self):
        original = deepcopy(self.app.profiles_data)
        for name in (None, self.app.active_profile.upper()):
            with patch('kodlar.gui.simpledialog.askstring', return_value=name), patch('kodlar.gui.messagebox.showerror'):
                self.app.copy_profile()
            self.assertEqual(self.app.profiles_data, original)

    def test_root_handle_drags_into_group_and_can_be_taken_out(self):
        self.group.enabled = True
        self.app.refresh_keys_list_ui()
        self.root.update()
        handle = self.app.config_widgets[id(self.config)]['handle']
        self.assertTrue(handle.winfo_manager())
        self.assertTrue(handle.bind('<ButtonPress-1>'))
        card = self.app._group_cards[self.group.id_token][0][1]
        start = SimpleNamespace(widget=handle, x_root=handle.winfo_rootx()+3, y_root=handle.winfo_rooty()+3)
        target = SimpleNamespace(widget=handle, x_root=card.winfo_rootx()+10, y_root=card.winfo_rooty()+2)
        self.app.start_group_drag(start, None, self.config.id_token)
        self.app.drag_group_key(target)
        self.app.finish_group_drag(target)
        self.assertEqual(self.group.children[0].macro_id, self.config.id_token)
        self.app.move_macro_card(self.config.id_token, None, 0)
        self.assertNotIn(self.config.id_token, [i.macro_id for i in self.group.children])
        widgets = self.app.config_widgets[id(self.config)]
        self.assertIsNone(widgets['parent_id'])
        self.assertTrue(widgets['timing_frame'].winfo_manager())

    def test_independent_order_survives_save_and_reopen(self):
        extra = KeyConfig('c', .5, .1)
        self.app.key_configs.append(extra)
        self.app.refresh_keys_list_ui()
        self.app.move_macro_card(extra.id_token, None, 0)
        saved = load_profiles()['profiles'][self.app.active_profile]
        self.assertEqual(saved[0]['id_token'], extra.id_token)


del Fixture
