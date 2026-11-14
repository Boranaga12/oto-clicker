from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kodlar import app_paths


class AppPathTests(unittest.TestCase):
    def test_profiles_migrate_from_previous_local_app_data_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roaming = base / "Roaming"
            local = base / "Local"
            source = base / "Install" / "kodlar"
            old_profile = local / app_paths.APP_DIRECTORY_NAME / "profiles.json"
            old_backup = old_profile.with_suffix(".json.bak")
            old_profile.parent.mkdir(parents=True)
            old_profile.write_text('{"active_profile":"Eski"}', encoding="utf-8")
            old_backup.write_text('{"active_profile":"Yedek"}', encoding="utf-8")

            with (
                patch.dict(
                    "os.environ",
                    {"APPDATA": str(roaming), "LOCALAPPDATA": str(local)},
                    clear=False,
                ),
                patch.object(app_paths, "SOURCE_DIRECTORY", source),
            ):
                destination = app_paths.writable_data_file("profiles.json")

            self.assertEqual(
                destination,
                roaming / app_paths.APP_DIRECTORY_NAME / "profiles.json",
            )
            self.assertEqual(destination.read_text(encoding="utf-8"), '{"active_profile":"Eski"}')
            self.assertEqual(
                destination.with_suffix(".json.bak").read_text(encoding="utf-8"),
                '{"active_profile":"Yedek"}',
            )

    def test_existing_roaming_profile_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roaming = base / "Roaming"
            local = base / "Local"
            destination = roaming / app_paths.APP_DIRECTORY_NAME / "profiles.json"
            legacy = local / app_paths.APP_DIRECTORY_NAME / "profiles.json"
            destination.parent.mkdir(parents=True)
            legacy.parent.mkdir(parents=True)
            destination.write_text("yeni", encoding="utf-8")
            legacy.write_text("eski", encoding="utf-8")

            with patch.dict(
                "os.environ",
                {"APPDATA": str(roaming), "LOCALAPPDATA": str(local)},
                clear=False,
            ):
                resolved = app_paths.writable_data_file("profiles.json")

            self.assertEqual(resolved.read_text(encoding="utf-8"), "yeni")

    def test_profile_survives_installation_directory_removal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roaming = base / "Roaming"
            source = base / "Install" / "kodlar"
            source.mkdir(parents=True)
            (source / "profiles.json").write_text("kalıcı profil", encoding="utf-8")

            with (
                patch.dict(
                    "os.environ",
                    {"APPDATA": str(roaming), "LOCALAPPDATA": str(base / "Local")},
                    clear=False,
                ),
                patch.object(app_paths, "SOURCE_DIRECTORY", source),
            ):
                destination = app_paths.writable_data_file("profiles.json")
                (source / "profiles.json").unlink()
                source.rmdir()
                resolved_after_reinstall = app_paths.writable_data_file("profiles.json")

            self.assertEqual(resolved_after_reinstall, destination)
            self.assertEqual(destination.read_text(encoding="utf-8"), "kalıcı profil")
            self.assertEqual(
                destination.with_suffix(".json.bak").read_text(encoding="utf-8"),
                "kalıcı profil",
            )


if __name__ == "__main__":
    unittest.main()
