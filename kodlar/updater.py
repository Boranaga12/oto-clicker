"""Public GitHub release updates; preferences and the virtualenv stay untouched."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

RELEASE_URL = 'https://github.com/Boranaga12/oto-clicker/releases/latest/download/'
MAX_BYTES = 25 * 1024 * 1024
ROOT_FILES = {'baslat.bat', 'hata_ayikla.bat', 'pyproject.toml', 'README.md'}


def version_number(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('Geçersiz sürüm numarası')
    return tuple(map(int, value.split('.')))


def fetch(name: str) -> bytes:
    request = urllib.request.Request(RELEASE_URL + name, headers={'User-Agent': 'ArikMakro-Updater'})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Güncelleme paketi boyut sınırını aşıyor')
    return data


def allowed_path(name: str) -> Path:
    path = PurePosixPath(name)
    if '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts:
        raise ValueError('Güvenli olmayan paket yolu')
    if not path.parts or path.parts[0] != 'oto-clicker':
        raise ValueError('Geçersiz paket kökü')
    relative = PurePosixPath(*path.parts[1:])
    valid = str(relative) in ROOT_FILES or (
        len(relative.parts) == 2 and relative.parts[0] == 'kodlar'
        and (relative.suffix == '.py' or relative.name in {'requirements.txt', 'README.md'})
    ) or (
        len(relative.parts) == 3 and relative.parts[:2] == ('kodlar', 'assets')
        and relative.suffix in {'.png', '.ico', '.svg'}
    )
    if not valid:
        raise ValueError(f'Paketin değiştiremeyeceği dosya: {relative}')
    return Path(*relative.parts)


def unpack(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        files = [info for info in bundle.infolist() if not info.is_dir()]
        if len(files) > 1000 or sum(info.file_size for info in files) > MAX_BYTES:
            raise ValueError('Güncelleme paketi çok büyük')
        names = set()
        for info in files:
            relative = allowed_path(info.filename)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Paket sembolik bağlantı içeriyor')
            key = str(relative).casefold()
            if key in names:
                raise ValueError('Tekrarlanan paket dosyası')
            names.add(key)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
    for required in ('baslat.bat', 'kodlar/launcher.py', 'kodlar/__init__.py', 'kodlar/requirements.txt'):
        if not (destination / required).is_file():
            raise ValueError(f'Eksik güncelleme dosyası: {required}')


def prepare_update(install: Path, current_version: str, cache: Path) -> Path | None:
    try:
        manifest = json.loads(fetch('update.json'))
    except urllib.error.HTTPError as error:
        if error.code == 404:  # No release has been published yet.
            return None
        raise
    version = manifest['version']
    if version_number(version) <= version_number(current_version):
        return None
    checksum = manifest['sha256']
    if not re.fullmatch(r'[0-9a-f]{64}', checksum):
        raise ValueError('Güncelleme özeti geçersiz')
    data = fetch('arik-makro.zip')
    if hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError('Güncellemenin SHA-256 doğrulaması başarısız')
    cache.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='update-', dir=cache))
    try:
        archive = stage / 'release.zip'
        archive.write_bytes(data)
        unpack(archive, stage / 'payload')
        packaged_version = (stage / 'payload/kodlar/__init__.py').read_text(encoding='utf-8')
        if f'__version__ = "{version}"' not in packaged_version:
            raise ValueError('Paket sürümü ile yayın bilgisi uyuşmuyor')
        # A dependency/toolchain migration needs the normal installer, not a live swap.
        if (stage / 'payload/kodlar/requirements.txt').read_bytes() != (install / 'kodlar/requirements.txt').read_bytes():
            raise ValueError('Bağımlılıklar değişti; bu sürümü GitHub üzerinden indirip baslat.bat ile kurun.')
        return stage
    except Exception:
        shutil.rmtree(stage)
        raise


def install_payload(stage: Path, install: Path) -> None:
    if (install / '.git').exists():
        raise ValueError('Git çalışma kopyası otomatik olarak değiştirilemez')
    payload = stage / 'payload'
    files = sorted(path for path in payload.rglob('*') if path.is_file())
    backup = stage / 'backup'
    replaced = []
    try:
        for source in files:
            relative = allowed_path('oto-clicker/' + source.relative_to(payload).as_posix())
            target = install / relative
            if not target.resolve().is_relative_to(install.resolve()):
                raise ValueError('Hedef kurulum klasörü dışında')
            old = backup / relative
            existed = target.exists()
            if existed:
                old.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, old)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + '.update-tmp')
            try:
                shutil.copy2(source, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            replaced.append((target, old, existed))
    except Exception:
        for target, old, existed in reversed(replaced):
            if existed:
                shutil.copy2(old, target)
            else:
                target.unlink(missing_ok=True)
        raise


def schedule_install(stage: Path, install: Path) -> None:
    helper = stage / 'apply_update.py'
    shutil.copy2(__file__, helper)
    subprocess.Popen(
        [sys.executable, str(helper), '--apply', str(stage), str(install), str(os.getpid())],
        cwd=stage, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )


def apply_after_exit(stage: Path, install: Path, pid: int) -> None:
    import ctypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if handle:
        try:
            if kernel.WaitForSingleObject(handle, 120000) != 0:
                raise RuntimeError('Uygulamanın kapanması beklenirken süre doldu')
        finally:
            kernel.CloseHandle(handle)
    elif ctypes.get_last_error() != 87:  # ERROR_INVALID_PARAMETER: process already exited.
        raise ctypes.WinError(ctypes.get_last_error())
    error_message = None
    try:
        install_payload(stage, install)
    except Exception as error:
        error_message = f'Güncelleme yüklenemedi:\n{error}'
    if error_message:
        ctypes.windll.user32.MessageBoxW(None, error_message, 'Arık Makro', 0x10)
    subprocess.Popen([sys.executable, '-m', 'kodlar.launcher'], cwd=install)
    if not error_message:
        shutil.rmtree(stage, ignore_errors=True)


if __name__ == '__main__':
    if len(sys.argv) == 5 and sys.argv[1] == '--apply' and os.name == 'nt':
        try:
            apply_after_exit(Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]))
        except Exception as error:
            import ctypes
            import traceback
            try:
                (Path(sys.argv[2]) / 'update-error.log').write_text(traceback.format_exc(), encoding='utf-8')
            except OSError:
                pass
            ctypes.windll.user32.MessageBoxW(None, f'Güncelleme uygulanamadı:\n{error}', 'Arık Makro', 0x10)
