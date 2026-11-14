from __future__ import annotations

import configparser
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .app_paths import writable_data_file


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AppConfig:
    panic_key: str = "esc"


def read_setting(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    fallback: str = "esc"
) -> str:
    try:
        if parser.has_option(section, option):
            value = parser.get(section, option).strip().lower()
            return value or fallback
        return fallback
    except configparser.Error:
        return fallback


def load_config(path: Path | None = None) -> AppConfig:
    path = path or writable_data_file("settings.ini")
    if not path.exists():
        save_config(AppConfig(), path)

    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeError) as exc:
        LOGGER.error("%s okunamadı: %s", path.name, exc)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        quarantine = path.with_name(f"{path.stem}.corrupt-{timestamp}{path.suffix}")
        try:
            os.replace(path, quarantine)
        except OSError:
            LOGGER.exception("Bozuk ayar dosyası karantinaya alınamadı: %s", path)
        fallback = AppConfig()
        try:
            save_config(fallback, path)
        except RuntimeError:
            LOGGER.exception("Varsayılan ayarlar kaydedilemedi: %s", path)
        return fallback

    panic_key = "esc"
    if parser.has_section("settings"):
        panic_key = read_setting(parser, "settings", "panic_key", "esc")

    return AppConfig(panic_key=panic_key)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    path = path or writable_data_file("settings.ini")
    parser = configparser.ConfigParser()
    parser["settings"] = {
        "panic_key": config.panic_key
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temp_name = stream.name
            parser.write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except OSError as exc:
        raise RuntimeError(f"{path.name} kaydedilemedi: {exc}") from exc
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
