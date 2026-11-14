from __future__ import annotations

import queue
import time
import tkinter as tk
from tkinter import messagebox, simpledialog

from pynput.mouse import Button

from .config import save_config
from .engine import RandomizedAutoClicker
from .models import (
    KeyConfig,
    key_config_from_dict,
    key_config_to_dict,
    new_id,
)
from .platform_win import get_pixel_color_win32
from .profile_store import load_profiles, save_profiles
from .sequences import (
    MAX_GROUP_DEPTH,
    SequenceGroup,
    SequenceItem,
    group_macro_ids,
    grouped_macro_ids,
    iter_groups,
    sequence_group_to_dict,
    sequence_groups_from_list,
)
from .ui_widgets import DEFAULT_THEME, ScrollableFrame


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
        self.root.title("Arık Makro")
        self.root.geometry("560x640")
        
        # İç içe grup kartları için okunabilir, kullanıcı tarafından ayarlanabilir alan.
        self.root.resizable(True, True)
        self.root.minsize(480, 360)
        
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
        
        bottom_row = top_row
        self.panic_btn = tk.Button(
            bottom_row, text=self.clicker.app_config.panic_key.upper(), font=("Segoe UI", 8, "bold"),
            bg=self.input_bg, fg=self.text_primary, bd=0, activebackground=self.border_color,
            activeforeground="white", padx=8, pady=2,
            command=lambda: self.start_key_capture("panic", None, self.panic_btn)
        )
        self.panic_btn.pack(side="left", padx=8)
        
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
        
        self.delete_prof_btn = tk.Button(
            self.profile_frame, text="Sil", font=("Segoe UI", 8, "bold"),
            bg=self.danger_color, fg="white", bd=0, activebackground=self.danger_hover,
            activeforeground="white", padx=8, pady=2, command=self.delete_profile
        )
        self.delete_prof_btn.pack(side="right", padx=2)
        
        self.new_prof_btn = tk.Button(
            self.profile_frame, text="Yeni", font=("Segoe UI", 8, "bold"),
            bg=self.accent_color, fg="white", bd=0, activebackground=self.accent_hover,
            activeforeground="white", padx=8, pady=2, command=self.create_profile
        )
        self.new_prof_btn.pack(side="right", padx=2)
        
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

    def shutdown(self) -> None:
        self._shutting_down = True
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

    def on_marker_press(self, marker_window, event):
        marker_window._drag_x = event.x
        marker_window._drag_y = event.y

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

    def on_marker_drag(self, marker_window, event, config, marker_type):
        dx = event.x - marker_window._drag_x
        dy = event.y - marker_window._drag_y
        x = marker_window.winfo_x() + dx
        y = marker_window.winfo_y() + dy
        
        center_x = x + 50
        center_y = y + 28
        
        if marker_type == "screen":
            config.pixel_x = center_x
            config.pixel_y = center_y
            cfg_id = id(config)
            if cfg_id in self.config_widgets:
                self.config_widgets[cfg_id]["coord_lbl"].configure(text=f" ({center_x}, {center_y})")
                color = get_pixel_color_win32(center_x, center_y)
                if color:
                    config.target_color = color
                    self.config_widgets[cfg_id]["color_preview"].configure(bg=color)
        elif marker_type == "click":
            config.click_x = center_x
            config.click_y = center_y
            cfg_id = id(config)
            if cfg_id in self.config_widgets:
                self.config_widgets[cfg_id]["loc_lbl"].configure(text=f" ({center_x}, {center_y})")
        marker_window.geometry(f"100x40+{x}+{y}")
        self.schedule_marker_save()

    def draw_markers(self):
        # Eski işaretçileri sil
        for m in self.markers.values():
            try:
                m.destroy()
            except Exception:
                pass
        self.markers = {}
        
        # Editing markers must never cover the game while macros are running.
        if self.clicker.is_running:
            return

        trans_color = "#000001"
        
        # 1. Normal tuşların işaretçileri
        for config in self.key_configs:
            # Ekran İzleme Göstergesi (Halka - Gül Kırmızısı) - SÜRÜKLENEBİLİR
            if config.screen_mode and config.has_pixel_target:
                marker = tk.Toplevel(self.root)
                marker.overrideredirect(True)
                marker.attributes("-topmost", True)
                marker.attributes("-transparentcolor", trans_color)
                marker.geometry(f"100x40+{config.pixel_x-50}+{config.pixel_y-28}")
                marker.configure(bg=trans_color)
                
                canvas = tk.Canvas(marker, width=100, height=40, bg=trans_color, highlightthickness=0)
                canvas.pack()
                
                label_text = f"İzle: {config.key.upper()}"
                canvas.create_text(50, 8, text=label_text, fill="#f43f5e", font=("Segoe UI", 7, "bold"))
                canvas.create_oval(42, 20, 58, 36, outline="#f43f5e", width=2)
                
                canvas.bind("<Button-1>", lambda event, mw=marker: self.on_marker_press(mw, event))
                canvas.bind("<B1-Motion>", lambda event, mw=marker, c=config: self.on_marker_drag(mw, event, c, "screen"))
                
                self.markers[f"screen_{id(config)}"] = marker
                
            # Fare Tıklama Koordinat Göstergesi (Halka - Mavi) - SÜRÜKLENEBİLİR
            is_mouse = config.key.lower() in ("sol klik", "left click", "sol tık", "sağ klik", "sag klik", "right click", "sağ tık", "orta klik", "middle click", "orta tık")
            if is_mouse and config.has_click_target:
                marker = tk.Toplevel(self.root)
                marker.overrideredirect(True)
                marker.attributes("-topmost", True)
                marker.attributes("-transparentcolor", trans_color)
                marker.geometry(f"100x40+{config.click_x-50}+{config.click_y-28}")
                marker.configure(bg=trans_color)
                
                canvas = tk.Canvas(marker, width=100, height=40, bg=trans_color, highlightthickness=0)
                canvas.pack()
                
                label_text = f"Tıkla: {config.key.upper()}"
                canvas.create_text(50, 8, text=label_text, fill="#3b82f6", font=("Segoe UI", 7, "bold"))
                canvas.create_oval(42, 20, 58, 36, outline="#3b82f6", width=2)
                
                canvas.bind("<Button-1>", lambda event, mw=marker: self.on_marker_press(mw, event))
                canvas.bind("<B1-Motion>", lambda event, mw=marker, c=config: self.on_marker_drag(mw, event, c, "click"))
                
                self.markers[f"click_{id(config)}"] = marker

    def toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get() == 1)

    def toggle_system(self) -> None:
        """Arayüzden sistemi güvenli biçimde başlat veya durdur."""
        self.clicker.toggle_manual()

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
                if msg_type == "log":
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
                elif msg_type == "pixel_capture":
                    config, x, y, color, btn, lbl, preview = data
                    config.pixel_x = x
                    config.pixel_y = y
                    config.target_color = color
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
        self.log_text = tk.Text(
            self.log_container_frame, bg="#0d1117", fg="#c9d1d9",
            font=("Consolas", 8), bd=0, highlightthickness=0,
            state="disabled", wrap="word", height=2
        )
        
        scrollbar = tk.Scrollbar(self.log_container_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

    def clear_console_logs(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def unfocus_entries(self, event):
        # Eğer tıklanan nesne bir Entry değilse odağı ana pencereye çekerek klavye odağını düşürür
        if event.widget and not isinstance(event.widget, tk.Entry):
            self.root.focus_set()

    def append_log_to_widget(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, msg + "\n")
        lines = int(self.log_text.index('end-1c').split('.')[0])
        if lines > 100:
            self.log_text.delete("1.0", "2.0")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def load_active_profile_configs(self):
        configs_list = self.profiles_data["profiles"].get(self.active_profile, [])
        self.key_configs = [
            key_config_from_dict(item) for item in configs_list if isinstance(item, dict)
        ]
        self.sequence_groups = sequence_groups_from_list(
            self.profiles_data.get("groups", {}).get(self.active_profile, [])
        )
        
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

    def on_profile_menu_select(self, val):
        self.profile_var.set(val)
        self.on_profile_changed()

    def on_profile_changed(self, event=None):
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

    def create_profile(self):
        name = simpledialog.askstring("Yeni Profil", "Profil ismini girin:", parent=self.root)
        if name:
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

    def delete_profile(self):
        if len(self.profiles_data["profiles"]) <= 1:
            messagebox.showinfo("Bilgi", "En az bir adet profil bulunmalıdır.")
            return
            
        if messagebox.askyesno("Onay", f"'{self.active_profile}' profilini silmek istiyor musunuz?"):
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

    def start_key_capture(self, target_type: str, config: KeyConfig | None = None, button_widget: tk.Button | None = None):
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
                    
            self.draw_markers()

    def add_root_group(self) -> None:
        group = SequenceGroup(name=f"Grup {len(self.sequence_groups) + 1}")
        self.sequence_groups.append(group)
        self.save_current_configs_to_profiles(
            update_workers=False,
            update_sequences=True,
        )
        self.refresh_keys_list_ui()
        self._scroll_to_bottom()

    def add_key_to_group(self, group: SequenceGroup) -> None:
        config = KeyConfig(
            key="sol klik",
            interval_seconds=1.0,
            random_seconds=0.0,
            enabled=False,
            id_token=new_id(),
        )
        self.key_configs.append(config)
        group.children.append(
            SequenceItem(
                kind="macro",
                macro_id=config.id_token,
                delay_seconds=0.0 if not group.children else 1.0,
            )
        )
        self.save_current_configs_to_profiles(
            update_workers=True,
            update_sequences=True,
        )
        self.refresh_keys_list_ui()

    def add_nested_group(self, parent: SequenceGroup, depth: int) -> None:
        if depth + 1 >= MAX_GROUP_DEPTH:
            messagebox.showinfo(
                "Grup Sınırı",
                f"Gruplar en fazla {MAX_GROUP_DEPTH} kat iç içe olabilir.",
            )
            return
        nested = SequenceGroup(name=f"Alt Grup {len(parent.children) + 1}")
        parent.children.append(
            SequenceItem(
                kind="group",
                group=nested,
                delay_seconds=0.0 if not parent.children else 1.0,
            )
        )
        self.save_current_configs_to_profiles(
            update_workers=False,
            update_sequences=True,
        )
        self.refresh_keys_list_ui()

    def start_group(self, group: SequenceGroup) -> None:
        if not group.children:
            messagebox.showinfo(
                "Boş Grup",
                "Önce gruba en az bir tuş veya alt grup ekleyin.",
            )
            return
        if not self.clicker.is_running:
            self.clicker.set_enabled(
                True,
                reason=f"{group.name} başlatıldığı için sistem açıldı.",
            )
        if not self.clicker.start_sequence(group.id_token):
            self.clicker.log(f"{group.name} zaten çalışıyor veya başlatılamadı.")

    def save_group_name(self, group: SequenceGroup, entry: tk.Entry) -> None:
        name = entry.get().strip()[:40] or "İsimsiz Grup"
        group.name = name
        entry.delete(0, tk.END)
        entry.insert(0, name)
        self.save_current_configs_to_profiles(update_workers=False)

    def save_group_delay(self, item: SequenceItem, entry: tk.Entry) -> None:
        try:
            value = round(float(entry.get().strip().replace(",", ".")), 3)
            if value < 0:
                raise ValueError
        except ValueError:
            value = item.delay_seconds
            self.clicker.log("Grup bekleme süresi negatif veya geçersiz olamaz.")
        item.delay_seconds = value
        entry.delete(0, tk.END)
        entry.insert(0, f"{value:.3f}")
        self.save_current_configs_to_profiles(update_workers=False)

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

    def draw_sequence_group(
        self,
        group: SequenceGroup,
        parent: tk.Misc,
        *,
        depth: int,
    ) -> None:
        border_color = self.accent_color if depth == 0 else self.success_color
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

        icon = tk.Label(
            header,
            text="▶",
            bg=self.card_color,
            fg=border_color,
            font=("Segoe UI", 10, "bold"),
        )
        icon.pack(side="left", padx=(0, 4))

        name_entry = tk.Entry(
            header,
            bg=self.input_bg,
            fg=self.text_primary,
            insertbackground=self.text_primary,
            bd=0,
            font=("Segoe UI", 9, "bold"), width=8,
        )
        name_entry.insert(0, group.name)
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

        start_button = tk.Button(
            controls,
            text="▶ Başlat",
            bg=self.success_color,
            fg="white",
            activebackground=self.success_hover,
            activeforeground="white",
            bd=0,
            font=("Segoe UI", 8, "bold"),
            padx=7,
            pady=3,
            command=lambda g=group: self.start_group(g),
        )
        start_button.pack(side="left")

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

        add_group_button = tk.Button(
            controls,
            text="+ Grup",
            bg=self.input_bg,
            fg=self.text_primary,
            activebackground=self.border_color,
            activeforeground="white",
            bd=0,
            font=("Segoe UI", 7, "bold"),
            padx=6,
            pady=3,
            state="normal" if depth + 1 < MAX_GROUP_DEPTH else "disabled",
            command=lambda g=group, d=depth: self.add_nested_group(g, d),
        )
        add_group_button.pack(side="right", padx=(0, 4))

        children_frame = tk.Frame(card, bg=self.card_color)
        children_frame.pack(fill="x")

        for index, item in enumerate(group.children):
            if index > 0:
                delay_row = tk.Frame(children_frame, bg=self.card_color)
                delay_row.pack(fill="x", pady=2)
                tk.Label(
                    delay_row,
                    text="↓",
                    bg=self.card_color,
                    fg=self.text_secondary,
                    font=("Segoe UI", 8, "bold"),
                ).pack(side="left")
                delay_entry = self.create_modern_entry(delay_row, width=6)
                delay_entry.frame.pack(side="left", padx=4)
                delay_entry.insert(0, f"{item.delay_seconds:.3f}")
                delay_entry.bind(
                    "<FocusOut>",
                    lambda _event, sequence_item=item, entry=delay_entry:
                        self.save_group_delay(sequence_item, entry),
                )
                delay_entry.bind(
                    "<Return>",
                    lambda _event, sequence_item=item, entry=delay_entry: (
                        self.save_group_delay(sequence_item, entry),
                        self.root.focus_set(),
                    ),
                )
                tk.Label(
                    delay_row,
                    text="sn",
                    bg=self.card_color,
                    fg=self.text_secondary,
                    font=("Segoe UI", 8),
                ).pack(side="left")

            if item.kind == "macro":
                config = self._find_config(item.macro_id)
                if config is not None:
                    self.draw_card_row(config, parent=children_frame)
            elif item.kind == "group" and item.group is not None:
                self.draw_sequence_group(
                    item.group,
                    children_frame,
                    depth=depth + 1,
                )

        self.group_widgets[group.id_token] = {
            "outer": outer,
            "icon": icon,
            "start_button": start_button,
        }

    def update_group_states(self) -> None:
        for group_id, widgets in self.group_widgets.items():
            active = group_id in self.active_group_ids
            outer = widgets.get("outer")
            icon = widgets.get("icon")
            button = widgets.get("start_button")
            if outer and outer.winfo_exists():
                outer.configure(
                    bg=self.success_color if active else self.accent_color
                )
            if icon and icon.winfo_exists():
                icon.configure(
                    text="●" if active else "▶",
                    fg=self.success_color if active else self.accent_color,
                )
            if button and button.winfo_exists():
                button.configure(
                    text="● Aktif" if active else "▶ Başlat",
                    state="disabled" if active else "normal",
                )

    def refresh_keys_list_ui(self):
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
                    depth=0,
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

    def draw_card_row(self, config: KeyConfig, parent: tk.Misc | None = None):
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
        
        key_btn = tk.Button(
            row1, text=config.key.upper(), font=("Segoe UI", 8, "bold"),
            bg=self.input_bg, fg=self.text_primary, bd=0, activebackground=self.border_color,
            activeforeground="white", padx=6, pady=2
        )
        key_btn.pack(side="left", padx=(0, 8))
        key_btn.configure(command=lambda cfg=config, btn=key_btn: self.start_key_capture("key", cfg, btn))
        
        # 2. Satır: Aralık & Rastgelelik Girişleri
        row2 = row1
        
        tk.Label(row2, text="Aralık", bg=self.card_color, fg=self.text_secondary, font=("Segoe UI", 8)).pack(side="left")
        int_entry = self.create_modern_entry(row2, width=6)
        int_entry.frame.pack(side="left", padx=(5, 10))
        int_entry.insert(0, f"{config.interval_seconds:.3f}")
        
        # Auto-save bindings for interval
        int_entry.bind("<FocusOut>", lambda e, cfg=config, entry=int_entry: self.auto_save_timing(cfg, entry, "interval"))
        int_entry.bind("<Return>", lambda e, cfg=config, entry=int_entry: (self.auto_save_timing(cfg, entry, "interval"), self.root.focus_set()))
        
        tk.Label(row2, text="± sn", bg=self.card_color, fg=self.text_secondary, font=("Segoe UI", 8)).pack(side="left")
        rand_entry = self.create_modern_entry(row2, width=6)
        rand_entry.frame.pack(side="left", padx=5)
        rand_entry.insert(0, f"{config.random_seconds:.3f}")
        
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
            screen_frame, width=12, height=12,
            bg=config.target_color if config.target_color else self.input_bg,
            highlightthickness=1, highlightbackground=self.border_color
        )
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

    def start_pixel_capture(self, config: KeyConfig, button: tk.Button, coord_lbl: tk.Label, color_preview: tk.Canvas):
        button.configure(text="Tıklayın...", bg=self.accent_color, fg="white")
        
        # Tam ekran şeffaf overlay penceresi oluştur
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        
        # Tüm ekranı kapla
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        overlay.geometry(f"{screen_w}x{screen_h}+0+0")
        
        # Windows'ta yarı şeffaf yapmak için alpha = 0.01
        overlay.attributes("-alpha", 0.01)
        overlay.configure(cursor="crosshair")
        
        # Tıklama ve iptal tuşlarını bağla
        overlay.bind("<Button-1>", lambda event: self.on_overlay_clicked(event, overlay, config, button, coord_lbl, color_preview))
        overlay.bind("<Escape>", lambda event: self.cancel_overlay_capture(overlay, button))

    def on_overlay_clicked(self, event, overlay, config, button, coord_lbl, color_preview):
        overlay._click_count = getattr(overlay, "_click_count", 0) + 1
        x = event.x_root
        y = event.y_root
        
        if overlay._click_count == 1:
            button.configure(text="Tekrar Tıkla...")
            self.clicker.log("Odaklanma algılandı. Lütfen aynı yere tekrar tıklayın...")
            
            self.focus_through_overlay(overlay, x, y)
        else:
            overlay.destroy()
            
            # Wait for the capture overlay to leave the desktop compositor.
            def sample_pixel():
                color = get_pixel_color_win32(x, y)
                if not color:
                    if button.winfo_exists():
                        button.configure(text="Piksel Seç", bg=self.input_bg, fg=self.text_primary)
                    self.clicker.log("Piksel okunamadı; önceki hedef korundu.")
                    return
                self.log_queue.put(("pixel_capture", (config, x, y, color, button, coord_lbl, color_preview)))
            self.root.after(100, sample_pixel)

    def cancel_overlay_capture(self, overlay, button):
        overlay.destroy()
        button.configure(text="Piksel Seç", bg=self.input_bg, fg=self.text_primary)
        self.clicker.log("Piksel seçimi iptal edildi.")

    def start_click_capture(self, config: KeyConfig, button: tk.Button, loc_lbl: tk.Label):
        button.configure(text="Tıklayın...", bg=self.accent_color, fg="white")
        
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        overlay.geometry(f"{screen_w}x{screen_h}+0+0")
        
        overlay.attributes("-alpha", 0.01)
        overlay.configure(cursor="crosshair")
        
        overlay.bind("<Button-1>", lambda event: self.on_click_overlay_clicked(event, overlay, config, button, loc_lbl))
        overlay.bind("<Escape>", lambda event: self.cancel_click_overlay_capture(overlay, button))

    def on_click_overlay_clicked(self, event, overlay, config, button, loc_lbl):
        overlay._click_count = getattr(overlay, "_click_count", 0) + 1
        x = event.x_root
        y = event.y_root
        
        if overlay._click_count == 1:
            button.configure(text="Tekrar Tıkla...")
            self.clicker.log("Odaklanma algılandı. Lütfen tıklanacak konumu seçmek için tekrar tıklayın...")
            
            self.focus_through_overlay(overlay, x, y)
        else:
            overlay.destroy()
            self.log_queue.put(("click_capture", (config, x, y, button, loc_lbl)))

    def cancel_click_overlay_capture(self, overlay, button):
        overlay.destroy()
        button.configure(text="Konum Seç", bg=self.input_bg, fg=self.text_primary)
        self.clicker.log("Tıklama konumu seçimi iptal edildi.")

    def reset_click_coordinate(self, config: KeyConfig, loc_lbl: tk.Label):
        config.click_x = -1
        config.click_y = -1
        self.save_current_configs_to_profiles(update_workers=False)
        
        loc_lbl.configure(text="İmleç")
        self.clicker.log(f"{config.key.upper()} tıklama konumu sıfırlandı, imleç konumuna tıklanacak.")
        self.draw_markers()

    def toggle_screen_mode(self, config: KeyConfig, screen_var: tk.IntVar):
        config.screen_mode = (screen_var.get() == 1)
        self.save_current_configs_to_profiles(update_workers=True)
        
        cfg_id = id(config)
        if cfg_id in self.config_widgets:
            frame = self.config_widgets[cfg_id]["screen_frame"]
            if config.screen_mode:
                frame.pack(fill="x", padx=5, pady=1)
            else:
                frame.pack_forget()
                
        self.draw_markers()

    def auto_save_timing(self, config: KeyConfig, entry: tk.Entry, field_type: str):
        try:
            raw_text = entry.get().strip().replace(",", ".")
            val = round(float(raw_text), 3)
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
            self.clicker.log(f"Zamanlama güncellendi: {config.key.upper()} ({config.interval_seconds:.3f} + {config.random_seconds:.3f} sn)")
        except ValueError as e:
            entry.delete(0, tk.END)
            if field_type == "interval":
                entry.insert(0, f"{config.interval_seconds:.3f}")
            else:
                entry.insert(0, f"{config.random_seconds:.3f}")
            self.clicker.log(f"Geçersiz zamanlama değeri: {e}")

    def add_blank_key_config(self):
        now = time.monotonic()
        if now - self.last_add_time < 0.1:
            return
        self.last_add_time = now

        config = KeyConfig(
            key="sol klik",
            interval_seconds=1.00,
            random_seconds=0.00,
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

    def delete_key_config(self, config: KeyConfig):
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
        
        if not self.key_configs:
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
                
    def toggle_key_enabled(self, config: KeyConfig, var: tk.IntVar):
        self.clicker.set_config_enabled(config, var.get() == 1)
        self.save_current_configs_to_profiles(update_workers=False)
        state_str = "aktif" if config.enabled else "pasif"
        self.clicker.log(f"{config.key.upper()} basıcısı {state_str} yapıldı.")

    def update_running_ui(self, active: bool):
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
