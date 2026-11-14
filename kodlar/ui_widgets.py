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
