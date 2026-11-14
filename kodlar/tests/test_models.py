from __future__ import annotations

import unittest

from kodlar.models import (
    key_config_from_dict,
    key_config_to_dict,
)


class ModelTests(unittest.TestCase):
    def test_invalid_values_are_normalised(self) -> None:
        config = key_config_from_dict({
            "key": "f1",
            "interval_seconds": "bozuk",
            "random_seconds": -4,
            "click_x": "12",
        })
        self.assertEqual(config.interval_seconds, 1.0)
        self.assertEqual(config.random_seconds, 0.0)
        self.assertEqual(config.click_x, 12)
        self.assertTrue(config.id_token)

    def test_legacy_action_is_migrated(self) -> None:
        config = key_config_from_dict({
            "chain_type": "Diğerlerini Sustur",
            "chain_mute_duration": "2.5",
        })
        self.assertEqual(config.actions[0]["type"], "Sustur")
        self.assertEqual(config.actions[0]["mute_duration"], 2.5)

    def test_round_trip_keeps_actions(self) -> None:
        source = {
            "key": "tab",
            "interval_seconds": 3,
            "random_seconds": 1,
            "action_chain": True,
            "actions": [{"type": "Aktif Et", "target_id": "abc"}],
        }
        restored = key_config_from_dict(key_config_to_dict(key_config_from_dict(source)))
        self.assertTrue(restored.action_chain)
        self.assertEqual(restored.actions[0]["target_id"], "abc")

    def test_non_finite_timings_fall_back_to_safe_values(self) -> None:
        config = key_config_from_dict({
            "interval_seconds": "nan",
            "random_seconds": "inf",
        })
        self.assertEqual(config.interval_seconds, 1.0)
        self.assertEqual(config.random_seconds, 0.0)

    def test_three_decimal_precision(self) -> None:
        config = key_config_from_dict({
            "key": "sol klik",
            "interval_seconds": 0.768,
            "random_seconds": 0.125,
        })
        self.assertAlmostEqual(config.interval_seconds, 0.768, places=3)
        self.assertAlmostEqual(config.random_seconds, 0.125, places=3)

if __name__ == "__main__":
    unittest.main()
