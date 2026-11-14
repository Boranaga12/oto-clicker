from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


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
    """Read the current desktop; never reuse a DC across a display-mode switch."""

    def __enter__(self) -> "PixelSampler":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        pass

    def get(self, x: int, y: int) -> str:
        if os.name != "nt":
            return ""
        bounds = screen_bounds()
        if bounds:
            left, top, width, height = bounds
            if not (left <= x < left + width and top <= y < top + height):
                return ""
        hdc = _user32.GetDC(None)
        if not hdc:
            return ""
        try:
            color = _gdi32.GetPixel(hdc, int(x), int(y))
        finally:
            _user32.ReleaseDC(None, hdc)
        if color == 0xFFFFFFFF:
            return ""
        return f"#{color & 0xff:02x}{(color >> 8) & 0xff:02x}{(color >> 16) & 0xff:02x}"


def screen_bounds() -> tuple[int, int, int, int] | None:
    if os.name != "nt":
        return None
    values = tuple(_user32.GetSystemMetrics(index) for index in (76, 77, 78, 79))
    return values if values[2] > 0 and values[3] > 0 else None


def physical_cursor_position() -> tuple[int, int] | None:
    if os.name != "nt":
        return None
    point = wintypes.POINT()
    reader = getattr(_user32, "GetPhysicalCursorPos", _user32.GetCursorPos)
    reader.argtypes = [ctypes.POINTER(wintypes.POINT)]
    reader.restype = wintypes.BOOL
    if not reader(ctypes.byref(point)):
        return None
    return point.x, point.y


def get_pixel_color_win32(x: int, y: int) -> str:
    return PixelSampler().get(x, y)


def enable_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        setter = _user32.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = wintypes.BOOL
        if setter(ctypes.c_void_p(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return
    except (AttributeError, OSError):
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) >= 0:
            return
    except (AttributeError, OSError):
        pass
    try:
        _user32.SetProcessDPIAware()
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


def flush_desktop() -> None:
    """Wait until a hidden capture overlay has left the desktop compositor."""
    if os.name == "nt":
        try:
            ctypes.windll.dwmapi.DwmFlush()
        except (AttributeError, OSError):
            pass


def foreground_is_ours() -> bool:
    """Never place editing overlays over a foreground fullscreen game."""
    if os.name != "nt":
        return True
    _user32.GetForegroundWindow.restype = ctypes.c_void_p
    _user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    handle = _user32.GetForegroundWindow()
    if not handle:
        return False
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    return pid.value == os.getpid()


def foreground_description() -> str:
    if os.name != "nt":
        return "Windows dışında"
    _user32.GetForegroundWindow.restype = ctypes.c_void_p
    handle = _user32.GetForegroundWindow()
    if not handle:
        return "ön pencere yok"
    _user32.GetWindowTextW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    title = ctypes.create_unicode_buffer(256)
    _user32.GetWindowTextW(handle, title, len(title))
    rect = wintypes.RECT()
    area = None
    if _user32.GetWindowRect(handle, ctypes.byref(rect)):
        area = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    dpi = None
    try:
        _user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
        _user32.GetDpiForWindow.restype = wintypes.UINT
        dpi = _user32.GetDpiForWindow(handle)
    except AttributeError:
        pass
    return f"pencere={title.value}, alan={area}, DPI={dpi}"
