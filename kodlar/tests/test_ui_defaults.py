from __future__ import annotations

import unittest
from unittest.mock import Mock

from kodlar.gui import ClickerApp
from kodlar.sequences import SequenceGroup


class NewKeyDefaultTests(unittest.TestCase):
    def app(self):
        app = ClickerApp.__new__(ClickerApp)
        app.key_configs = []
        app.clicker = Mock(is_running=False)
        app.last_add_time = 0
        app.save_current_configs_to_profiles = Mock()
        app.draw_card_row = Mock()
        app.draw_markers = Mock()
        app.refresh_keys_list_ui = Mock()
        app.list_container = Mock()
        return app

    def test_new_independent_key_has_hundred_milliseconds_randomness(self):
        app = self.app()
        app.add_blank_key_config()
        self.assertEqual(app.key_configs[0].random_seconds, 0.100)

    def test_new_group_key_has_hundred_milliseconds_randomness(self):
        app = self.app()
        group = SequenceGroup()
        app.add_key_to_group(group)
        self.assertEqual(app.key_configs[0].random_seconds, 0.100)
        self.assertEqual(group.children[0].macro_id, app.key_configs[0].id_token)


if __name__ == '__main__':
    unittest.main()
