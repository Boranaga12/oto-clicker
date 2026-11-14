from __future__ import annotations

import ctypes
import os
from types import TracebackType


if os.name == "nt":
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32
    _user32.GetDC.argtypes = [ctypes.c_void_p]
    _user32.GetDC.restype = ctypes.c_void_p
    _user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _user32.ReleaseDC.restype = ctypes.c_int
    _gdi32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    _gdi32.GetPixel.restype = ctypes.c_uint32
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    _kernel32.CreateMutexW.restype = ctypes.c_void_p
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = ctypes.c_bool


class SingleInstanceLock:
    """Process-wide Windows mutex preventing duplicate global input hooks."""

    def __init__(self, name: str = "Local\\ArikMakro") -> None:
        self.name = name
        self._handle: int | None = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        handle = _kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            # A mutex failure should be logged by the caller, not make the app unusable.
            return True
        self._handle = handle
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS

    def release(self) -> None:
        if self._handle and os.name == "nt":
            _kernel32.CloseHandle(self._handle)
        self._handle = None


def parse_hex_color(value: str) -> tuple[int, int, int] | None:
    value = value.strip().removeprefix("#")
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def is_color_close(first: str, second: str, threshold: int = 25) -> bool:
    left = parse_hex_color(first)
    right = parse_hex_color(second)
    if left is None or right is None:
        return False
    return all(abs(a - b) <= threshold for a, b in zip(left, right))


class PixelSampler:
    """Bir worker boyunca masaüstü DC'sini tekrar kullanarak piksel okur."""

    def __init__(self) -> None:
        self._hdc: int | None = None

    def __enter__(self) -> "PixelSampler":
        if os.name == "nt":
            self._hdc = _user32.GetDC(None)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._hdc and os.name == "nt":
            _user32.ReleaseDC(None, self._hdc)
        self._hdc = None

    def get(self, x: int, y: int) -> str:
        if os.name != "nt":
            return ""

        owns_dc = self._hdc is None
        hdc = self._hdc or _user32.GetDC(None)
        if not hdc:
            return ""
        try:
            color = _gdi32.GetPixel(hdc, int(x), int(y))
        finally:
            if owns_dc and hdc:
                _user32.ReleaseDC(None, hdc)

        if color == 0xFFFFFFFF:
            return ""
        red = color & 0xFF
        green = (color >> 8) & 0xFF
        blue = (color >> 16) & 0xFF
        return f"#{red:02x}{green:02x}{blue:02x}"


def get_pixel_color_win32(x: int, y: int) -> str:
    return PixelSampler().get(x, y)


def enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def set_application_identity() -> None:
    """Keep the application's own icon and grouping in the Windows taskbar."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p("Boranaga12.ArikMakro")
        )
    except (AttributeError, OSError):
        pass
