from __future__ import annotations

import os
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from kodlar.models import KeyConfig
from kodlar.sequences import SequenceGroup, SequenceItem
from kodlar.tests.test_edit_lock import EditLockTests as _UIFixture
from kodlar.tests.test_engine import EngineTests as _EngineFixture


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Desktop required')
class CardReconciliationTests(unittest.TestCase):
    setUp = _UIFixture.setUp
    close = _UIFixture.close

    def card(self, config):
        return self.app.config_widgets[id(config)]['card']

    def test_initial_view_is_mapped_and_unchanged_refresh_creates_no_windows(self):
        self.assertTrue(self.app._current_view['frame'].winfo_ismapped())
        self.assertGreater(self.card(self.config).winfo_width(), 250)
        original = {id(c): self.card(c) for c in self.app.key_configs}
        widgets = self.app.config_widgets[id(self.config)]
        widgets['int_entry'].delete(0, 'end')
        widgets['int_entry'].insert(0, '2.')
        with patch.object(self.app, 'draw_card_row', wraps=self.app.draw_card_row) as create, \
             patch.object(self.app, 'draw_sequence_group', wraps=self.app.draw_sequence_group) as group:
            for _ in range(4):
                self.app.refresh_keys_list_ui()
            create.assert_not_called()
            group.assert_not_called()
        self.assertEqual(widgets['int_entry'].get(), '2.')
        self.assertEqual(original, {id(c): self.card(c) for c in self.app.key_configs})

    def test_add_delete_and_reorder_only_touch_affected_card(self):
        first, independent = self.card(self.grouped), self.card(self.config)
        with patch.object(self.app, 'draw_card_row', wraps=self.app.draw_card_row) as create:
            self.app.add_key_to_group(self.group)
            self.assertEqual(create.call_count, 1)
        added = self.app.key_configs[-1]
        second = self.card(added)
        with patch.object(self.app, 'draw_card_row', wraps=self.app.draw_card_row) as create:
            self.app.step_group_key(self.group, added.id_token, -1)
            self.app.delete_key_config(added)
            create.assert_not_called()
        self.assertIs(self.card(self.grouped), first)
        self.assertIs(self.card(self.config), independent)
        self.assertFalse(second.winfo_exists())

    def test_writing_and_group_lock_update_existing_widgets(self):
        self.app.add_key_to_group(self.group)
        end = self.app.key_configs[-1]
        cards = [self.card(self.grouped), self.card(end)]
        with patch.object(self.app, 'draw_card_row', wraps=self.app.draw_card_row) as create:
            self.app.toggle_writing(self.group, self.grouped.id_token)
            self.app.toggle_writing(self.group, end.id_token)
            check = self.app.group_widgets[self.group.id_token]['check']
            check.invoke()
            check.invoke()
            create.assert_not_called()
        self.assertEqual(cards, [self.card(self.grouped), self.card(end)])
        self.assertEqual(self.app.config_widgets[id(end)]['writing_check'].cget('text'), 'Yazı kapatıyor')

    def test_profile_switch_restores_cached_cards_and_callback_models(self):
        self.app.save_current_configs_to_profiles()
        original_name = self.app.active_profile
        original_card = self.card(self.config)
        self.app.profiles_data['profiles']['Diğer'] = []
        self.app.profiles_data['groups']['Diğer'] = []
        self.app.on_profile_menu_select('Diğer')
        self.app.last_add_time = 0
        self.app.add_blank_key_config()
        other = self.app.key_configs[0]
        other_card = self.card(other)
        with patch.object(self.app, 'draw_card_row', wraps=self.app.draw_card_row) as create:
            self.app.on_profile_menu_select(original_name)
            self.assertIs(self.card(self.config), original_card)
            self.assertIs(self.app._find_config(self.config.id_token), self.config)
            self.app.toggle_key_enabled(self.config, Mock(get=lambda: 0))
            self.app.on_profile_menu_select('Diğer')
            self.assertIs(self.card(other), other_card)
            self.app.on_profile_menu_select(original_name)
            self.assertFalse(self.config.enabled)
            create.assert_not_called()

    def test_switch_commits_focused_edit_and_ignores_hidden_profile_callbacks(self):
        widgets = self.app.config_widgets[id(self.config)]
        entry = widgets['int_entry']
        entry.delete(0, 'end')
        entry.insert(0, '0.8')
        self.app.profiles_data['profiles']['Başka'] = []
        self.app.profiles_data['groups']['Başka'] = []
        original = self.app.active_profile
        with patch.object(self.root, 'focus_get', return_value=entry):
            self.app.on_profile_menu_select('Başka')
        self.assertEqual(self.config.interval_seconds, .8)
        with patch.object(self.app, 'save_current_configs_to_profiles') as save:
            self.app.auto_save_timing(self.config, Mock(get=lambda: '9'), 'interval')
            save.assert_not_called()
        self.app.on_profile_menu_select(original)
        self.assertEqual(self.config.interval_seconds, .8)

    def test_profile_cache_is_bounded_and_rename_reuses_view(self):
        view = self.app._current_view
        with patch('kodlar.gui.simpledialog.askstring', return_value='Yeni ad'):
            self.app.rename_profile()
        self.app.refresh_keys_list_ui()
        self.assertIs(self.app._current_view, view)
        for i in range(5):
            name = f'Profil {i}'
            self.app.profiles_data['profiles'][name] = []
            self.app.profiles_data['groups'][name] = []
            self.app.on_profile_menu_select(name)
        self.assertEqual(len(self.app._profile_views), 3)
        self.assertFalse(view['frame'].winfo_exists())

    def test_order_controls_are_in_action_column_above_delete(self):
        widgets = self.app.config_widgets[id(self.grouped)]
        self.root.update()
        rail = widgets['rail']
        self.assertEqual(widgets['delete_btn'].master, rail)
        self.assertGreater(widgets['delete_btn'].winfo_rooty(), widgets['handle'].winfo_rooty())
        self.assertGreater(rail.winfo_rootx(), widgets['key_btn'].winfo_rootx())
        for arrow in widgets['arrows']:
            self.assertLess(arrow.winfo_rooty(), widgets['delete_btn'].winfo_rooty())

    def test_only_changed_cards_are_synchronized(self):
        widgets = self.app.config_widgets[id(self.config)]
        untouched = self.app.config_widgets[id(self.grouped)]
        before = untouched['signature']
        self.config.interval_seconds = 0.7
        self.app.refresh_keys_list_ui()
        self.assertEqual(widgets['int_entry'].get(), '0.700')
        self.assertEqual(untouched['signature'], before)
        self.assertIs(self.app.config_widgets[id(self.config)], widgets)

    def test_unchanged_fields_and_reselecting_profile_do_not_write_or_reconfigure(self):
        widgets = self.app.config_widgets[id(self.config)]
        name = self.app.group_widgets[self.group.id_token]['name_entry']
        with patch.object(self.app, 'save_current_configs_to_profiles') as save, \
             patch.object(self.engine, 'configure') as configure:
            self.app.auto_save_timing(self.config, widgets['int_entry'], 'interval')
            self.app.save_group_name(self.group, name)
            self.app.on_profile_menu_select(self.app.active_profile)
            save.assert_not_called()
            configure.assert_not_called()


