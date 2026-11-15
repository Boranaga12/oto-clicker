"""A single Tab fallback after the configured unpaused interval."""
from __future__ import annotations

import threading

from .platform_win import foreground_is_ours, foreground_window
from .sequences import writing_layout, grouped_macro_ids
from .models import KeyConfig


class TabWatchdog:
    def __init__(self, engine):
        self.engine = engine
        self.last = {}
        self.lock = threading.RLock()
        self.thread = None

    def start_session(self):
        with self.lock:
            self.last.clear()
            self.started = self.engine.writing_gate.clock()
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name='tab-fallback', daemon=True)
                self.thread.start()

    def record(self, config):
        if config.key.strip().lower() == 'tab' and self.engine.writing_gate.owner is None:
            with self.lock:
                self.last[config.id_token] = self.engine.writing_gate.clock()

    def due(self, config):
        with self.lock:
            return self.engine.writing_gate.clock()-self.last.get(config.id_token, self.started) >= config.tab_refresh_seconds

    def eligible(self, config):
        if config.key.strip().lower() != 'tab' or not config.screen_mode or not config.enabled or not config.has_pixel_target:
            return False
        for group in self.engine.sequence_groups:
            roles, _errors = writing_layout(group)
            if config.id_token in roles or config.id_token in grouped_macro_ids([group]):
                return False
        return True

    def group_due(self, config):
        return (config.key.strip().lower() == 'tab' and config.screen_mode
                and self.engine.writing_gate.owner is None and self.due(config))

    def run(self):
        engine = self.engine
        gate = engine.writing_gate
        while not engine.stop_event.wait(.05):
            if not engine.is_running or not gate.allowed() or gate.writer_pending() or foreground_is_ours():
                continue
            if engine._writing_target is not None and foreground_window() != engine._writing_target:
                continue
            with engine.worker_lock:
                workers = [entry['worker'] for entry in engine._worker_entries.values()
                           if not entry['retiring'] and isinstance(getattr(entry['worker'], 'config', None), KeyConfig)]
            for worker in workers:
                if not self.eligible(worker.config) or not self.due(worker.config):
                    continue
                worker.watchdog_owner = threading.get_ident()
                try:
                    # Recheck under the input lock: a normal Tab may have just fired.
                    worker.press_key(before_press=lambda: self.due(worker.config)
                        and not gate.writer_pending() and not foreground_is_ours()
                        and (engine._writing_target is None or foreground_window() == engine._writing_target))
                finally:
                    worker.watchdog_owner = None

