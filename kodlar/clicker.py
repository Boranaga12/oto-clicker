"""Eski içe aktarımlar için geriye dönük uyumluluk katmanı."""

from .engine import RandomizedAutoClicker, get_key_name, get_mouse_button_name
from .models import KeyConfig
from .platform_win import get_pixel_color_win32, is_color_close, parse_hex_color
from .profile_store import load_profiles, save_profiles

__all__ = [
    "KeyConfig",
    "RandomizedAutoClicker",
    "get_key_name",
    "get_mouse_button_name",
    "get_pixel_color_win32",
    "is_color_close",
    "load_profiles",
    "parse_hex_color",
    "save_profiles",
]
