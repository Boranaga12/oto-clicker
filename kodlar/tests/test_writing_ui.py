from __future__ import annotations

import os
import tkinter as tk
import unittest
from unittest.mock import Mock, patch, PropertyMock

from kodlar.models import KeyConfig
from kodlar.sequences import SequenceItem, WritingBlock, writing_layout
from kodlar.profile_store import load_profiles
from kodlar.tests.test_edit_lock import EditLockTests as _Fixture


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'A desktop display is required')
class WritingUITests(unittest.TestCase):
    setUp = _Fixture.setUp
    close = _Fixture.close

    def prepare(self):
        self.grouped.enabled = True
        self.keys = [self.grouped] + [KeyConfig('enter', 0.1, 0.01) for _ in range(6)]
        self.app.key_configs = [self.config] + self.keys
        self.group.children = [SequenceItem('macro', macro_id=c.id_token) for c in self.keys]
        self.app.refresh_keys_list_ui()
        self.root.update()

    def checks(self, index):
        card = self.app._group_cards[self.group.id_token][index][1]
        return [child for row in card.winfo_children() for child in row.winfo_children()
                if isinstance(child, tk.Checkbutton)]

    def test_dynamic_labels_locked_bodies_and_multiple_blocks_are_saved(self):
        self.prepare()
        self.app.toggle_writing(self.group, self.keys[0].id_token)
        self.assertEqual(self.checks(2)[2].cget('text'), 'Yazı kapatıyor')
        self.app.toggle_writing(self.group, self.keys[3].id_token)
        self.app.toggle_writing(self.group, self.keys[4].id_token)
        self.app.toggle_writing(self.group, self.keys[6].id_token)
        self.assertEqual(self.checks(0)[2].cget('text'), 'Yazı açıyor')
        self.assertEqual(self.checks(1)[2].cget('text'), 'Yazı')
        self.assertEqual(str(self.checks(1)[2].cget('state')), 'disabled')
        self.assertEqual(self.checks(1)[2].var.get(), 1)
        self.assertEqual(self.checks(3)[2].cget('text'), 'Yazı kapatıyor')
        self.assertEqual(len(self.group.writing_blocks), 2)
        profile = load_profiles()
        saved = profile['groups'][profile['active_profile']][0]['writing_blocks']
        self.assertEqual([b['opening'] for b in saved], [self.keys[0].id_token, self.keys[4].id_token])
        self.root.update()
        for _key, card in self.app._group_cards[self.group.id_token]:
            self.assertLessEqual(card.winfo_reqwidth(), 460)

    def test_arrows_drag_and_running_guard(self):
        self.prepare()
        first = self.keys[0].id_token
        self.app.step_group_key(self.group, first, 1)
        self.assertEqual(self.group.children[1].macro_id, first)
        cards = self.app._group_cards[self.group.id_token]
        self.root.update()
        from types import SimpleNamespace
        handle = self.app.config_widgets[id(self.keys[0])]['handle']
        x = handle.winfo_rootx()+3
        start = SimpleNamespace(widget=handle, x_root=x, y_root=handle.winfo_rooty()+3)
        target = SimpleNamespace(widget=handle, x_root=x, y_root=cards[0][1].winfo_rooty()+2)
        self.app.start_group_drag(start, self.group, first)
        self.app.drag_group_key(target)
        self.app.finish_group_drag(target)
        self.assertEqual(self.group.children[0].macro_id, first)
        self.assertIsNone(self.app._group_drag_job)
        self.assertIsNone(self.app._group_drop_line)
        before = [c.macro_id for c in self.group.children]
        with patch.object(type(self.engine), 'is_running', new_callable=PropertyMock, return_value=True):
            self.app.move_group_key(self.group, first, 7)
            self.app.toggle_writing(self.group, first)
        self.assertEqual([c.macro_id for c in self.group.children], before)
        self.assertEqual(self.group.writing_blocks, [])

    def test_deleting_boundary_keeps_invalid_block_and_blocks_start(self):
        self.prepare()
        self.group.writing_blocks = [WritingBlock(self.keys[0].id_token, self.keys[3].id_token)]
        self.app.refresh_keys_list_ui()
        self.app.delete_key_config(self.keys[3])
        self.assertTrue(writing_layout(self.group)[1])
        self.engine.set_enabled(True)
        self.assertFalse(self.engine.is_running)
        self.assertEqual(len(self.group.writing_blocks), 1)

    def test_moving_opening_carries_whole_section_and_close_uncheck_is_incomplete(self):
        self.prepare()
        self.app.toggle_writing(self.group, self.keys[0].id_token)
        self.app.toggle_writing(self.group, self.keys[2].id_token)
        self.app.step_group_key(self.group, self.keys[0].id_token, 1)
        self.assertEqual([i.macro_id for i in self.group.children[:4]],
                         [self.keys[3].id_token, self.keys[0].id_token, self.keys[1].id_token, self.keys[2].id_token])
        self.app.toggle_writing(self.group, self.keys[2].id_token)
        self.assertTrue(writing_layout(self.group)[1])
        self.assertEqual(self.group.writing_blocks[0].closing, '')


# Keep the shared fixture out of unittest discovery for this module.
del _Fixture
