from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UITheme:
    background: str = "#11161f"
    card: str = "#1c2532"
    text_primary: str = "#f3f4f6"
    text_secondary: str = "#9ca3af"
    accent: str = "#3b82f6"
    accent_hover: str = "#2563eb"
    danger: str = "#c95161"
    danger_hover: str = "#dc2626"
    success: str = "#239d83"
    success_hover: str = "#059669"
    border: str = "#303e50"
    input_background: str = "#303e50"


DEFAULT_THEME = UITheme()


class ScrollableFrame(tk.Frame):
    def __init__(self, container: tk.Misc, background: str, **kwargs) -> None:
        super().__init__(container, **kwargs)
        self.configure(bg=background)
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.scrollable_frame = tk.Frame(self.canvas, bg=background)
        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.scrollable_frame,
            anchor="nw",
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollable_frame.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_content)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_content(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def _bind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(-(event.delta // 120), "units")


class PointMarker(tk.Toplevel):
    """A passive point with a transparent sampling center, not an input overlay."""

    SIZE = 9
    RADIUS = 4
    TRANSPARENT = "#000001"

    def __init__(self, parent, x: int, y: int, color: str, protected_points=()):
        import os
        from .platform_win import make_overlay_passive
        super().__init__(parent)
        try:
            self.withdraw()
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            if os.name == "nt":
                self.attributes("-transparentcolor", self.TRANSPARENT)
                self.attributes("-disabled", True)
            else:
                self.attributes("-alpha", 0.7)
            self.configure(bg=self.TRANSPARENT)
            self.canvas = tk.Canvas(self, width=self.SIZE, height=self.SIZE,
                                    bg=self.TRANSPARENT, highlightthickness=0)
            self.canvas.pack()
            self.color = color
            self.point = (x, y)
            self.protected = frozenset(protected_points) | {self.point}
            self.geometry(f"{self.SIZE}x{self.SIZE}{x - self.RADIUS:+d}{y - self.RADIUS:+d}")
            self.update_idletasks()
            self._handle = make_overlay_passive(self.winfo_id())
            self.deiconify()
            self.update_idletasks()
            self._handle = make_overlay_passive(self.winfo_id())
            self.move(x, y)
        except Exception:
            self.destroy()
            raise

    def move(self, x: int, y: int) -> None:
        from .platform_win import move_overlay
        self.point = (x, y)
        left, top = x - self.RADIUS, y - self.RADIUS
        if self._handle is not None:
            move_overlay(self._handle, left, top, self.SIZE)
        else:
            self.geometry(f"{self.SIZE}x{self.SIZE}{left:+d}{top:+d}")
        self.paint()

    def set_color(self, color: str) -> None:
        if self.color != color:
            self.color = color
            self.paint()

    def protect(self, points) -> None:
        protected = frozenset(points)
        if self.protected != protected:
            self.protected = protected
            self.paint()

    def paint(self) -> None:
        self.canvas.delete("all")
        self.canvas.create_oval(1, 1, 7, 7, outline="#11161f", width=3)
        self.canvas.create_oval(2, 2, 6, 6, outline=self.color, width=2)
        # Preserve all sampled pixels, even where two nearby markers overlap.
        for x, y in self.protected | {self.point}:
            dx, dy = x - self.point[0] + self.RADIUS, y - self.point[1] + self.RADIUS
            if -1 <= dx <= self.SIZE and -1 <= dy <= self.SIZE:
                self.canvas.create_rectangle(dx - 1, dy - 1, dx + 2, dy + 2,
                                             fill=self.TRANSPARENT, outline="")
