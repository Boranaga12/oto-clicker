from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime
from copy import deepcopy
from pathlib import Path
from typing import Any

from .app_paths import writable_data_file


LOGGER = logging.getLogger(__name__)
DEFAULT_PROFILE = "Varsayılan"
_LOCK = threading.RLock()


def default_profiles() -> dict[str, Any]:
    return {
        "active_profile": DEFAULT_PROFILE,
        "profiles": {DEFAULT_PROFILE: []},
        "groups": {DEFAULT_PROFILE: []},
        "positions": {DEFAULT_PROFILE: {}},
    }


def _normalise(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return default_profiles()

    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        profiles = {DEFAULT_PROFILE: []}
    profiles = {
        str(name): rows if isinstance(rows, list) else []
        for name, rows in profiles.items()
    }

    active = str(data.get("active_profile", DEFAULT_PROFILE))
    if active not in profiles:
        active = next(iter(profiles))

    groups = data.get("groups")
    if not isinstance(groups, dict):
        groups = {}
    groups = {
        str(name): rows if isinstance(rows, list) else []
        for name, rows in groups.items()
    }
    for name in profiles:
        groups.setdefault(name, [])
    positions = data.get('positions', {})
    if not isinstance(positions, dict):
        positions = {}
    positions = {name: positions.get(name, {}) if isinstance(positions.get(name), dict) else {}
                 for name in profiles}

    return {
        "active_profile": active,
        "profiles": profiles,
        "groups": groups,
        "positions": positions,
    }


def _backup_path(path: Path) -> Path:
    return path.with_suffix(f"{path.suffix}.bak")


def _read_profiles(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return _normalise(json.load(stream))


def _quarantine_corrupt_file(path: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = path.with_name(f"{path.stem}.corrupt-{timestamp}{path.suffix}")
    try:
        os.replace(path, destination)
        LOGGER.warning("Bozuk profil dosyası %s olarak saklandı.", destination.name)
    except OSError:
        LOGGER.exception("Bozuk profil dosyası karantinaya alınamadı: %s", path)


def load_profiles(path: Path | None = None) -> dict[str, Any]:
    path = path or writable_data_file("profiles.json")
    with _LOCK:
        if not path.exists():
            data = default_profiles()
            save_profiles(data, path)
            return data
        try:
            return _read_profiles(path)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            LOGGER.error("%s okunamadı: %s", path.name, exc)

            backup = _backup_path(path)
            if backup.exists():
                try:
                    recovered = _read_profiles(backup)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    LOGGER.exception("Profil yedeği de okunamadı: %s", backup)
                else:
                    _quarantine_corrupt_file(path)
                    save_profiles(recovered, path)
                    LOGGER.warning("Profiller yedek dosyadan kurtarıldı.")
                    return recovered

            _quarantine_corrupt_file(path)
            fallback = default_profiles()
            try:
                save_profiles(fallback, path)
            except RuntimeError:
                LOGGER.exception("Varsayılan profil belgesi oluşturulamadı: %s", path)
            return fallback


def save_profiles(data: dict[str, Any], path: Path | None = None) -> None:
    """Profili yarım dosya bırakmadan atomik olarak kaydet."""
    path = path or writable_data_file("profiles.json")
    clean_data = _normalise(deepcopy(data))
    path.parent.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.stem}-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temp_name = stream.name
                json.dump(clean_data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                shutil.copy2(path, _backup_path(path))
            os.replace(temp_name, path)
        except OSError as exc:
            raise RuntimeError(f"{path.name} kaydedilemedi: {exc}") from exc
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass


def reset_profiles(path: Path | None = None) -> dict[str, Any]:
    """Clear profiles and their recovery backup so deleted macros cannot return."""
    data = default_profiles()
    with _LOCK:
        save_profiles(data, path)
        save_profiles(data, path)
    return data
