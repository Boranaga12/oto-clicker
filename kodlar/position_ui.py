"""One persistent position card and a passive rectangle overlay per profile."""
from __future__ import annotations

import math
import os
import time
import tkinter as tk

from .platform_win import make_overlay_passive, move_overlay, screen_bounds, monitor_layout


class RegionBorder(tk.Toplevel):
    TRANSPARENT = '#000001'

    def __init__(self, parent, region):
        super().__init__(parent)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(bg=self.TRANSPARENT)
        if os.name == 'nt':
            self.attributes('-transparentcolor', self.TRANSPARENT)
        else:
            self.attributes('-alpha', .5)
        x, y, width, height = region
        # The colored outline is outside the sampled rectangle.
        self.canvas = tk.Canvas(self, width=width+4, height=height+4,
                                bg=self.TRANSPARENT, bd=0, highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_rectangle(1, 1, width+2, height+2, outline='#4fd1c5', width=2)
        self.geometry(f'{width+4}x{height+4}')
        self.update_idletasks()
        handle = make_overlay_passive(self.winfo_id())
        self.deiconify()
        if handle is not None:
            move_overlay(handle, x-2, y-2, width+4, height+4)
        else:
            self.geometry(f'{width+4}x{height+4}{x-2:+d}{y-2:+d}')


class RegionSelector(tk.Toplevel):
    def __init__(self, parent, complete, cancelled):
        super().__init__(parent)
        self.withdraw()
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.attributes('-alpha', .28)
        self.configure(bg='black', cursor='crosshair')
        self.complete, self.cancelled = complete, cancelled
        self.origin = None
        self.bounds = screen_bounds()
        if self.bounds is None:
            self.destroy()
            raise RuntimeError('Ekran alanı okunamadı')
        left, top, width, height = self.bounds
        self.canvas = tk.Canvas(self, bg='black', bd=0, highlightthickness=0, cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)
        self.rect = self.canvas.create_rectangle(0, 0, 0, 0, outline='#4fd1c5', width=3)
        self.canvas.create_text(width//2, 32,
            text='Yalnızca X/Y sayılarını çevreleyin · Sürükleyip bırakın · Esc: iptal',
            fill='white', font=('Segoe UI', 13, 'bold'))
        self.geometry(f'{width}x{height}{left:+d}{top:+d}')
        self.deiconify()
        self.update_idletasks()
        if os.name == 'nt':
            import ctypes
            user = ctypes.windll.user32
            user.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            user.GetAncestor.restype = ctypes.c_void_p
            handle = user.GetAncestor(self.winfo_id(), 2)
            move_overlay(handle, left, top, width, height)
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.bind('<Escape>', lambda _event: self.cancel())
        self.focus_force()
        self.grab_set()

    def press(self, event):
        self.origin = (event.x, event.y)
        self.drag(event)

    def drag(self, event):
        if self.origin is not None:
            self.canvas.coords(self.rect, *self.origin, event.x, event.y)

    def release(self, event):
        if self.origin is None:
            return
        x1, y1 = self.origin
        x2, y2 = event.x, event.y
        left, top, width, height = self.bounds
        x1, x2 = sorted((max(0, min(width, x1)), max(0, min(width, x2))))
        y1, y2 = sorted((max(0, min(height, y1)), max(0, min(height, y2))))
        self.grab_release()
        self.destroy()
        if 8 <= x2-x1 <= 640 and 8 <= y2-y1 <= 180:
            self.complete((left+x1, top+y1, x2-x1, y2-y1), self.bounds)
        else:
            self.cancelled('Sadece koordinat satırını seçin (en az 8×8, en fazla 640×180).')

    def cancel(self):
        self.grab_release()
        self.destroy()
        self.cancelled('Seçim iptal edildi.')


class PositionPanel(tk.Frame):
    def __init__(self, parent, app):
        self.app = app
        self.engine = app.clicker
        super().__init__(parent, bg=app.card_color, padx=8, pady=7,
                         highlightbackground='#7597bd', highlightthickness=2)
        self.profile = None
        self.model = None
        self.border = self.selector = None
        self.job = None
        self.disposed = False
        self.pending_center = False
        self._border_signature = None
        header = tk.Frame(self, bg=app.card_color)
        header.pack(fill='x')
        tk.Label(header, text='KONUM KONTROLÜ', bg=app.card_color, fg=app.text_primary,
                 font=('Segoe UI', 9, 'bold')).pack(side='left')
        self.enabled = tk.IntVar()
        self.check = tk.Checkbutton(header, text='Aktif', variable=self.enabled,
            command=self.toggle, bg=app.card_color, fg=app.text_primary,
            selectcolor=app.input_bg, activebackground=app.card_color)
        self.check.pack(side='right')
        controls = tk.Frame(self, bg=app.card_color)
        controls.pack(fill='x', pady=4)
        def button(text, command):
            widget = tk.Button(controls, text=text, command=command, bg=app.input_bg,
                fg=app.text_primary, activebackground=app.accent_color,
                activeforeground='white', bd=0, padx=6, pady=4, font=('Segoe UI', 8))
            widget.pack(side='left', padx=(0, 4))
            return widget
        self.select = button('Konumu Seç', self.begin_select)
        self.remove = button('Seçimi Kaldır', self.remove_region)
        self.center = button('Anlık Konumu Al', self.take_center)
        self.readout = tk.Label(self, text='', bg=app.card_color, fg=app.text_primary,
                                font=('Consolas', 9), anchor='w', justify='left')
        self.readout.pack(fill='x')
        limits = tk.Frame(self, bg=app.card_color)
        limits.pack(fill='x', pady=4)
        self.entries = []
        for label in ('Maks', 'Min'):
            tk.Label(limits, text=label+':', bg=app.card_color, fg=app.text_secondary).pack(side='left')
            entry = tk.Entry(limits, width=7, bg=app.input_bg, fg=app.text_primary,
                             insertbackground=app.text_primary, bd=0)
            entry.pack(side='left', padx=(4, 12), ipady=3)
            entry.bind('<FocusOut>', self.save_limits)
            entry.bind('<Return>', self.save_limits)
            self.entries.append(entry)
        self.status = tk.Label(self, text='Alan seçin', bg=app.card_color,
                               fg=app.text_secondary, anchor='w', wraplength=420,
                               font=('Segoe UI', 8))
        self.status.pack(fill='x')
        self.error_label = tk.Label(self, text='', bg=app.card_color, fg=app.danger_color,
                                    anchor='w', wraplength=420, font=('Segoe UI', 8))
        self.error_label.pack(fill='x')
        self.ocr_help = tk.Frame(self, bg=app.card_color)
        self.retry = tk.Button(self.ocr_help, text='OCR’yi Yeniden Dene',
            command=self.engine.position_controller.retry_ocr, bg=app.input_bg, fg=app.text_primary, bd=0)
        self.retry.pack(side='left', padx=(0, 8), pady=3)
        self.language_settings = tk.Button(self.ocr_help, text='Windows Dil Ayarları',
            command=self.open_language_settings, bg=app.input_bg, fg=app.text_primary, bd=0)
        self.language_settings.pack(side='left', pady=3)
        self.ocr_detail = tk.Label(self, text='', bg=app.card_color, fg=app.text_secondary,
                                   anchor='w', justify='left', wraplength=420, font=('Segoe UI', 8))
        self.job = self.after(100, self.poll)

    def set_profile(self, profile, model):
        if profile != self.profile:
            self.cancel_selection()
            self.pending_center = False
            self.error_label.configure(text='')
        self.profile, self.model = profile, model
        self.enabled.set(int(model.enabled))
        for entry, value in zip(self.entries, (model.maximum, model.minimum)):
            if self.focus_get() is not entry:
                entry.configure(state='normal')
                entry.delete(0, 'end')
                entry.insert(0, f'{value:g}')
        self.engine.position_controller.configure(profile, model)
        self.draw_border()
        self.app.fade_widgets(self, not model.enabled)

    def persist(self):
        self.pending_center = False
        self.app.position_config = self.model
        self.app.save_current_configs_to_profiles()
        self.engine.position_controller.configure(self.profile, self.model)
        self.app.refresh_keys_list_ui()
        self.draw_border()

    def toggle(self):
        if self.engine.is_running:
            self.enabled.set(int(self.model.enabled))
            return
        self.model.enabled = bool(self.enabled.get())
        self.persist()

    def open_language_settings(self):
        try:
            if os.name != 'nt':
                raise OSError('Windows dil ayarları yalnızca Windows üzerinde açılabilir.')
            os.startfile('ms-settings:regionlanguage')
        except OSError as error:
            self.error_label.configure(text=str(error))

    def save_limits(self, _event=None):
        if self.model is None or self.engine.is_running:
            return
        try:
            maximum, minimum = [float(entry.get().replace(',', '.')) for entry in self.entries]
            if not all(math.isfinite(v) for v in (maximum, minimum)) or not 0 <= minimum < maximum:
                raise ValueError
        except ValueError:
            self.error_label.configure(text='0 ≤ Min < Maks olmalı. Önceki değerler korundu.')
            return
        self.error_label.configure(text='')
        if (maximum, minimum) != (self.model.maximum, self.model.minimum):
            self.model.maximum, self.model.minimum = maximum, minimum
            self.persist()

    def begin_select(self):
        if self.engine.is_running:
            return
        self.app.cancel_pixel_pick()
        self.cancel_selection()
        self.selector = RegionSelector(self.winfo_toplevel(), self.selected, self.selection_cancelled)

    def selected(self, region, bounds):
        self.selector = None
        if self.engine.is_running:
            return
        self.model.region, self.model.display = region, bounds
        self.model.monitors = monitor_layout()
        self.persist()

    def selection_cancelled(self, message):
        self.selector = None
        self.status.configure(text=message)

    def remove_region(self):
        if self.engine.is_running:
            return
        self.cancel_selection()
        self.model.region = self.model.display = None
        self.model.monitors = None
        self.persist()

    def take_center(self):
        if self.engine.is_running or not self.model.region or self.pending_center:
            return
        if (self.model.display != screen_bounds() or
                (self.model.monitors is not None and self.model.monitors != monitor_layout())):
            self.error_label.configure(text='Bu bilgisayarın ekran düzeni farklı; önce Konumu Seç ile alanı yeniden seçin.')
            return
        self.pending_center = True
        self.error_label.configure(text='')
        self.status.configure(text='Karakteri sabit tutun; üç tutarlı okuma bekleniyor…')
        self.engine.position_controller.request_center()

    def draw_border(self):
        signature = (self.profile, self.model.region, self.model.display, screen_bounds(), monitor_layout())
        if signature == self._border_signature:
            return
        self._border_signature = signature
        if self.border is not None:
            self.border.destroy()
            self.border = None
        if (self.model.region and self.model.display == signature[3] and
                (self.model.monitors is None or self.model.monitors == signature[4])):
            self.border = RegionBorder(self.winfo_toplevel(), self.model.region)

    def poll(self):
        self.job = None
        if self.disposed:
            return
        if self.model is not None:
            state = self.engine.position_controller.state()
            running = self.engine.is_running
            for widget in (self.select, self.remove, self.center, *self.entries):
                busy = running or (self.pending_center and widget is self.center)
                widget.configure(state='disabled' if busy else 'normal')
            self.check.configure(state='disabled' if running else 'normal')
            if self.selector is not None and running:
                self.cancel_selection()
            if state.get('profile') == self.profile:
                if self.pending_center:
                    self.status.configure(text=f"Merkez doğrulanıyor: {state.get('center_progress', 0)}/3 · Karakteri sabit tutun")
                candidate = state.get('center_candidate')
                if self.pending_center and state.get('center_error'):
                    self.pending_center = False
                    self.error_label.configure(text=state['center_error'])
                if self.pending_center and state.get('available') is False:
                    self.pending_center = False
                if (self.pending_center and candidate and
                        time.monotonic()-state.get('center_stamp', 0) > self.engine.position_controller.FRESH_SECONDS):
                    self.pending_center = False
                    self.error_label.configure(text='Ölçüm güncelliğini yitirdi; merkezi yeniden alın.')
                if (self.pending_center and candidate and not running
                        and time.monotonic()-state.get('center_stamp', 0) <= self.engine.position_controller.FRESH_SECONDS):
                    self.pending_center = False
                    self.model.center = tuple(candidate)
                    self.persist()
                point = state.get('point')
                fresh = time.monotonic()-state.get('stamp', 0) <= self.engine.position_controller.FRESH_SECONDS
                current = f'X {point[0]:.1f}   Y {point[1]:.1f}' if point and fresh else '—'
                center = self.model.center
                reference = f'X {center[0]:.1f}   Y {center[1]:.1f}' if center else 'Kaydedilmedi'
                gap = state.get('distance')
                suffix = f'   Uzaklık: {gap:.1f}' if gap is not None and fresh else ''
                self.readout.configure(text=f'Merkez: {reference}\nŞimdi:  {current}{suffix}')
                if not self.pending_center:
                    issue = self.engine.position_controller.activation_issue(state) if not running else None
                    self.status.configure(text=issue or state.get('status', 'Alan seçin'))
                if state.get('available') is False:
                    self.ocr_help.pack(fill='x')
                    detail = str(state.get('error') or '')[:240]
                    self.ocr_detail.configure(text='Ayrıntı: '+detail if detail else '')
                    self.ocr_detail.pack(fill='x')
                else:
                    self.ocr_help.pack_forget()
                    self.ocr_detail.pack_forget()
                self.retry.configure(state='disabled' if running else 'normal')
                self.language_settings.configure(state='disabled' if running else 'normal')
            self.draw_border()
        self.job = self.after(150, self.poll)

    def cancel_selection(self):
        if self.selector is not None:
            try:
                self.selector.grab_release()
                self.selector.destroy()
            except tk.TclError:
                pass
            self.selector = None

    def dispose(self):
        self.disposed = True
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        self.cancel_selection()
        if self.border is not None:
            self.border.destroy()
            self.border = None
