from __future__ import annotations

import queue
from collections import deque
from functools import wraps
import os
from pathlib import Path
import time
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog

from pynput.mouse import Button

from . import __version__
from .app_paths import data_directory
from .updater import prepare_update, schedule_install
from .release_notes import CURRENT_NOTES, HISTORY
from .config import AppConfig, save_config
from .engine import RandomizedAutoClicker
from .models import (
    KeyConfig,
    clamp_click_interval,
    key_config_from_dict,
    key_config_to_dict,
    new_id,
)
from .platform_win import flush_desktop, get_pixel_color_win32, screen_bounds, foreground_is_ours, foreground_description, physical_cursor_position
from .profile_store import load_profiles, reset_profiles, save_profiles
from .sequences import (
    SequenceGroup,
    WritingBlock, writing_layout, move_group_item,
    flatten_groups,
    SequenceItem,
    group_macro_ids,
    grouped_macro_ids,
    iter_groups,
    sequence_group_to_dict,
    sequence_groups_from_list,
)
from .ui_widgets import DEFAULT_THEME, ScrollableFrame, PointMarker


PIXEL_PICK_OFFSET = 8


def editable_only(method):
    """Also reject queued callbacks during the gap before Tk is visually locked."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        if self.clicker.is_running:
            return
        if args and method.__name__ != "toggle_group_enabled":
            target = args[0]
            if isinstance(target, SequenceGroup) and not target.enabled:
                return
            if isinstance(target, KeyConfig):
                for group in getattr(self, "sequence_groups", []):
                    if not group.enabled and target.id_token in group_macro_ids(group):
                        return
        return method(self, *args, **kwargs)
    return guarded


class ClickerApp:
    def __init__(self, root: tk.Tk, clicker: RandomizedAutoClicker) -> None:
        self.root = root
        self.clicker = clicker
        
        self.last_add_time = 0.0
        self.config_widgets = {}
        self.group_widgets: dict[str, dict[str, tk.Widget]] = {}
        self.active_group_ids: set[str] = set()
        self.markers = {}
        self._marker_save_job: str | None = None
        self._queue_job: str | None = None
        self._shutting_down = False
        self._update_stage: Path | None = None
        self._locked_widget_states = {}
        self._locked_menu_states = {}
        self._capture_overlay = None
        self._pending_pixel_pick = None
        self._pending_click_pick = None
        self._preview_job = None
        self._selection_preview = None
        self._preview_kind = None
        self._preview_config = None
        self._preview_swatch = None
        
        theme = DEFAULT_THEME
        self.bg_color = theme.background
        self.card_color = theme.card
        self.text_primary = theme.text_primary
        self.text_secondary = theme.text_secondary
        self.accent_color = theme.accent
        self.accent_hover = theme.accent_hover
        self.danger_color = theme.danger
        self.danger_hover = theme.danger_hover
        self.success_color = theme.success
        self.success_hover = theme.success_hover
        self.border_color = theme.border
        self.input_bg = theme.input_background
        
        self.root.configure(bg=self.bg_color)
        self.root.title(f"Arık Makro · v{__version__}")
        self.root.geometry("480x640")
        self.root.resizable(False, True)
        self.root.minsize(480, 360)
        self.root.maxsize(480, self.root.winfo_screenheight())
        icon_directory = Path(__file__).with_name("assets")
        self._window_icon = tk.PhotoImage(file=str(icon_directory / "mouse.png"))
        self.root.iconphoto(True, self._window_icon)
        if os.name == "nt":
            self.root.iconbitmap(str(icon_directory / "mouse.ico"))
        
        # En ustte kalma (Always on Top) varsayilan etkin
        self.root.attributes("-topmost", True)
        
        # Profil verilerini yukle
        self.profiles_data = load_profiles()
        self.active_profile = self.profiles_data.get("active_profile", "Varsayılan")
        self.load_active_profile_configs()
        
        self.log_queue = queue.Queue()
        self.clicker.log_callback = self.enqueue_log
        self.clicker.state_callback = self.on_state_changed
        self.clicker.refresh_callback = self.enqueue_refresh
        self.clicker.persist_callback = self.enqueue_persist
        self.clicker.sequence_state_callback = self.on_sequence_state_changed
        self.clicker.configure(
            self.key_configs,
            sequence_groups=self.sequence_groups,
        )
        
        self.capturing_target = None
        
        # 1. Ust Durum & Kacis Tusu Alani
        self.header_frame = tk.Frame(
            self.root, bg=self.card_color, padx=10, pady=8, 
            bd=0, highlightbackground=self.border_color, highlightthickness=1
        )
        self.header_frame.pack(side="top", fill="x", padx=10, pady=(10, 5))
        
        # Header Row 1: Title, Topmost toggle & Status Badge
        top_row = tk.Frame(self.header_frame, bg=self.card_color)
        top_row.pack(fill="x")
        
        title_lbl = tk.Label(
            top_row, text="ARIK MAKRO", 
            bg=self.card_color, fg=self.text_primary, font=("Segoe UI", 10, "bold")
        )
        title_lbl.pack(side="left")
        tk.Label(
            top_row, text=f"v{__version__}", bg=self.input_bg, fg=self.accent_color,
            font=("Segoe UI", 8, "bold"), padx=5, pady=2,
        ).pack(side="left", padx=(6, 2))
        notes_button = tk.Canvas(
            top_row, width=22, height=22, bg=self.card_color, bd=0,
            highlightthickness=0, cursor="hand2", takefocus=True,
        )
        notes_button.create_oval(3, 3, 19, 19, outline=self.text_secondary, tags="ring")
        notes_button.create_text(11, 11, text="i", fill=self.text_secondary,
                                 font=("Segoe UI", 9, "bold"), tags="letter")
        notes_button.pack(side="left")
        for event_name in ("<Button-1>", "<Return>", "<space>"):
            notes_button.bind(event_name, lambda _event: self.show_release_notes())
        def tint_notes_button(color):
            notes_button.itemconfigure("ring", outline=color)
            notes_button.itemconfigure("letter", fill=color)
        for event_name in ("<Enter>", "<FocusIn>"):
            notes_button.bind(event_name, lambda _event: tint_notes_button(self.accent_color))
        for event_name in ("<Leave>", "<FocusOut>"):
            notes_button.bind(event_name, lambda _event: tint_notes_button(self.text_secondary))

        
        self.status_badge = tk.Button(
            top_row, text="SİSTEM KAPALI", bg=self.danger_color, fg="white",
            font=("Segoe UI", 8, "bold"), padx=10, pady=4, bd=0,
            activebackground=self.danger_hover, activeforeground="white",
            cursor="hand2", command=self.toggle_system
        )
        self.status_badge.pack(side="right")
        
        self.topmost_var = tk.IntVar(value=1)
        self.chk_topmost = tk.Checkbutton(
            top_row, text="Üstte", variable=self.topmost_var,
            bg=self.card_color, fg=self.text_secondary, selectcolor=self.input_bg,
            activebackground=self.card_color, activeforeground=self.text_primary,
            font=("Segoe UI", 8), command=self.toggle_topmost
        )
        self.chk_topmost.pack(side="right", padx=(0, 10))
        
        # 2. Profil Secim Alani
        self.profile_frame = tk.Frame(
            self.root, bg=self.card_color, padx=10, pady=6,
            bd=0, highlightbackground=self.border_color, highlightthickness=1
        )
        self.profile_frame.pack(side="top", fill="x", padx=10, pady=(5, 5))
        
        tk.Label(
            self.profile_frame, text="Profil:", 
            bg=self.card_color, fg=self.text_secondary, font=("Segoe UI", 9)
        ).pack(side="left")
        
        self.profile_var = tk.StringVar()
        self.profile_menu = self.create_modern_option_menu(
            self.profile_frame, self.profile_var, ["Varsayılan"], self.on_profile_menu_select
        )
        self.profile_menu.pack(side="left", padx=5)
        self.profile_menu.configure(width=14)

        self.panic_btn = tk.Button(
            self.profile_frame, text=self.clicker.app_config.panic_key.upper(), font=("Segoe UI", 8, "bold"),
            bg=self.input_bg, fg=self.text_primary, bd=0, activebackground=self.border_color,
            activeforeground="white", padx=8, pady=2,
            command=lambda: self.start_key_capture("panic", None, self.panic_btn)
        )
        self.panic_btn.pack(side="left", padx=8)


        
        profile_actions = tk.Menubutton(
            self.profile_frame, text="⋯", font=("Segoe UI", 12, "bold"),
            bg=self.card_color, fg=self.text_secondary, bd=0,
            activebackground=self.input_bg, activeforeground=self.text_primary,
            cursor="hand2", padx=8,
        )
        profile_actions.pack(side="right")
        actions = tk.Menu(profile_actions, tearoff=False, bg=self.card_color,
                          fg=self.text_primary, activebackground=self.accent_color)
        actions.add_command(label="Yeni profil", command=self.create_profile)
        actions.add_command(label="İsmi değiştir", command=self.rename_profile)
        actions.add_command(label="Profili sil", command=self.delete_profile)
        profile_actions.configure(menu=actions)

        # 3. Tuş Atama Listesi (Card Panel)
        self.list_header = tk.Frame(self.root, bg=self.bg_color, padx=10)
        self.list_header.pack(side="top", fill="x")
        
        tk.Label(
            self.list_header, text="Makrolar",
            bg=self.bg_color, fg=self.text_primary, font=("Segoe UI", 9, "bold")
        ).pack(side="left")
        
        self.add_key_btn = tk.Button(
            self.list_header, text="+ Tuş", font=("Segoe UI", 8, "bold"),
            bg=self.accent_color, fg="white", bd=0, activebackground=self.accent_hover,
            activeforeground="white", padx=10, pady=3, command=self.add_blank_key_config
        )
        self.add_key_btn.pack(side="right")

        self.add_group_btn = tk.Button(
            self.list_header, text="+ Grup", font=("Segoe UI", 8, "bold"),
            bg=self.success_color, fg="white", bd=0,
            activebackground=self.success_hover, activeforeground="white",
            padx=10, pady=3, command=self.add_root_group,
        )
        self.add_group_btn.pack(side="right", padx=(0, 5))
        
        self.list_container = ScrollableFrame(self.root, background=self.bg_color)
        self.list_container.pack(fill="both", expand=True, padx=10, pady=(5, 5))
        
        # 4. Log Alanı (Alt)
        self.console_area = tk.Frame(
            self.root, bg=self.card_color, bd=0, highlightbackground=self.border_color, highlightthickness=1
        )
        self.console_area.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        
        # Log Başlığı ve Temizleme Butonu
        log_header = tk.Frame(self.console_area, bg=self.card_color, padx=6, pady=4)
        log_header.pack(fill="x")
        
        tk.Label(
            log_header, text="Kayıtlar", bg=self.card_color, fg=self.text_secondary, font=("Segoe UI", 8, "bold")
        ).pack(side="left")
        
        clear_btn = tk.Button(
            log_header, text="Temizle", font=("Segoe UI", 7, "bold"),
            bg=self.input_bg, fg=self.text_secondary, bd=0, activebackground=self.border_color,
            activeforeground="white", padx=8, pady=1, command=self.clear_console_logs
        )
        clear_btn.pack(side="right")
        
        self.log_container_frame = tk.Frame(self.console_area, bg=self.card_color)
        self.log_container_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        
        self.init_console()
        self.refresh_profile_combobox()
        self.refresh_keys_list_ui()
        
        self._queue_job = self.root.after(100, self.process_queue)
        self.root.bind_all("<Button-1>", self.unfocus_entries)
        self.update_running_ui(self.clicker.enabled_event.is_set())
        install = Path(__file__).resolve().parent.parent
        if os.name == "nt" and not (install / ".git").exists():
            threading.Thread(target=self.check_for_update, name="update-check", daemon=True).start()

    def show_release_notes(self) -> None:
        existing = getattr(self, "_notes_window", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        window = tk.Toplevel(self.root)
        self._notes_window = window
        window.title("Güncelleme Notları")
        window.configure(bg=self.card_color)
        window.transient(self.root)
        window.geometry("400x420")
        window.resizable(False, True)
        window.minsize(400, 260)
        window.maxsize(400, self.root.winfo_screenheight())
        window.attributes("-topmost", bool(self.topmost_var.get()))
        tk.Label(
            window, text="Yenilikler", bg=self.card_color, fg=self.text_primary,
            font=("Segoe UI", 12, "bold"), anchor="w",
        ).pack(fill="x", padx=16, pady=(16, 8))
        content = tk.Frame(window, bg=self.card_color)
        content.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        text = tk.Text(
            content, bg=self.card_color, fg=self.text_primary, wrap="word",
            font=("Segoe UI", 9), bd=0, highlightthickness=0,
            padx=2, pady=4, cursor="arrow", spacing3=7,
        )
        scrollbar = tk.Scrollbar(content, command=text.yview)
        scrollbar.pack(side="right", fill="y")
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        text.tag_configure("version", foreground=self.accent_color,
                           font=("Segoe UI", 10, "bold"), spacing1=6, spacing3=10)
        for version, notes in ((__version__, CURRENT_NOTES), *HISTORY):
            text.insert("end", f"v{version}\n", "version")
            for note in notes:
                text.insert("end", f"• {note}\n")
            text.insert("end", "\n")
        text.configure(state="disabled")

    def check_for_update(self) -> None:
        try:
            stage = prepare_update(
                Path(__file__).resolve().parent.parent,
                __version__, data_directory() / "updates",
            )
            if stage:
                self.log_queue.put(("update_ready", stage))
        except Exception as error:
            self.enqueue_log(f"Güncelleme kontrolü tamamlanamadı: {error}")

    def apply_pending_update(self) -> None:
        if self._update_stage is None or self.clicker.is_running or self.capturing_target is not None or self._pending_pixel_pick is not None or self._pending_click_pick is not None:
            return
        stage = self._update_stage
        self._update_stage = None
        try:
            self.save_current_configs_to_profiles(update_workers=False)
            schedule_install(stage, Path(__file__).resolve().parent.parent)
        except Exception as error:
            self.enqueue_log(f"Güncelleme başlatılamadı: {error}")
            return
        # Use the regular close path to release input hooks and the instance mutex.
        self.root.tk.call(self.root.protocol("WM_DELETE_WINDOW"))

    def shutdown(self) -> None:
        self._shutting_down = True
        self.finish_group_drag(None)
        self.cancel_pixel_pick()
        if self._queue_job is not None:
            try:
                self.root.after_cancel(self._queue_job)
            except tk.TclError:
                pass
            self._queue_job = None
        if self._marker_save_job is not None:
            self.root.after_cancel(self._marker_save_job)
            self._marker_save_job = None
            self.save_current_configs_to_profiles(update_workers=False)
        self.clicker.capturing_callback = None
        self.clicker.log_callback = None
        self.clicker.state_callback = None
        self.clicker.refresh_callback = None
        self.clicker.persist_callback = None
        self.clicker.sequence_state_callback = None
        for marker in self.markers.values():
            try:
                marker.destroy()
            except tk.TclError:
                pass
        self.markers.clear()

    def create_modern_option_menu(self, parent, variable, values, command=None) -> tk.OptionMenu:
        if not values:
            values = ["-"]
        menu_btn = tk.OptionMenu(parent, variable, *values, command=command)
        menu_btn.configure(
            bg=self.input_bg, fg=self.text_primary, 
            activebackground=self.border_color, activeforeground="white", 
            bd=0, highlightthickness=0, font=("Segoe UI", 8, "bold"),
            padx=6, pady=2
        )
        menu_btn["menu"].configure(
            bg=self.card_color, fg=self.text_primary, 
            activebackground=self.accent_color, activeforeground="white", 
            bd=1, relief="solid", font=("Segoe UI", 9)
        )
        return menu_btn

    @editable_only
    def on_marker_press(self, marker_window, event):
        marker_window._drag_x = event.x
        marker_window._drag_y = event.y
        marker_window._pending_pixel = None

    def focus_through_overlay(self, overlay: tk.Toplevel, x: int, y: int) -> None:
        """Ana GUI döngüsünü bloklamadan alttaki pencereye odak tıklaması ilet."""
        overlay.withdraw()

        def forward_click() -> None:
            if not overlay.winfo_exists():
                return
            with self.clicker.input_lock:
                original = self.clicker.mouse.position
                try:
                    self.clicker.mouse.position = (x, y)
                    self.clicker.mouse.click(Button.left)
                finally:
                    self.clicker.mouse.position = original
            self.root.after(200, restore_overlay)

        def restore_overlay() -> None:
            if overlay.winfo_exists():
                overlay.deiconify()
                overlay.lift()
                overlay.focus_force()

        self.root.after(50, forward_click)

    @editable_only
    def on_marker_drag(self, marker_window, event, config, marker_type):
        dx = event.x - marker_window._drag_x
        dy = event.y - marker_window._drag_y
        x = marker_window.winfo_x() + dx
        y = marker_window.winfo_y() + dy
        
        center_x = x + 50
        center_y = y + 28
        
        if marker_type == "screen":
            marker_window._pending_pixel = (center_x, center_y)
        elif marker_type == "click":
            config.click_x = center_x
            config.click_y = center_y
            cfg_id = id(config)
            if cfg_id in self.config_widgets:
                self.config_widgets[cfg_id]["loc_lbl"].configure(text=f" ({center_x}, {center_y})")
        marker_window.geometry(f"100x40+{x}+{y}")
        if marker_type != "screen":
            self.schedule_marker_save()

    @editable_only
    def on_screen_marker_release(self, marker, config):
        pending = getattr(marker, "_pending_pixel", None)
        if pending is None:
            return
        marker._pending_pixel = None
        x, y = pending
        color = self.sample_uncovered_pixel(x, y)
        widgets = self.config_widgets.get(id(config))
        if color and widgets:
            self.log_queue.put(("pixel_capture", (
                config, x, y, color, widgets["pixel_btn"],
                widgets["coord_lbl"], widgets["color_preview"],
            )))
        else:
            marker.geometry(f"100x40+{config.pixel_x-50}+{config.pixel_y-28}")
            self.clicker.log("Piksel okunamadı; önceki hedef korundu.")

    def draw_markers(self):
        if self._shutting_down:
            return
        desired = {}
        for config in self.key_configs:
            if config.has_pixel_target:
                desired[f"screen_{id(config)}"] = (config.pixel_x, config.pixel_y, "#f43f5e")
            if config.key.strip().lower() in {"sol klik", "left click", "sol tık", "sağ klik", "sag klik", "right click", "sağ tık", "orta klik", "middle click", "orta tık", "mouse x1", "mouse x2", "x1", "x2"} and config.has_click_target:
                desired[f"click_{id(config)}"] = (config.click_x, config.click_y, "#3b82f6")
        self._marker_target_points = [(x, y) for x, y, _color in desired.values()]
        for token in list(self.markers):
            if token not in desired:
                self.markers.pop(token).destroy()
        for token, (x, y, color) in desired.items():
            marker = self.markers.get(token)
            if marker is None or not marker.winfo_exists():
                try:
                    self.markers[token] = PointMarker(self.root, x, y, color, protected_points=self._marker_target_points)
                except (OSError, tk.TclError) as error:
                    self.clicker.log_activity("marker-error", f"İşaretçi gösterilemedi: {error}")
            elif marker.point != (x, y):
                marker.move(x, y)
        self.protect_marker_pixels()

    def protect_marker_pixels(self, extra=()):
        points = list(getattr(self, "_marker_target_points", [marker.point for marker in self.markers.values()]))
        points.extend(extra)
        preview = getattr(self, "_selection_preview", None)
        if preview is not None and preview.winfo_exists():
            points.append(preview.point)
        for marker in self.markers.values():
            marker.protect(points)
        if preview is not None and preview.winfo_exists():
            preview.protect(points)

    def begin_point_preview(self, kind, config):
        self._preview_kind = kind
        self._selection_clicked_point = None
        self._preview_failed = False
        self._preview_config = config
        widgets = self.config_widgets.get(id(config), {})
        self._preview_swatch = widgets.get("color_preview")
        self._preview_job = self.root.after(0, self.update_point_preview)

    def update_point_preview(self):
        self._preview_job = None
        if self._shutting_down or self.clicker.is_running or self._preview_kind is None:
            return
        point = getattr(self, "_selection_clicked_point", None)
        held = self.clicker._pixel_capture_down
        if point is None and isinstance(held, tuple) and len(held) == 2:
            point = held
        if point is None:
            point = physical_cursor_position()
        if point is None and os.name != "nt":
            point = self.root.winfo_pointerxy()
        if point is not None:
            x, y = point
            if self._preview_kind == "screen":
                x, y = x - PIXEL_PICK_OFFSET, y - PIXEL_PICK_OFFSET
            color = "#f43f5e" if self._preview_kind == "screen" else "#3b82f6"
            if self._selection_preview is None and not self._preview_failed:
                try:
                    self._selection_preview = PointMarker(self.root, x, y, color, protected_points=getattr(self, "_marker_target_points", ()))
                except (OSError, tk.TclError) as error:
                    self._preview_failed = True
                    self.clicker.log_activity("preview-error", f"Nokta önizlemesi gösterilemedi: {error}")
            elif self._selection_preview is not None and self._selection_preview.point != (x, y):
                self._selection_preview.move(x, y)
            self.protect_marker_pixels(extra=((x, y),))
            self.root.update_idletasks()
            flush_desktop()
            sampled = get_pixel_color_win32(x, y)
            if sampled:
                if self._selection_preview is not None:
                    self._selection_preview.set_color(sampled)
                if self._preview_swatch is not None and self._preview_swatch.winfo_exists():
                    self._preview_swatch.configure(bg=sampled)
        self._preview_job = self.root.after(20, self.update_point_preview)

    def stop_point_preview(self):
        job = getattr(self, "_preview_job", None)
        if job is not None:
            self.root.after_cancel(job)
        self._preview_job = None
        preview = getattr(self, "_selection_preview", None)
        if preview is not None and preview.winfo_exists():
            preview.destroy()
        self._selection_preview = None
        swatch = getattr(self, "_preview_swatch", None)
        config = getattr(self, "_preview_config", None)
        if swatch is not None and swatch.winfo_exists() and config is not None:
            swatch.configure(bg=config.target_color or self.input_bg)
        self._preview_swatch = None
        self._preview_config = None
        self._preview_kind = None
        self._selection_clicked_point = None
        self.protect_marker_pixels()

    @editable_only
    def toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get() == 1)

    def toggle_system(self) -> None:
        """Arayüzden sistemi güvenli biçimde başlat veya durdur."""
        self.root.focus_set()
        self.clicker.toggle_manual()
        self.update_running_ui(self.clicker.is_running)

    def enqueue_log(self, msg: str):
        self.log_queue.put(("log", msg))
        
    def on_state_changed(self, active: bool):
        self.log_queue.put(("state", active))

    def on_sequence_state_changed(self, group_id: str, active: bool) -> None:
        self.log_queue.put(("sequence_state", (group_id, active)))
        
    def enqueue_refresh(self):
        self.log_queue.put(("refresh", None))

    def enqueue_persist(self):
        self.log_queue.put(("persist", None))

    def save_profile_document(self) -> bool:
        try:
            save_profiles(self.profiles_data)
            return True
        except RuntimeError as exc:
            self.clicker.log(str(exc))
            return False

    def schedule_marker_save(self):
        """Sürükleme sırasında her pikselde diske yazmak yerine kaydı birleştir."""
        if self._marker_save_job is not None:
            self.root.after_cancel(self._marker_save_job)
        self._marker_save_job = self.root.after(250, self._flush_marker_save)

    @editable_only
    def _flush_marker_save(self):
        self._marker_save_job = None
        self.save_current_configs_to_profiles(update_workers=False)
        
    def process_queue(self):
        if self._shutting_down:
            return
        try:
            processed = 0
            while processed < 200:
                msg_type, data = self.log_queue.get_nowait()
                if msg_type == "update_ready":
                    self._update_stage = data
                    self.append_log_to_widget("Yeni sürüm hazır; makrolar durduğunda otomatik yüklenecek.")
                elif msg_type == "log":
                    self.append_log_to_widget(data)
                elif msg_type == "state":
                    self.update_running_ui(data)
                elif msg_type == "refresh":
                    self.update_checkbox_states()
                elif msg_type == "persist":
                    self.save_current_configs_to_profiles(update_workers=False)
                elif msg_type == "sequence_state":
                    group_id, active = data
                    if active:
                        self.active_group_ids.add(group_id)
                    else:
                        self.active_group_ids.discard(group_id)
                    self.update_group_states()
                elif msg_type == "capture":
                    self.handle_captured_key(data)
                elif msg_type == "click_pick_cancel":
                    if self._pending_click_pick is data:
                        self.cancel_pixel_pick()
                elif msg_type == "click_pick_result":
                    pending, x, y = data
                    if self._pending_click_pick is pending:
                        self.cancel_pixel_pick()
                        config, button, label = pending
                        if not self.clicker.is_running and any(config is item for item in self.key_configs):
                            self.log_queue.put(("click_capture", (config, x, y, button, label)))
                elif msg_type == "pixel_pick_cancel":
                    if self._pending_pixel_pick is data:
                        self.cancel_pixel_pick()
                        self.draw_markers()
                elif msg_type == "pixel_pick_point":
                    pending, x, y = data
                    if self._pending_pixel_pick is pending and not self.clicker.is_running:
                        self.sample_picked_pixel(pending, x, y)
                elif msg_type == "pixel_pick_result":
                    pending, x, y, color, bounds = data
                    if self._pending_pixel_pick is pending:
                        self.cancel_pixel_pick()
                        config, button, coord_lbl, preview = pending
                        if not self.clicker.is_running and any(config is item for item in self.key_configs):
                            if color:
                                self.log_queue.put(("pixel_capture", (config, x, y, color, button, coord_lbl, preview, bounds)))
                                self.clicker.log(f"Seçilen fiziksel piksel ({x}, {y}); ekran sınırları: {bounds}")
                            else:
                                self.clicker.log("Oyun pikseli okunamadı veya ekran modu değişti; önceki hedef korundu.")
                elif msg_type in {"pixel_capture", "click_capture"} and self.clicker.is_running:
                    self.log_queue.task_done()
                    processed += 1
                    continue
                elif msg_type == "pixel_capture":
                    config, x, y, color, btn, lbl, preview = data[:7]
                    config.pixel_x = x
                    config.pixel_y = y
                    config.target_color = color
                    config.pixel_screen_bounds = data[7] if len(data) > 7 else screen_bounds()
                    config.invert_color = False
                    self.save_current_configs_to_profiles(update_workers=False)
                    
                    if btn.winfo_exists():
                        btn.configure(text="Piksel Seç", bg=self.input_bg, fg=self.text_primary)
                    if lbl.winfo_exists():
                        lbl.configure(text=f" ({x}, {y})")
                    if preview.winfo_exists():
                        preview.configure(bg=color)
                        
                    self.clicker.log(f"Hedef piksel seçildi: {config.key.upper()} ({x}, {y}) - Renk: {color}")
                    self.draw_markers()
                elif msg_type == "click_capture":
                    config, x, y, btn, lbl = data
                    config.click_x = x
                    config.click_y = y
                    self.save_current_configs_to_profiles(update_workers=False)
                    
                    if btn.winfo_exists():
                        btn.configure(text="Konum Seç", bg=self.input_bg, fg=self.text_primary)
                    if lbl.winfo_exists():
                        lbl.configure(text=f" ({x}, {y})")
                        
                    self.clicker.log(f"{config.key.upper()} tıklama konumu seçildi: ({x}, {y})")
                    self.draw_markers()
                self.log_queue.task_done()
                processed += 1
        except queue.Empty:
            pass
        self.apply_pending_update()
        if self._shutting_down:
            return
        self._queue_job = self.root.after(
            10 if not self.log_queue.empty() else 100,
            self.process_queue,
        )

    def validate_float(self, action: str, value_if_allowed: str) -> bool:
        if action == '1': # Insertion
            if not value_if_allowed:
                return True
            separator_count = value_if_allowed.count('.') + value_if_allowed.count(',')
            if separator_count > 1:
                return False
            clean_val = value_if_allowed.replace('.', '').replace(',', '')
            if clean_val and not clean_val.isdigit():
                return False
            for sep in ('.', ','):
                if sep in value_if_allowed:
                    _, decimals = value_if_allowed.split(sep, 1)
                    if len(decimals) > 3:
                        return False
        return True

    def create_modern_entry(self, parent, width=10) -> tk.Entry:
        frame = tk.Frame(parent, bg=self.border_color, padx=1, pady=1)
        vcmd = (self.root.register(self.validate_float), '%d', '%P')
        entry = tk.Entry(
            frame, width=width, bg=self.input_bg, fg=self.text_primary, 
            bd=0, insertbackground=self.text_primary, font=("Segoe UI", 9),
            validate="key", validatecommand=vcmd
        )
        entry.pack(fill="both")
        entry.frame = frame
        return entry

    def init_console(self):
        self._log_selecting = False
        self._pending_log_lines = deque(maxlen=200)
        self.log_text = tk.Text(
            self.log_container_frame, bg="#0d1117", fg="#c9d1d9",
            font=("Consolas", 8), bd=0, highlightthickness=0,
            state="disabled", wrap="word", height=2, exportselection=False,
            selectbackground=self.accent_color, selectforeground="white"
        )
        
        scrollbar = tk.Scrollbar(self.log_container_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.bind("<ButtonPress-1>", self.begin_log_selection)
        self.log_text.bind("<ButtonRelease-1>", self.end_log_selection)


    def clear_console_logs(self):
        self._pending_log_lines.clear()
        self._log_selecting = False
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def unfocus_entries(self, event):
        # Text must retain focus for native mouse selection and Ctrl+C.
        if event.widget and not isinstance(event.widget, (tk.Entry, tk.Text)):
            self.root.focus_set()

    def begin_log_selection(self, _event):
        self._log_selecting = True
        self.log_text.focus_set()

    def end_log_selection(self, _event):
        self._log_selecting = False
        self.flush_log_buffer()

    def append_log_to_widget(self, msg: str):
        self._pending_log_lines.append(msg)
        self.flush_log_buffer()

    def flush_log_buffer(self):
        # Freeze the displayed text while it is being selected or copied.
        if self._log_selecting or self.log_text.tag_ranges("sel") or not self._pending_log_lines:
            return
        follow_end = self.log_text.yview()[1] >= 0.999
        messages = list(self._pending_log_lines)
        self._pending_log_lines.clear()
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, "\n".join(messages) + "\n")
        lines = int(self.log_text.index('end-1c').split('.')[0])
        if lines > 100:
            self.log_text.delete("1.0", f"{lines - 99}.0")
        self.log_text.configure(state="disabled")
        if follow_end:
            self.log_text.see(tk.END)

    def load_active_profile_configs(self):
        configs_list = self.profiles_data["profiles"].get(self.active_profile, [])
        self.key_configs = [
            key_config_from_dict(item) for item in configs_list if isinstance(item, dict)
        ]
        self.sequence_groups = sequence_groups_from_list(
            self.profiles_data.get("groups", {}).get(self.active_profile, [])
        )
        
    @editable_only
    def save_current_configs_to_profiles(
        self,
        update_workers: bool = False,
        update_sequences: bool = False,
    ) -> None:
        self.profiles_data["profiles"][self.active_profile] = [
            key_config_to_dict(config)
            for config in self.key_configs
        ]
        self.profiles_data.setdefault("groups", {})[self.active_profile] = [
            sequence_group_to_dict(group)
            for group in self.sequence_groups
        ]
        
        self.save_profile_document()
        self.clicker.configure(
            self.key_configs,
            sequence_groups=self.sequence_groups if update_sequences else None,
            restart=update_workers,
        )

    def refresh_profile_combobox(self):
        profile_names = list(self.profiles_data["profiles"].keys())
        menu = self.profile_menu["menu"]
        menu.delete(0, "end")
        for name in profile_names:
            menu.add_command(label=name, command=lambda val=name: self.on_profile_menu_select(val))
        self.profile_var.set(self.active_profile)

    @editable_only
    def on_profile_menu_select(self, val):
        self.profile_var.set(val)
        self.on_profile_changed()

    @editable_only
    def on_profile_changed(self, event=None):
        self.cancel_pixel_pick()
        self.save_current_configs_to_profiles(update_workers=False)
        new_profile = self.profile_var.get().strip()
        if new_profile in self.profiles_data["profiles"]:
            self.active_profile = new_profile
            self.profiles_data["active_profile"] = new_profile
            self.save_profile_document()
            
            self.load_active_profile_configs()
            self.clicker.configure(
                self.key_configs,
                sequence_groups=self.sequence_groups,
            )
            self.refresh_keys_list_ui()

    @editable_only
    def create_profile(self):
        name = simpledialog.askstring("Yeni Profil", "Profil ismini girin:", parent=self.root)
        if name and not self.clicker.is_running:
            name = name.strip()
            duplicate = next(
                (
                    existing
                    for existing in self.profiles_data["profiles"]
                    if existing.casefold() == name.casefold()
                ),
                None,
            )
            if len(name) > 40:
                messagebox.showerror("Hata", "Profil ismi en fazla 40 karakter olabilir.")
            elif name and duplicate is None:
                self.cancel_pixel_pick()
                self.profiles_data["profiles"][name] = []
                self.profiles_data.setdefault("groups", {})[name] = []
                
                self.active_profile = name
                self.profiles_data["active_profile"] = name
                self.save_profile_document()
                
                self.key_configs = []
                self.sequence_groups = []
                self.clicker.configure([], sequence_groups=[])
                self.refresh_profile_combobox()
                self.refresh_keys_list_ui()
            elif duplicate is not None:
                messagebox.showerror("Hata", "Bu isimde bir profil zaten mevcut.")

    @editable_only
    def rename_profile(self):
        old = self.active_profile
        name = simpledialog.askstring("Profil İsmi", "Yeni profil ismi:",
                                      initialvalue=old, parent=self.root)
        if name is None or self.clicker.is_running:
            return
        name = name.strip()
        if not name or len(name) > 40:
            messagebox.showerror("Hata", "Profil ismi 1–40 karakter olmalı.", parent=self.root)
            return
        if any(key != old and key.casefold() == name.casefold() for key in self.profiles_data["profiles"]):
            messagebox.showerror("Hata", "Bu isimde bir profil zaten mevcut.", parent=self.root)
            return
        if name == old:
            return
        self.cancel_pixel_pick()
        self.save_current_configs_to_profiles(update_workers=False)
        # Preserve profile order and both macro and group data, including writing sections.
        for section in ("profiles", "groups"):
            values = self.profiles_data.setdefault(section, {})
            self.profiles_data[section] = {name if key == old else key: value for key, value in values.items()}
        self.active_profile = name
        self.profiles_data["active_profile"] = name
        self.save_profile_document()
        self.refresh_profile_combobox()

    @editable_only
    def reset_all_profiles(self) -> None:
        if not messagebox.askyesno(
            "Tümünü Sıfırla",
            "Tüm profiller, gruplar ve tuş atamaları silinsin mi?\n"
            "Başlat/durdur kısayolu ESC olarak sıfırlanacak.",
            parent=self.root,
        ):
            return
        if self.clicker.is_running:
            return
        self.cancel_pixel_pick()
        self.clicker.set_enabled(False)
        if self._marker_save_job is not None:
            self.root.after_cancel(self._marker_save_job)
            self._marker_save_job = None
        self.clicker.configure([], sequence_groups=[])
        try:
            data = reset_profiles()
            config = AppConfig()
            save_config(config)
        except RuntimeError as exc:
            messagebox.showerror("Sıfırlama Hatası", str(exc), parent=self.root)
            return
        self.profiles_data = data
        self.active_profile = data["active_profile"]
        self.key_configs = []
        self.sequence_groups = []
        self.active_group_ids.clear()
        self.clicker.app_config = config
        self.panic_btn.configure(text=config.panic_key.upper())
        self.refresh_profile_combobox()
        self.refresh_keys_list_ui()

    @editable_only
    def delete_profile(self):
        if len(self.profiles_data["profiles"]) <= 1:
            messagebox.showinfo("Bilgi", "En az bir adet profil bulunmalıdır.")
            return
            
        if messagebox.askyesno("Onay", f"'{self.active_profile}' profilini silmek istiyor musunuz?") and not self.clicker.is_running:
            self.cancel_pixel_pick()
            del self.profiles_data["profiles"][self.active_profile]
            self.profiles_data.get("groups", {}).pop(self.active_profile, None)
                
            first_key = list(self.profiles_data["profiles"].keys())[0]
            self.active_profile = first_key
            self.profiles_data["active_profile"] = first_key
            self.save_profile_document()
            
            self.load_active_profile_configs()
            self.clicker.configure(
                self.key_configs,
                sequence_groups=self.sequence_groups,
            )
            self.refresh_profile_combobox()
            self.refresh_keys_list_ui()

    @editable_only
    def start_key_capture(self, target_type: str, config: KeyConfig | None = None, button_widget: tk.Button | None = None):
        self.cancel_pixel_pick()
        if self.capturing_target is not None:
            _, _, prev_btn = self.capturing_target
            if prev_btn and prev_btn.winfo_exists():
                original_text = getattr(
                    prev_btn,
                    "_capture_original_text",
                    prev_btn.cget("text"),
                )
                prev_btn.configure(
                    text=original_text,
                    bg=self.input_bg,
                    fg=self.text_primary,
                )
        
        self.capturing_target = (target_type, config, button_widget)
        if button_widget:
            button_widget._capture_original_text = button_widget.cget("text")
            button_widget.configure(text="Basın...", bg=self.accent_color, fg="white")
        self.clicker.capturing_callback = self.on_key_captured

    def on_key_captured(self, key_name: str):
        self.log_queue.put(("capture", key_name))

    @editable_only
    def handle_captured_key(self, key_name: str):
        if self.capturing_target is None:
            return
            
        target_type, config, button_widget = self.capturing_target
        self.capturing_target = None
        self.clicker.capturing_callback = None
        
        if target_type == "panic":
            self.clicker.app_config.panic_key = key_name
            try:
                save_config(self.clicker.app_config)
            except RuntimeError as exc:
                self.clicker.log(str(exc))
            if button_widget:
                button_widget.configure(text=key_name.upper(), bg=self.input_bg, fg=self.text_primary)
            self.clicker.log(f"Sistem başlatma/durdurma kısayolu değiştirildi: {key_name.upper()}")
            
        elif target_type == "key" and config:
            config.key = key_name
            config.interval_seconds = clamp_click_interval(config.key, config.interval_seconds)
            widgets = self.config_widgets.get(id(config))
            if widgets:
                entry = widgets["int_entry"]
                entry.delete(0, tk.END)
                entry.insert(0, f"{config.interval_seconds:.3f}")
            self.clicker.log(f"Tetikleme tuşu değiştirildi: {key_name.upper()}")
            
            is_mouse = key_name.lower() in (
                "sol klik", "left click", "sol tık",
                "sağ klik", "sag klik", "right click", "sağ tık",
                "orta klik", "middle click", "orta tık",
                "mouse x1", "mouse x2", "x1", "x2",
            )
            if not is_mouse:
                config.click_x = -1
                config.click_y = -1
                
            self.save_current_configs_to_profiles(update_workers=False)
            
            if button_widget:
                button_widget.configure(text=key_name.upper(), bg=self.input_bg, fg=self.text_primary)
                
            cfg_id = id(config)
            if cfg_id in self.config_widgets:
                frame = self.config_widgets[cfg_id]["click_frame"]
                if is_mouse:
                    frame.pack(fill="x", padx=5, pady=1)
                else:
                    frame.pack_forget()
                self.fade_widgets(self.config_widgets[cfg_id]["card"], not config.enabled)
            self.draw_markers()

    @editable_only
    def add_root_group(self) -> None:
        group = SequenceGroup(name=f"Grup {len(self.sequence_groups) + 1}")
        self.sequence_groups.append(group)
        self.save_current_configs_to_profiles(
            update_workers=False,
            update_sequences=True,
        )
        self.refresh_keys_list_ui()
        self._scroll_to_bottom()

    @editable_only
    def add_key_to_group(self, group: SequenceGroup) -> None:
        config = KeyConfig(
            key="sol klik",
            interval_seconds=1.0,
            random_seconds=0.100,
            enabled=True,
            id_token=new_id(),
        )
        self.key_configs.append(config)
        group.children.append(
            SequenceItem(
                kind="macro",
                macro_id=config.id_token,
            )
        )
        self.save_current_configs_to_profiles(
            update_workers=True,
            update_sequences=True,
        )
        self.refresh_keys_list_ui()

    @editable_only
    def save_group_name(self, group: SequenceGroup, entry: tk.Entry) -> None:
        name = entry.get().strip()[:40] or "İsimsiz Grup"
        group.name = name
        entry.delete(0, tk.END)
        entry.insert(0, name)
        self.save_current_configs_to_profiles(update_workers=False)

    @editable_only
    def delete_group(self, group: SequenceGroup) -> None:
        macro_ids = group_macro_ids(group)
        if not messagebox.askyesno(
            "Grubu Sil",
            (
                f"“{group.name}” ve içindeki {len(macro_ids)} tuş silinsin mi?\n\n"
                "Bu işlem alt grupları da kaldırır."
            ),
            parent=self.root,
        ):
            return
        if self.clicker.is_running:
            return
        self._remove_group(self.sequence_groups, group.id_token)
        self.key_configs = [
            config
            for config in self.key_configs
            if config.id_token not in macro_ids
        ]
        self.save_current_configs_to_profiles(
            update_workers=True,
            update_sequences=True,
        )
        self.refresh_keys_list_ui()

    def _remove_group(
        self,
        groups: list[SequenceGroup],
        group_id: str,
    ) -> bool:
        for index, group in enumerate(list(groups)):
            if group.id_token == group_id:
                groups.pop(index)
                return True
            for item_index, item in enumerate(list(group.children)):
                if item.kind != "group" or item.group is None:
                    continue
                if item.group.id_token == group_id:
                    group.children.pop(item_index)
                    return True
                if self._remove_group([item.group], group_id):
                    return True
        return False

    def _remove_macro_from_groups(self, macro_id: str) -> bool:
        changed = False
        for group in iter_groups(self.sequence_groups):
            original_length = len(group.children)
            group.children[:] = [
                item
                for item in group.children
                if not (item.kind == "macro" and item.macro_id == macro_id)
            ]
            changed = changed or len(group.children) != original_length
        return changed

    def _find_config(self, macro_id: str) -> KeyConfig | None:
        return next(
            (config for config in self.key_configs if config.id_token == macro_id),
            None,
        )

    def _scroll_to_bottom(self) -> None:
        self.list_container.scrollable_frame.update_idletasks()
        self.list_container.canvas.configure(
            scrollregion=self.list_container.canvas.bbox("all")
        )
        self.list_container.canvas.yview_moveto(1.0)

    @editable_only
    def toggle_writing(self, group, macro_id):
        saved_blocks = [(b, b.opening, b.closing) for b in group.writing_blocks]
        roles, _errors = writing_layout(group)
        role, block = roles.get(macro_id, (None, None))
        if role == "body":
            return
        if role == "open":
            group.writing_blocks.remove(block)
        elif role == "close":
            block.closing = ""
        else:
            pending = next((b for b in group.writing_blocks if not b.closing or not b.opening), None)
            ids = [i.macro_id for i in group.children]
            if pending is not None:
                if not pending.opening and pending.closing in ids and ids.index(macro_id) < ids.index(pending.closing):
                    pending.opening = macro_id
                elif pending.opening in ids and ids.index(macro_id) > ids.index(pending.opening):
                    pending.closing = macro_id
                else:
                    self.refresh_keys_list_ui()
                    return
            else:
                group.writing_blocks.append(WritingBlock(macro_id))
        # Reject crossing a completed block when selecting a closing boundary.
        _roles_after, errors_after = writing_layout(group)
        if errors_after and all(b.opening and b.closing for b in group.writing_blocks):
            group.writing_blocks[:] = [b for b, _a, _z in saved_blocks]
            for b, a, z in saved_blocks:
                b.opening, b.closing = a, z
        self.save_current_configs_to_profiles(update_workers=False, update_sequences=True)
        self.refresh_keys_list_ui()

    @editable_only
    def repair_writing(self, group):
        if not messagebox.askyesno("Yazı bölümü", "Eksik yazı bölümleri kaldırılsın mı? İçindeki tuşlar normal tuşlara dönüşür.", parent=self.root):
            return
        if self.clicker.is_running:
            return
        previous = list(group.writing_blocks)
        group.writing_blocks.clear()
        for block in previous:
            group.writing_blocks.append(block)
            if writing_layout(group)[1]:
                group.writing_blocks.pop()
        self.save_current_configs_to_profiles(update_workers=False, update_sequences=True)
        self.refresh_keys_list_ui()

    @editable_only
    def move_group_key(self, group, macro_id, target):
        if move_group_item(group, macro_id, target):
            view = self.list_container.canvas.yview()[0]
            self.save_current_configs_to_profiles(update_workers=False, update_sequences=True)
            self.refresh_keys_list_ui()
            self.list_container.canvas.update_idletasks()
            self.list_container.canvas.yview_moveto(view)

    def step_group_key(self, group, macro_id, direction):
        ids = [i.macro_id for i in group.children]
        index = ids.index(macro_id)
        roles, _ = writing_layout(group)
        role, block = roles.get(macro_id, (None, None))
        end = ids.index(block.closing)+1 if role == "open" else index+1
        target = index-1 if direction < 0 else end+1
        # Whole blocks jump over adjacent whole blocks with a single arrow.
        neighbor = index-1 if direction < 0 else end
        if role == "open" and 0 <= neighbor < len(ids) and ids[neighbor] in roles:
            _, other = roles[ids[neighbor]]
            target = ids.index(other.opening) if direction < 0 else ids.index(other.closing)+1
        self.move_group_key(group, macro_id, target)

    def start_group_drag(self, event, group, macro_id):
        if self.clicker.is_running:
            return
        self._group_drag = (group, macro_id)
        line = tk.Frame(self.list_container.canvas, bg=self.accent_color, height=2)
        self._group_drop_line = line
        self.drag_group_key(event)

    def drag_group_key(self, event):
        if self.clicker.is_running or not getattr(self, "_group_drag", None):
            return
        self._group_drag_pointer = event.y_root
        self._paint_group_drop()
        if not getattr(self, "_group_drag_job", None):
            self._group_drag_job = self.root.after(40, self._scroll_group_drag)

    def _paint_group_drop(self):
        group, _macro_id = self._group_drag
        cards = self._group_cards.get(group.id_token, [])
        y = self._group_drag_pointer
        target = len(cards)
        boundary = cards[-1][1].winfo_rooty()+cards[-1][1].winfo_height() if cards else y
        for index, (_key, card) in enumerate(cards):
            if y < card.winfo_rooty()+card.winfo_height()/2:
                target, boundary = index, card.winfo_rooty()
                break
        self._group_drag_target = target
        canvas = self.list_container.canvas
        self._group_drop_line.place(x=4, y=max(0, min(canvas.winfo_height()-2, boundary-canvas.winfo_rooty())), width=max(1, canvas.winfo_width()-8))

    def _scroll_group_drag(self):
        self._group_drag_job = None
        if not getattr(self, "_group_drag", None):
            return
        if self.clicker.is_running:
            self.finish_group_drag(None)
            return
        canvas = self.list_container.canvas
        y = self._group_drag_pointer-canvas.winfo_rooty()
        if y < 24:
            canvas.yview_scroll(-1, "units")
        elif y > canvas.winfo_height()-24:
            canvas.yview_scroll(1, "units")
        self._paint_group_drop()
        self._group_drag_job = self.root.after(40, self._scroll_group_drag)

    def finish_group_drag(self, event):
        drag = getattr(self, "_group_drag", None)
        self._group_drag = None
        job = getattr(self, "_group_drag_job", None)
        if job:
            self.root.after_cancel(job)
            self._group_drag_job = None
        line = getattr(self, "_group_drop_line", None)
        if line is not None:
            line.destroy()
            self._group_drop_line = None
        if drag and event is not None:
            group, macro_id = drag
            self.move_group_key(group, macro_id, self._group_drag_target)

    def draw_sequence_group(
        self,
        group: SequenceGroup,
        parent: tk.Misc,
    ) -> None:
        border_color = self.accent_color
        outer = tk.Frame(
            parent,
            bg=border_color,
            padx=1,
            pady=1,
        )
        outer.pack(fill="x", padx=(3, 0), pady=3)

        card = tk.Frame(outer, bg=self.card_color, padx=4, pady=4)
        card.pack(fill="x")

        header = tk.Frame(card, bg=self.card_color)
        header.pack(fill="x")

        enabled_var = tk.IntVar(value=int(group.enabled))
        group_check = tk.Checkbutton(header, text="", variable=enabled_var,
            bg=self.card_color, fg=self.text_primary, selectcolor=self.input_bg,
            activebackground=self.card_color, activeforeground=self.text_primary,
            bd=0, highlightthickness=0, padx=0, pady=0,
            command=lambda g=group, v=enabled_var: self.toggle_group_enabled(g, v))
        group_check.var = enabled_var
        group_check.pack(side="left", padx=(0, 4))

        name_entry = tk.Entry(
            header,
            bg=self.input_bg,
            fg=self.text_primary,
            insertbackground=self.text_primary,
            bd=0,
            font=("Segoe UI", 9, "bold"), width=8,
        )
        name_entry.insert(0, group.name)
        name_entry._saved_value = lambda g=group: g.name
        name_entry.pack(side="left", fill="x", expand=True, ipady=2)
        name_entry.bind(
            "<FocusOut>",
            lambda _event, g=group, entry=name_entry: self.save_group_name(g, entry),
        )
        name_entry.bind(
            "<Return>",
            lambda _event, g=group, entry=name_entry: (
                self.save_group_name(g, entry),
                self.root.focus_set(),
            ),
        )

        delete_button = tk.Button(
            header,
            text="Sil",
            bg=self.danger_color,
            fg="white",
            activebackground=self.danger_hover,
            activeforeground="white",
            bd=0,
            font=("Segoe UI", 7, "bold"),
            command=lambda g=group: self.delete_group(g),
        )
        delete_button.pack(side="right", padx=(4, 0))

        controls = tk.Frame(header, bg=self.card_color)
        controls.pack(side="right", padx=4)

        add_key_button = tk.Button(
            controls,
            text="+ Tuş",
            bg=self.accent_color,
            fg="white",
            activebackground=self.accent_hover,
            activeforeground="white",
            bd=0,
            font=("Segoe UI", 7, "bold"),
            padx=6,
            pady=3,
            command=lambda g=group: self.add_key_to_group(g),
        )
        add_key_button.pack(side="right")

        _roles, errors = writing_layout(group)
        if errors:
            tk.Button(card, text="Yazı eksik · Düzelt", bg=self.input_bg, fg=self.danger_color,
                      bd=0, command=lambda g=group: self.repair_writing(g)).pack(anchor="w")
        children_frame = tk.Frame(card, bg=self.card_color)
        children_frame.pack(fill="x")

        for item in group.children:
            if item.kind == "macro":
                config = self._find_config(item.macro_id)
                if config is not None:
                    self.draw_card_row(config, parent=children_frame, group=group)

        self.group_widgets[group.id_token] = {
            "outer": outer,
            "check": group_check,
            "enabled_var": enabled_var,
        }
        if not group.enabled:
            self.fade_widgets(outer, True, locked=True, exception=group_check)

    @editable_only
    def toggle_group_enabled(self, group, variable):
        self.cancel_pixel_pick()
        self.clicker.capturing_callback = None
        self.capturing_target = None
        group.enabled = bool(variable.get())
        self.save_current_configs_to_profiles(update_workers=False, update_sequences=True)
        self.refresh_keys_list_ui()

    def fade_widgets(self, widget, faded, *, locked=False, exception=None):
        # Blend every original color toward the app background; keep controls recoverable.
        options = widget.keys()
        if not hasattr(widget, "_unfaded_colors"):
            widget._unfaded_colors = {key: widget.cget(key) for key in
                ("background", "foreground", "activebackground", "activeforeground",
                 "disabledforeground", "disabledbackground", "highlightbackground", "selectcolor", "insertbackground")
                if key in options}
        applied = getattr(widget, "_applied_fade_colors", {})
        for key in widget._unfaded_colors:
            current = widget.cget(key)
            if key in applied and str(current) != str(applied[key]):
                widget._unfaded_colors[key] = current
        widget._applied_fade_colors = {}
        widget._faded = faded
        for key, original in widget._unfaded_colors.items():
            color = original
            if faded:
                try:
                    source, target = widget.winfo_rgb(original), widget.winfo_rgb(self.bg_color)
                    color = "#" + "".join(f"{round((a * 0.22 + b * 0.78) / 257):02x}" for a, b in zip(source, target))
                except tk.TclError:
                    continue
            widget.configure(**{key: color})
            widget._applied_fade_colors[key] = widget.cget(key)
        if locked and widget is not exception and isinstance(widget, (tk.Button, tk.Entry, tk.Checkbutton, tk.Menubutton)):
            widget.configure(state="disabled")
        for child in widget.winfo_children():
            self.fade_widgets(child, faded, locked=locked, exception=exception)

    def update_group_states(self) -> None:
        for group_id, widgets in self.group_widgets.items():
            active = group_id in self.active_group_ids
            outer = widgets.get("outer")
            group = next((g for g in self.sequence_groups if g.id_token == group_id), None)
            if outer and outer.winfo_exists():
                outer.configure(
                    bg=self.border_color if group is not None and not group.enabled else self.success_color if active else self.accent_color
                )

    def refresh_keys_list_ui(self):
        self.finish_group_drag(None)
        self._group_cards = {}
        self.sequence_groups = flatten_groups(self.sequence_groups)
        for widget in self.list_container.scrollable_frame.winfo_children():
            widget.destroy()

        self.config_widgets = {}
        self.group_widgets = {}

        if not self.key_configs and not self.sequence_groups:
            self.draw_markers()
            return

        if self.sequence_groups:
            for group in self.sequence_groups:
                self.draw_sequence_group(
                    group,
                    self.list_container.scrollable_frame,
                )

        assigned_ids = grouped_macro_ids(self.sequence_groups)
        ungrouped = [
            config
            for config in self.key_configs
            if config.id_token not in assigned_ids
        ]
        if ungrouped:
            for config in ungrouped:
                self.draw_card_row(config)

        self.update_group_states()
        self.draw_markers()

    def draw_card_row(self, config: KeyConfig, parent: tk.Misc | None = None, group=None):
        if hasattr(self, "empty_lbl") and self.empty_lbl.winfo_exists():
            self.empty_lbl.destroy()

        card = tk.Frame(
            parent or self.list_container.scrollable_frame, bg=self.card_color,
            bd=0, highlightbackground=self.border_color, highlightthickness=1
        )
        card.pack(fill="x", pady=3, padx=0)
        
        # 1. Satır: Tuş Seçici
        row1 = tk.Frame(card, bg=self.card_color)
        row1.pack(fill="x", padx=5, pady=(4, 0))
        
        if group is not None:
            self._group_cards.setdefault(group.id_token, []).append((config.id_token, card))
            roles, errors = writing_layout(group)
            role, _block = roles.get(config.id_token, (None, None))
            handle = tk.Label(row1, text="⠿", bg=self.card_color, fg=self.text_secondary,
                              cursor="fleur", font=("Segoe UI", 10))
            handle.pack(side="left")
            if role != "close" and not errors:
                handle.bind("<ButtonPress-1>", lambda e, g=group, k=config.id_token: self.start_group_drag(e, g, k))
                handle.bind("<B1-Motion>", self.drag_group_key)
                handle.bind("<ButtonRelease-1>", self.finish_group_drag)
            for label, direction in (("↑", -1), ("↓", 1)):
                tk.Button(row1, text=label, bd=0, bg=self.input_bg, fg=self.text_primary,
                          padx=1, state="disabled" if role == "close" or errors else "normal",
                          command=lambda g=group, k=config.id_token, d=direction: self.step_group_key(g, k, d)).pack(side="left")

        key_btn = tk.Button(
            row1, text=config.key.upper(), font=("Segoe UI", 8, "bold"),
            bg=self.input_bg, fg=self.text_primary, bd=0, activebackground=self.border_color,
            activeforeground="white", padx=6, pady=2
        )
        key_btn.pack(side="left", padx=(2, 4))
        key_btn.configure(command=lambda cfg=config, btn=key_btn: self.start_key_capture("key", cfg, btn))
        
        # 2. Satır: Aralık & Rastgelelik Girişleri
        row2 = row1
        
        tk.Label(row2, text="Aralık", bg=self.card_color, fg=self.text_secondary, font=("Segoe UI", 8)).pack(side="left")
        int_entry = self.create_modern_entry(row2, width=5)
        int_entry.frame.pack(side="left", padx=(3, 4))
        int_entry.insert(0, f"{config.interval_seconds:.3f}")
        int_entry._saved_value = lambda cfg=config: f"{cfg.interval_seconds:.3f}"
        
        # Auto-save bindings for interval
        int_entry.bind("<FocusOut>", lambda e, cfg=config, entry=int_entry: self.auto_save_timing(cfg, entry, "interval"))
        int_entry.bind("<Return>", lambda e, cfg=config, entry=int_entry: (self.auto_save_timing(cfg, entry, "interval"), self.root.focus_set()))
        
        tk.Label(row2, text="± sn", bg=self.card_color, fg=self.text_secondary, font=("Segoe UI", 8)).pack(side="left")
        rand_entry = self.create_modern_entry(row2, width=5)
        rand_entry.frame.pack(side="left", padx=5)
        rand_entry.insert(0, f"{config.random_seconds:.3f}")
        rand_entry._saved_value = lambda cfg=config: f"{cfg.random_seconds:.3f}"
        
        # Auto-save bindings for randomness
        rand_entry.bind("<FocusOut>", lambda e, cfg=config, entry=rand_entry: self.auto_save_timing(cfg, entry, "random"))
        rand_entry.bind("<Return>", lambda e, cfg=config, entry=rand_entry: (self.auto_save_timing(cfg, entry, "random"), self.root.focus_set()))
        
        # 3. Satır: Durum & İzleme & Sil Butonları
        row3 = tk.Frame(card, bg=self.card_color)
        row3.pack(fill="x", padx=5, pady=(1, 3))
        
        var = tk.IntVar(value=1 if config.enabled else 0)
        chk = tk.Checkbutton(
            row3, text="Aktif", variable=var,
            bg=self.card_color, fg=self.text_primary, selectcolor=self.input_bg,
            activebackground=self.card_color, activeforeground=self.text_primary,
            font=("Segoe UI", 8, "bold"),
            command=lambda cfg=config, v=var: self.toggle_key_enabled(cfg, v)
        )
        chk.pack(side="left")
        chk.var = var
        
        screen_var = tk.IntVar(value=1 if config.screen_mode else 0)
        chk_screen = tk.Checkbutton(
            row3, text="İzleme", variable=screen_var,
            bg=self.card_color, fg=self.text_primary, selectcolor=self.input_bg,
            activebackground=self.card_color, activeforeground=self.text_primary,
            font=("Segoe UI", 8, "bold"),
            command=lambda cfg=config, sv=screen_var: self.toggle_screen_mode(cfg, sv)
        )
        chk_screen.pack(side="left", padx=(10, 0))
        chk_screen.var = screen_var
        
        if group is not None:
            roles, _errors = writing_layout(group)
            role, _block = roles.get(config.id_token, (None, None))
            pending = next((b for b in group.writing_blocks if not b.closing), None)
            ids = [item.macro_id for item in group.children]
            after_opening = pending is not None and pending.opening in ids and ids.index(config.id_token) > ids.index(pending.opening)
            label = {"open": "Yazı açıyor", "close": "Yazı kapatıyor", "body": "Yazı"}.get(role,
                     "Yazı kapatıyor" if after_opening else "Yazı açıyor")
            writing_var = tk.IntVar(value=int(role is not None))
            writing_check = tk.Checkbutton(row3, text=label, variable=writing_var,
                bg=self.card_color, fg=self.text_primary, selectcolor=self.input_bg,
                activebackground=self.card_color, activeforeground=self.text_primary,
                font=("Segoe UI", 8, "bold"), state="disabled" if role == "body" else "normal",
                command=lambda g=group, k=config.id_token: self.toggle_writing(g, k))
            writing_check.var = writing_var
            writing_check.pack(side="left", padx=(3, 0))

        del_btn = tk.Button(
            row3, text="Sil", font=("Segoe UI", 8, "bold"),
            bg=self.danger_color, fg="white", bd=0, activebackground=self.danger_hover,
            activeforeground="white", padx=12, pady=2,
            command=lambda cfg=config: self.delete_key_config(cfg)
        )
        del_btn.pack(side="right")
        
        # 4. Satır: Ekran İzleme Ayarları (Collapsible Frame)
        screen_frame = tk.Frame(card, bg=self.card_color)
        
        # Piksel Seç Butonu
        pixel_btn = tk.Button(
            screen_frame, text="Piksel Seç", font=("Segoe UI", 8, "bold"),
            bg=self.input_bg, fg=self.text_primary, bd=0, activebackground=self.border_color,
            activeforeground="white", padx=6, pady=2
        )
        pixel_btn.pack(side="left")
        
        # Konum & Renk Geri Bildirimi
        coord_lbl = tk.Label(
            screen_frame, text=f" ({config.pixel_x}, {config.pixel_y})" if config.has_pixel_target else "—",
            bg=self.card_color, fg=self.text_secondary, font=("Segoe UI", 8)
        )
        coord_lbl.pack(side="left", padx=(10, 5))
        
        color_preview = tk.Canvas(
            row1, width=12, height=12,
            bg=config.target_color if config.target_color else self.input_bg,
            highlightthickness=1, highlightbackground=self.border_color
        )
        if config.screen_mode:
            color_preview.pack(side="left", padx=2)
        
        pixel_btn.configure(command=lambda cfg=config, btn=pixel_btn, lbl=coord_lbl, preview=color_preview: self.start_pixel_capture(cfg, btn, lbl, preview))
        
        # Ekran modu aciksa frame'i paketle
        if config.screen_mode:
            screen_frame.pack(fill="x", padx=5, pady=1)
            
        # 5. Satır: Tıklama Hedef Koordinat Ayarları (Collapsible Frame)
        click_frame = tk.Frame(card, bg=self.card_color, pady=2)
        
        # Konum Seç Butonu
        loc_btn = tk.Button(
            click_frame, text="Konum Seç", font=("Segoe UI", 8, "bold"),
            bg=self.input_bg, fg=self.text_primary, bd=0, activebackground=self.border_color,
            activeforeground="white", padx=6, pady=2
        )
        loc_btn.pack(side="left")
        
        # Seçili Koordinat Geri Bildirimi
        loc_lbl = tk.Label(
            click_frame, text=f" ({config.click_x}, {config.click_y})" if config.has_click_target else "İmleç",
            bg=self.card_color, fg=self.text_secondary, font=("Segoe UI", 8)
        )
        loc_lbl.pack(side="left", padx=10)
        
        loc_btn.configure(command=lambda cfg=config, btn=loc_btn, lbl=loc_lbl: self.start_click_capture(cfg, btn, lbl))
        
        # Sıfırla Butonu
        reset_btn = tk.Button(
            click_frame, text="Sıfırla", font=("Segoe UI", 8, "bold"),
            bg=self.danger_color, fg="white", bd=0, activebackground=self.danger_hover,
            activeforeground="white", padx=8, pady=2,
            command=lambda cfg=config, lbl=loc_lbl: self.reset_click_coordinate(cfg, lbl)
        )
        reset_btn.pack(side="right")
        
        # Fare tuşu ise konum seç panelini paketle
        is_mouse = config.key.lower() in (
            "sol klik", "left click", "sol tık",
            "sağ klik", "sag klik", "right click", "sağ tık",
            "orta klik", "middle click", "orta tık",
            "mouse x1", "mouse x2", "x1", "x2",
        )
        if is_mouse:
            click_frame.pack(fill="x", padx=5, pady=1)
            
        self.config_widgets[id(config)] = {
            "card": card,
            "chk_var": var,
            "key_btn": key_btn,
            "int_entry": int_entry,
            "rand_entry": rand_entry,
            "screen_var": screen_var,
            "screen_frame": screen_frame,
            "coord_lbl": coord_lbl,
            "color_preview": color_preview,
            "pixel_btn": pixel_btn,
            "click_frame": click_frame,
            "loc_lbl": loc_lbl,
            "loc_btn": loc_btn
        }
        self.fade_widgets(card, not config.enabled)

    def cancel_pixel_pick(self) -> None:
        pending = self._pending_pixel_pick
        self._pending_pixel_pick = None
        click_pending = getattr(self, "_pending_click_pick", None)
        self._pending_click_pick = None
        if click_pending is not None and click_pending[1].winfo_exists():
            click_pending[1].configure(text="Konum Seç", bg=self.input_bg, fg=self.text_primary)
        self.stop_point_preview()
        self.clicker.pixel_capture_callback = None
        self.clicker.pixel_capture_cancel_callback = None
        self.clicker._pixel_capture_down = None
        if pending is not None and pending[1].winfo_exists():
            pending[1].configure(text="Piksel Seç", bg=self.input_bg, fg=self.text_primary)

    @editable_only
    def start_pixel_capture(self, config: KeyConfig, button: tk.Button, coord_lbl: tk.Label, color_preview: tk.Canvas):
        self.cancel_pixel_pick()
        previous = getattr(self, "capturing_target", None)
        if previous is not None:
            kind, old_config, old_button = previous
            if old_button is not None and old_button.winfo_exists():
                label = self.clicker.app_config.panic_key if kind == "panic" else old_config.key
                old_button.configure(text=label.upper(), bg=self.input_bg, fg=self.text_primary)
        self.capturing_target = None
        self.clicker.capturing_callback = None
        overlay = getattr(self, "_capture_overlay", None)
        if overlay is not None and overlay.winfo_exists():
            overlay.destroy()
        self._capture_overlay = None
        pending = (config, button, coord_lbl, color_preview)
        self._pending_pixel_pick = pending
        button.configure(text="Tıklayın...", bg=self.accent_color, fg="white")
        self.arm_pixel_click(pending)
        self.begin_point_preview("screen", config)
        self.clicker.log("İzlenecek noktaya tıklayın; tıklamanın 8 piksel solu ve üstü okunacak. ESC: iptal.")

    def arm_pixel_click(self, pending) -> None:
        if self._pending_pixel_pick is not pending or self.clicker.is_running:
            return
        self.clicker.pixel_capture_callback = lambda x, y: self.on_pixel_pick_click(x, y, pending)
        self.clicker.pixel_capture_cancel_callback = lambda: self.log_queue.put(("pixel_pick_cancel", pending))

    def on_pixel_pick_click(self, click_x: int, click_y: int, pending) -> None:
        if foreground_is_ours():
            self.arm_pixel_click(pending)
            return
        self._selection_clicked_point = (click_x, click_y)
        self.log_queue.put(("pixel_pick_point", (
            pending, click_x - PIXEL_PICK_OFFSET, click_y - PIXEL_PICK_OFFSET,
        )))

    def sample_picked_pixel(self, pending, x, y):
        # Hide the moving preview before confirming, including if the mouse moved
        # between preview frames. Persistent markers also expose this exact pixel.
        preview = getattr(self, "_selection_preview", None)
        if preview is not None and preview.winfo_exists():
            preview.withdraw()
        self.protect_marker_pixels(extra=((x, y),))
        self.root.update_idletasks()
        flush_desktop()
        bounds, color = None, ""
        try:
            self.enqueue_log(f"Piksel seçim ortamı: {foreground_description()}")
            bounds = screen_bounds()
            color = get_pixel_color_win32(x, y)
            if bounds != screen_bounds():
                color = ""
        except Exception as error:
            self.enqueue_log(f"Piksel seçimi başarısız: {error}")
        self.log_queue.put(("pixel_pick_result", (pending, x, y, color, bounds)))

    def sample_uncovered_pixel(self, x: int, y: int, overlay=None) -> str:
        if overlay is not None:
            overlay.withdraw()
        visible = [marker for marker in self.markers.values() if marker.winfo_viewable()]
        for marker in visible:
            marker.withdraw()
        try:
            self.root.update_idletasks()
            flush_desktop()
            return get_pixel_color_win32(x, y)
        finally:
            for marker in visible:
                if marker.winfo_exists():
                    marker.deiconify()

    @editable_only
    def on_overlay_clicked(self, event, overlay, config, button, coord_lbl, color_preview):
        # Capture the selected scene without forwarding a click into the game.
        x, y = event.x_root, event.y_root
        color = self.sample_uncovered_pixel(x, y, overlay)
        overlay.destroy()
        if not color:
            if button.winfo_exists():
                button.configure(text="Piksel Seç", bg=self.input_bg, fg=self.text_primary)
            self.clicker.log("Piksel okunamadı; önceki hedef korundu.")
            return
        self.log_queue.put(("pixel_capture", (config, x, y, color, button, coord_lbl, color_preview)))

    def cancel_overlay_capture(self, overlay, button):
        overlay.destroy()
        button.configure(text="Piksel Seç", bg=self.input_bg, fg=self.text_primary)
        self.clicker.log("Piksel seçimi iptal edildi.")

    @editable_only
    def start_click_capture(self, config: KeyConfig, button: tk.Button, loc_lbl: tk.Label):
        self.cancel_pixel_pick()
        pending = (config, button, loc_lbl)
        self._pending_click_pick = pending
        button.configure(text="Tıklayın...", bg=self.accent_color, fg="white")
        self.arm_click_target(pending)
        self.begin_point_preview("click", config)

    def arm_click_target(self, pending):
        if self._pending_click_pick is not pending or self.clicker.is_running:
            return
        self.clicker.pixel_capture_callback = lambda x, y: self.on_click_target_picked(x, y, pending)
        self.clicker.pixel_capture_cancel_callback = lambda: self.log_queue.put(("click_pick_cancel", pending))

    def on_click_target_picked(self, x, y, pending):
        if foreground_is_ours():
            self.arm_click_target(pending)
            return
        self._selection_clicked_point = (x, y)
        self.log_queue.put(("click_pick_result", (pending, x, y)))

    @editable_only
    def reset_click_coordinate(self, config: KeyConfig, loc_lbl: tk.Label):
        config.click_x = -1
        config.click_y = -1
        self.save_current_configs_to_profiles(update_workers=False)
        
        loc_lbl.configure(text="İmleç")
        self.clicker.log(f"{config.key.upper()} tıklama konumu sıfırlandı, imleç konumuna tıklanacak.")
        self.draw_markers()

    @editable_only
    def toggle_screen_mode(self, config: KeyConfig, screen_var: tk.IntVar):
        config.screen_mode = (screen_var.get() == 1)
        self.save_current_configs_to_profiles(update_workers=True)
        
        cfg_id = id(config)
        if cfg_id in self.config_widgets:
            frame = self.config_widgets[cfg_id]["screen_frame"]
            swatch = self.config_widgets[cfg_id]["color_preview"]
            if config.screen_mode:
                frame.pack(fill="x", padx=5, pady=1)
                swatch.pack(side="left", padx=2)
            else:
                frame.pack_forget()
                swatch.pack_forget()
                
        self.draw_markers()

    @editable_only
    def auto_save_timing(self, config: KeyConfig, entry: tk.Entry, field_type: str):
        try:
            raw_text = entry.get().strip().replace(",", ".")
            val = round(float(raw_text), 3)
            adjusted = False
            if field_type == "interval":
                clamped = clamp_click_interval(config.key, val)
                adjusted = clamped != val
                val = clamped
            if val < 0:
                raise ValueError("Değer negatif olamaz.")
            if field_type == "interval":
                if val <= 0:
                    raise ValueError("Aralık 0'dan büyük olmalıdır.")
                config.interval_seconds = val
            elif field_type == "random":
                config.random_seconds = val
                
            self.save_current_configs_to_profiles(update_workers=False)
            entry.delete(0, tk.END)
            entry.insert(0, f"{val:.3f}")
            if not adjusted:
                self.clicker.log(f"Zamanlama güncellendi: {config.key.upper()} ({config.interval_seconds:.3f} + {config.random_seconds:.3f} sn)")
        except ValueError as e:
            entry.delete(0, tk.END)
            if field_type == "interval":
                entry.insert(0, f"{config.interval_seconds:.3f}")
            else:
                entry.insert(0, f"{config.random_seconds:.3f}")
            self.clicker.log(f"Geçersiz zamanlama değeri: {e}")

    @editable_only
    def add_blank_key_config(self):
        now = time.monotonic()
        if now - self.last_add_time < 0.1:
            return
        self.last_add_time = now

        config = KeyConfig(
            key="sol klik",
            interval_seconds=1.00,
            random_seconds=0.100,
            enabled=True,
            screen_mode=False,
            pixel_x=0,
            pixel_y=0,
            target_color="",
            invert_color=False,
            click_x=-1,
            click_y=-1,
            id_token=new_id()
        )
        self.key_configs.append(config)
        self.save_current_configs_to_profiles(update_workers=True)
        
        self.draw_card_row(config)
        self.draw_markers()
        
        self.list_container.scrollable_frame.update_idletasks()
        self.list_container.canvas.configure(scrollregion=self.list_container.canvas.bbox("all"))
        self.list_container.canvas.yview_moveto(1.0)

    @editable_only
    def delete_key_config(self, config: KeyConfig):
        if getattr(self, "_preview_config", None) is config:
            self.cancel_pixel_pick()
        cfg_id = id(config)
        if cfg_id in self.config_widgets:
            self.config_widgets[cfg_id]["screen_frame"].pack_forget()
            self.config_widgets[cfg_id]["click_frame"].pack_forget()
            self.config_widgets[cfg_id]["card"].destroy()
            del self.config_widgets[cfg_id]
            
        self.key_configs.remove(config)
        group_changed = self._remove_macro_from_groups(config.id_token)
        self.save_current_configs_to_profiles(
            update_workers=True,
            update_sequences=group_changed,
        )
        
        if group_changed or not self.key_configs:
            self.refresh_keys_list_ui()
            
        self.list_container.scrollable_frame.update_idletasks()
        self.list_container.canvas.configure(scrollregion=self.list_container.canvas.bbox("all"))
        self.draw_markers()

    def update_checkbox_states(self):
        for config in self.key_configs:
            cfg_id = id(config)
            if cfg_id in self.config_widgets:
                var = self.config_widgets[cfg_id]["chk_var"]
                var.set(1 if config.enabled else 0)
                
    @editable_only
    def toggle_key_enabled(self, config: KeyConfig, var: tk.IntVar):
        self.clicker.set_config_enabled(config, var.get() == 1)
        self.save_current_configs_to_profiles(update_workers=False)
        widgets = self.config_widgets.get(id(config), {})
        if "card" in widgets:
            self.fade_widgets(widgets["card"], not config.enabled)
        state_str = "aktif" if config.enabled else "pasif"
        self.clicker.log(f"{config.key.upper()} basıcısı {state_str} yapıldı.")

    def set_editing_locked(self, locked: bool) -> None:
        if not locked:
            for widget, state in self._locked_widget_states.items():
                if widget.winfo_exists():
                    widget.configure(state=state)
            for (menu, index), state in self._locked_menu_states.items():
                if menu.winfo_exists():
                    menu.entryconfigure(index, state=state)
            self._locked_widget_states.clear()
            self._locked_menu_states.clear()
            return

        self.finish_group_drag(None)
        self.clicker.capturing_callback = None
        self.capturing_target = None
        self.cancel_pixel_pick()
        self.panic_btn.configure(text=self.clicker.app_config.panic_key.upper())
        overlay = self._capture_overlay
        if overlay is not None and overlay.winfo_exists():
            overlay.destroy()
        self._capture_overlay = None
        for config in self.key_configs:
            widgets = self.config_widgets.get(id(config), {})
            for name, label in (("key_btn", config.key.upper()), ("pixel_btn", "Piksel Seç"), ("loc_btn", "Konum Seç")):
                if name in widgets:
                    widgets[name].configure(text=label)
        if not isinstance(self.root.focus_get(), tk.Text):
            self.root.focus_set()

        def lock_widget(widget):
            if isinstance(widget, (tk.Entry, tk.Button, tk.Checkbutton, tk.Menubutton)):
                if widget not in self._locked_widget_states:
                    self._locked_widget_states[widget] = widget.cget("state")
                    if isinstance(widget, tk.Entry):
                        saved_value = getattr(widget, "_saved_value", None)
                        if saved_value is not None:
                            widget.delete(0, tk.END)
                            widget.insert(0, saved_value())
                        if not getattr(widget, "_faded", False):
                            widget.configure(disabledbackground=self.input_bg, disabledforeground=self.text_secondary)
                    widget.configure(state="disabled")
            if isinstance(widget, tk.Menu):
                widget.unpost()
                end = widget.index("end")
                for index in range(end + 1 if end is not None else 0):
                    if widget.type(index) == "separator":
                        continue
                    token = (widget, index)
                    if token not in self._locked_menu_states:
                        self._locked_menu_states[token] = widget.entrycget(index, "state")
                        widget.entryconfigure(index, state="disabled")
            for child in widget.winfo_children():
                lock_widget(child)

        for container in (self.profile_frame, self.list_header, self.list_container.scrollable_frame, self.chk_topmost):
            lock_widget(container)

    def update_running_ui(self, active: bool):
        self.set_editing_locked(active)
        self.draw_markers()
        if active:
            self.status_badge.configure(
                text="DURDUR",
                bg=self.success_color,
                activebackground=self.success_hover,
            )
        else:
            self.status_badge.configure(
                text="BAŞLAT",
                bg=self.danger_color,
                activebackground=self.danger_hover,
            )
            self.update_checkbox_states()
