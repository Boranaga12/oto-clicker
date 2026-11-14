"""Build a small updater-compatible ZIP and integrity manifest from tracked source."""
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kodlar.updater import allowed_path, version_number


def build(version: str, output: Path) -> None:
    version_number(version)
    output.mkdir(parents=True, exist_ok=True)
    files = [*ROOT.joinpath('kodlar').glob('*.py'), *ROOT.joinpath('kodlar/assets').glob('*')]
    files += [ROOT / name for name in ('baslat.bat', 'hata_ayikla.bat', 'pyproject.toml', 'README.md', 'kodlar/README.md', 'kodlar/requirements.txt')]
    archive = output / 'arik-makro.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            relative = path.relative_to(ROOT).as_posix()
            allowed_path('oto-clicker/' + relative)
            data = path.read_bytes()
            if relative == 'kodlar/__init__.py':
                data = re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', data.decode()).encode()
            elif relative == 'pyproject.toml':
                data = re.sub(r'^version = "[^"]+"', f'version = "{version}"', data.decode(), flags=re.MULTILINE).encode()
            bundle.writestr('oto-clicker/' + relative, data)
    manifest = {'version': version, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
    (output / 'update.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    build(sys.argv[1], Path(sys.argv[2]))
