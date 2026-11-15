"""Physical keyboard scan codes for games that do not consume text key events."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class KeyboardInput(ctypes.Structure):
    _fields_ = [('vk', wintypes.WORD), ('scan', wintypes.WORD),
                ('flags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('extra', ctypes.c_size_t)]


class MouseInput(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                ('data', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]


class InputData(ctypes.Union):
    _fields_ = [('keyboard', KeyboardInput), ('mouse', MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [('kind', wintypes.DWORD), ('data', InputData)]


SCAN_CODES = {'w': 0x11, 'a': 0x1e, 's': 0x1f, 'd': 0x20}


def send_movement_key(key, pressed, fallback):
    if os.name != 'nt':
        (fallback.press if pressed else fallback.release)(key)
        return
    event = Input(kind=1)
    event.data.keyboard.scan = SCAN_CODES[key]
    event.data.keyboard.flags = 0x0008 | (0 if pressed else 0x0002)
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
        raise OSError(ctypes.get_last_error(), 'Oyun hareket tuşunu kabul etmedi; uygulama ve oyun yetkilerini kontrol edin.')
