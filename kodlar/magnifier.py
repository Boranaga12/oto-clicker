"""Small, cursor-free GDI samples and a passive selection magnifier."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import tkinter as tk
from functools import lru_cache

from .platform_win import make_overlay_passive, move_overlay


def far_corner(point, bounds, size, previous=None, margin=16, clearance=100):
    left, top, right, bottom = bounds
    width, height = min(size, right-left), min(size, bottom-top)
    pad = min(margin, max(0, (right-left-width)//2), max(0, (bottom-top-height)//2))
    corners = [(left+pad, top+pad), (right-width-pad, top+pad),
               (left+pad, bottom-height-pad), (right-width-pad, bottom-height-pad)]
    x, y = point
    if previous in corners:
        px, py = previous
        if not (px-clearance <= x <= px+width+clearance and
                py-clearance <= y <= py+height+clearance):
            return previous
    return max(corners, key=lambda p: (x-p[0]-width/2)**2+(y-p[1]-height/2)**2)


@lru_cache(maxsize=1)
def _monitor_api():
    class Info(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
    user = ctypes.windll.user32
    user.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user.MonitorFromPoint.restype = ctypes.c_void_p
    user.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(Info)]
    return user, Info


def monitor_work_area(x, y):
    user, Info = _monitor_api()
    info = Info()
    info.size = ctypes.sizeof(info)
    handle = user.MonitorFromPoint(wintypes.POINT(x, y), 2)
    if not user.GetMonitorInfoW(handle, ctypes.byref(info)):
        raise OSError("Monitör bilgisi okunamadı")
    return (info.work.left, info.work.top, info.work.right, info.work.bottom)


@lru_cache(maxsize=1)
def _capture_api():
    """Declare the native ABI once, rather than on every preview frame."""
    class Header(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
                    ("height", wintypes.LONG), ("planes", wintypes.WORD),
                    ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                    ("image_size", wintypes.DWORD), ("xppm", wintypes.LONG),
                    ("yppm", wintypes.LONG), ("used", wintypes.DWORD),
                    ("important", wintypes.DWORD)]
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetDC.argtypes, user.GetDC.restype = [ctypes.c_void_p], ctypes.c_void_p
    user.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.CreateCompatibleDC.argtypes, gdi.CreateCompatibleDC.restype = [ctypes.c_void_p], ctypes.c_void_p
    gdi.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi.SelectObject.argtypes, gdi.SelectObject.restype = [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_void_p
    gdi.DeleteObject.argtypes = gdi.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
                             wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    return user, gdi, Header


def capture_patch(x, y, size=25):
    """Return PPM bytes and the center color; all native resources are released."""
    if os.name != "nt":
        raise OSError("Windows ekran yakalama gerekli")
    if not isinstance(size, int) or size < 1 or size > 101 or size % 2 == 0:
        raise ValueError("Ekran örneği boyutu 1–101 arasında tek sayı olmalı")
    user, gdi, Header = _capture_api()
    desktop = user.GetDC(None)
    memory = bitmap = old = None
    try:
        memory = gdi.CreateCompatibleDC(desktop) if desktop else None
        bitmap = gdi.CreateCompatibleBitmap(desktop, size, size) if memory else None
        if not bitmap:
            raise OSError("Ekran örneği oluşturulamadı")
        old = gdi.SelectObject(memory, bitmap)
        # SRCCOPY excludes layered selection windows and the hardware cursor.
        if not gdi.BitBlt(memory, 0, 0, size, size, desktop, x-size//2, y-size//2, 0x00CC0020):
            raise OSError("Ekran örneği okunamadı")
        gdi.SelectObject(memory, old)
        old = None
        header = Header(ctypes.sizeof(Header), size, -size, 1, 32)
        buffer = ctypes.create_string_buffer(size*size*4)
        if gdi.GetDIBits(memory, bitmap, 0, size, buffer, ctypes.byref(header), 0) != size:
            raise OSError("Ekran örneği dönüştürülemedi")
        raw = buffer.raw
        rgb = bytearray(size*size*3)
        rgb[0::3] = raw[2::4]
        rgb[1::3] = raw[1::4]
        rgb[2::3] = raw[0::4]
        center = (size//2*size+size//2)*3
        color = "#" + rgb[center:center+3].hex()
        return f"P6\n{size} {size}\n255\n".encode()+rgb, color
    finally:
        if old and memory:
            gdi.SelectObject(memory, old)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory:
            gdi.DeleteDC(memory)
        if desktop:
            user.ReleaseDC(None, desktop)


class SelectionMagnifier(tk.Toplevel):
    SIZE = 335
    ZOOM = 13
    SAMPLE_SIZE = 25

    def __init__(self, parent):
        super().__init__(parent)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.999)
        self.configure(bg="#66788e")
        self.position = None
        self.bounds = None
        self._last_frame = None
        self._image_size = None
        self.canvas = tk.Canvas(self, width=325, height=325, bg="#111111",
                                bd=0, highlightthickness=4)
        self.canvas.pack(padx=1, pady=1)
        self._image_id = self.canvas.create_image(4, 4, anchor="nw")
        self._dot = self.canvas.create_oval(90, 90, 92, 92, width=0, fill="white")
        self.update_idletasks()
        try:
            self._handle = make_overlay_passive(self.winfo_id())
        except (OSError, tk.TclError):
            self.destroy()
            raise

    def show_point(self, x, y):
        bounds = monitor_work_area(x, y)
        size = min(self.SIZE, bounds[2]-bounds[0], bounds[3]-bounds[1])
        previous = self.position if bounds == self.bounds else None
        position = far_corner((x, y), bounds, size, previous)
        moved = position != self.position or bounds != self.bounds
        if moved:
            self.geometry(f"{size}x{size}")
            self.position = position
            self.bounds = bounds
            move_overlay(self._handle, position[0], position[1], size)
        sample_size = max(1, min(self.SAMPLE_SIZE, (size-10)//self.ZOOM))
        if sample_size % 2 == 0:
            sample_size -= 1
        ppm, color = capture_patch(x, y, sample_size)
        if ppm != self._last_frame:
            self._image = tk.PhotoImage(master=self, data=ppm, format="PPM").zoom(self.ZOOM)
            image_size = sample_size*self.ZOOM
            if self._image_size != image_size:
                self._image_size = image_size
                self.canvas.configure(width=image_size, height=image_size)
                center = 4+image_size/2
                self.canvas.coords(self._dot, center-1, center-1, center+1, center+1)
            self.canvas.itemconfigure(self._image_id, image=self._image)
            self.canvas.configure(highlightbackground=color, highlightcolor=color)
            brightness = sum(int(color[i:i+2], 16) for i in (1, 3, 5))
            self.canvas.itemconfigure(self._dot, fill="black" if brightness > 382 else "white")
            self.canvas.tag_raise(self._dot)
            self._last_frame = ppm
        if moved or not self.winfo_viewable():
            self.deiconify()
            # Mapping can restore Tk's geometry; use physical coordinates again.
            move_overlay(self._handle, position[0], position[1], size)
        return color