class WorkerReconciliationTests(unittest.TestCase):
    setUp = _EngineFixture.setUp
    tearDown = _EngineFixture.tearDown

    def test_edit_and_add_retain_unrelated_workers_and_mode_change_restarts_only_one(self):
        def worker(*_args):
            return Mock(is_alive=Mock(return_value=False))
        configs = [KeyConfig('a', 1, .1), KeyConfig('b', 1, .1)]
        with patch('kodlar.engine.KeyClickerWorker', side_effect=worker) as create:
            self.engine.configure(configs, sequence_groups=[])
            first, second = self.engine.key_workers
            configs[0].interval_seconds = .3
            self.engine.configure(configs, restart=True)
            self.assertEqual(create.call_count, 2)
            self.assertEqual(self.engine.key_workers, [first, second])
            added = KeyConfig('c', 1, .1)
            configs.append(added)
            self.engine.configure(configs)
            self.assertEqual(create.call_count, 3)
            third = self.engine.key_workers[-1]
            configs[0].screen_mode = True
            self.engine.configure(configs)
            self.assertEqual(create.call_count, 4)
            first.stop.assert_called_once()
            self.assertIs(self.engine.key_workers[1], second)
            self.assertIs(self.engine.key_workers[2], third)
            second.stop.assert_not_called()

    def test_removed_and_regrouped_workers_are_retired_without_duplicates(self):
        configs = [KeyConfig('a', 1, .1), KeyConfig('b', 1, .1)]
        with patch('kodlar.engine.KeyClickerWorker', side_effect=lambda *_a: Mock(is_alive=Mock(return_value=False))):
            self.engine.configure(configs)
            first, second = self.engine.key_workers
            group = SequenceGroup(children=[SequenceItem('macro', macro_id=configs[0].id_token)])
            self.engine.configure(configs, sequence_groups=[group])
            self.assertEqual(self.engine.key_workers, [second])
            first.stop.assert_called_once()
            self.assertFalse(self.engine._group_workers[configs[0].id_token].start.called)
            self.engine.configure(configs[:1], sequence_groups=[group])
            second.stop.assert_called_once()
            self.assertEqual(self.engine.key_workers, [])

    def test_slow_retiring_worker_never_gets_an_overlapping_replacement(self):
        first = Mock(is_alive=Mock(return_value=True))
        replacement = Mock(is_alive=Mock(return_value=False))
        config = KeyConfig('a', 1, .1)
        with patch('kodlar.engine.KeyClickerWorker', side_effect=[first, replacement]) as create:
            self.engine.configure([config])
            config.screen_mode = True
            self.engine.configure([config])
            self.assertEqual(create.call_count, 1)
            self.assertEqual(self.engine.key_workers, [first])
            first.is_alive.return_value = False
            self.engine.configure([config])
            self.assertEqual(create.call_count, 2)
            self.assertEqual(self.engine.key_workers, [replacement])


del _UIFixture, _EngineFixture
