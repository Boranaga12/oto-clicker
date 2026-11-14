from __future__ import annotations

import os
import shutil
import logging
from pathlib import Path


APP_DIRECTORY_NAME = "ArikMakro"
SOURCE_DIRECTORY = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)


def data_directory() -> Path:
    """Sürümler ve kurulum klasörleri arasında kalıcı kullanıcı veri dizini."""
    roaming_app_data = os.environ.get("APPDATA")
    if roaming_app_data:
        return Path(roaming_app_data) / APP_DIRECTORY_NAME
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DIRECTORY_NAME
    return Path.home() / ".arik-makro"


def _legacy_directories() -> list[Path]:
    """Önceki sürümlerin veri yazmış olabileceği dizinleri döndür."""
    current = data_directory()
    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / APP_DIRECTORY_NAME)
    candidates.extend((SOURCE_DIRECTORY, SOURCE_DIRECTORY.parent))

    unique: list[Path] = []
    for candidate in candidates:
        if candidate != current and candidate not in unique:
            unique.append(candidate)
    return unique


def _backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".bak")


def _migrate_file(source: Path, destination: Path) -> bool:
    """Ana dosyayı ve varsa kurtarma yedeğini kalıcı alana kopyala."""
    source_backup = _backup_path(source)
    if not source.exists() and not source_backup.exists():
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    selected_source = source if source.exists() else source_backup
    shutil.copy2(selected_source, destination)
    if source_backup.exists():
        shutil.copy2(source_backup, _backup_path(destination))
    else:
        shutil.copy2(selected_source, _backup_path(destination))
    return True


def writable_data_file(filename: str, *, migrate_legacy: bool = True) -> Path:
    """Kalıcı veri yolunu çöz ve eski sürüm verisini yalnızca bir kez taşı."""
    destination = data_directory() / filename
    if migrate_legacy and not destination.exists():
        for directory in _legacy_directories():
            source = directory / filename
            try:
                if _migrate_file(source, destination):
                    LOGGER.info("%s kalıcı kullanıcı alanına taşındı: %s", filename, destination)
                    break
            except OSError:
                LOGGER.exception("%s dosyası %s konumundan taşınamadı", filename, source)
    return destination
