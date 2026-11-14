from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_release import build
from kodlar.updater import unpack


class ReleaseLayoutTests(unittest.TestCase):
    def test_distribution_has_only_launcher_and_code_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            build('2.1.2', output)
            archive = output / 'arik-makro.zip'
            with zipfile.ZipFile(archive) as bundle:
                entries = {name.split('/')[1] for name in bundle.namelist()}
                self.assertEqual(entries, {'baslat.bat', 'kodlar'})
                self.assertIn('oto-clicker/kodlar/hata_ayikla.py', bundle.namelist())
            unpack(archive, output / 'extracted')
            launcher = (output / 'extracted/baslat.bat').read_text()
            self.assertIn('set "VENV_DIR=%~dp0kodlar\\.venv"', launcher)
            self.assertNotIn('%~dp0.venv', launcher)
            self.assertTrue((output / 'extracted/kodlar/assets/mouse.ico').exists())


if __name__ == '__main__':
    unittest.main()
