from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kodlar.config import AppConfig, load_config, save_config
from kodlar.profile_store import default_profiles, load_profiles, reset_profiles, save_profiles


class StorageTests(unittest.TestCase):
    def test_reset_removes_macros_groups_and_old_recovery_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            save_profiles({"active_profile": "Oyun", "profiles": {"Oyun": [{"key": "x"}]},
                           "groups": {"Oyun": [{"name": "Grup"}]}}, path)
            self.assertEqual(reset_profiles(path), default_profiles())
            self.assertEqual(load_profiles(path), default_profiles())
            # Recovery must also remain empty after a later corrupt write.
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_profiles(path), default_profiles())

    def test_profile_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            data = {
                "active_profile": "Oyun",
                "profiles": {"Oyun": [{"key": "x"}]},
                "groups": {"Oyun": [{"name": "Sıra", "children": []}]},
            }
            save_profiles(data, path)
            loaded = load_profiles(path)
            self.assertEqual(loaded["active_profile"], "Oyun")
            self.assertEqual(loaded["profiles"]["Oyun"][0]["key"], "x")
            self.assertEqual(loaded["groups"]["Oyun"][0]["name"], "Sıra")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_invalid_profile_document_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            path.write_text("{bozuk", encoding="utf-8")
            loaded = load_profiles(path)
            self.assertIn(loaded["active_profile"], loaded["profiles"])
            self.assertEqual(len(list(Path(directory).glob("profiles.corrupt-*.json"))), 1)

    def test_corrupt_profile_is_recovered_from_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            original = {
                "active_profile": "Oyun",
                "profiles": {"Oyun": [{"key": "f8"}]},
            }
            save_profiles(original, path)
            save_profiles(original, path)  # creates the last-known-good backup
            path.write_text("{bozuk", encoding="utf-8")

            loaded = load_profiles(path)

            self.assertEqual(loaded["active_profile"], "Oyun")
            self.assertEqual(loaded["profiles"]["Oyun"][0]["key"], "f8")
            self.assertTrue(path.exists())

    def test_settings_are_atomic_and_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            save_config(AppConfig(panic_key="f8"), path)
            self.assertEqual(load_config(path).panic_key, "f8")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_invalid_settings_are_quarantined_and_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.ini"
            path.write_text("panic_key without a section", encoding="utf-8")

            loaded = load_config(path)

            self.assertEqual(loaded.panic_key, "esc")
            self.assertTrue(path.exists())
            self.assertEqual(len(list(Path(directory).glob("settings.corrupt-*.ini"))), 1)


if __name__ == "__main__":
    unittest.main()
