from __future__ import annotations

import threading
import time
import logging
from collections import defaultdict, deque
from datetime import datetime
from typing import Callable

from pynput import keyboard
from pynput.mouse import Button, Controller, Listener as MouseListener

from .config import AppConfig
from .models import KeyConfig, key_config_from_dict
from .profile_store import DEFAULT_PROFILE, load_profiles
from .sequence_runner import SequenceRunner
from .sequences import SequenceGroup, grouped_macro_ids, sequence_groups_from_list
from .workers import KeyClickerWorker

LOGGER = logging.getLogger(__name__)


LogCallback = Callable[[str], None]
StateCallback = Callable[[bool], None]
SimpleCallback = Callable[[], None]
CaptureCallback = Callable[[str], None]
SequenceStateCallback = Callable[[str, bool], None]


def get_key_name(key: object) -> str:
    if isinstance(key, keyboard.Key):
        return key.name or ""
    char = getattr(key, "char", None)
    if char:
        return str(char).lower()
    return str(key).strip().lower()


def get_mouse_button_name(button: Button) -> str:
    names = {
        Button.left: "sol klik",
        Button.right: "sağ klik",
        Button.middle: "orta klik",
    }
    if hasattr(Button, "x1"):
        names[Button.x1] = "mouse x1"
    if hasattr(Button, "x2"):
        names[Button.x2] = "mouse x2"
    return names.get(button, "")


class RandomizedAutoClicker:
    """Global dinleyicileri ve makro worker'larının yaşam döngüsünü yönetir."""

    def __init__(self, app_config: AppConfig) -> None:
        self.app_config = app_config
        self.mouse = Controller()
        self.keyboard = keyboard.Controller()
        self.key_configs: list[KeyConfig] = []
        self.key_workers: list[KeyClickerWorker] = []
        self.sequence_groups: list[SequenceGroup] = []

        self.enabled_event = threading.Event()
        self.stop_event = threading.Event()
        self.state_lock = threading.RLock()
        self.worker_lock = threading.RLock()
        self.input_lock = threading.RLock()
        self.last_toggle_at = 0.0
        self.manual_enabled = False
        self.mute_all_keys_until = 0.0
        self._runtime_enabled: dict[str, bool] = {}
        self._activity_log_times: dict[str, float] = {}
        self._injected_inputs: dict[tuple[str, str], deque[float]] = defaultdict(deque)

        self.log_callback: LogCallback | None = None
        self.state_callback: StateCallback | None = None
        self.refresh_callback: SimpleCallback | None = None
        self.persist_callback: SimpleCallback | None = None
        self.capturing_callback: CaptureCallback | None = None
        self.pixel_capture_callback: Callable[[int, int], None] | None = None
        self.pixel_capture_cancel_callback: SimpleCallback | None = None
        self._pixel_capture_down: tuple[int, int] | None = None
        self.sequence_state_callback: SequenceStateCallback | None = None
        self.sequence_runner = SequenceRunner(
            activate_macro=self._activate_macro_by_id,
            persist=self._request_persist,
            refresh=self._request_refresh,
            state_changed=self._publish_sequence_state,
            log=self.log,
        )

    @property
    def is_running(self) -> bool:
        return self.enabled_event.is_set()

    def log(self, message: str) -> None:
        formatted = f"[{datetime.now():%H:%M:%S}] {message}"
        LOGGER.info(message)
        print(formatted, flush=True)
        if self.log_callback:
            self.log_callback(formatted)

    def extend_mute(self, duration: float) -> None:
        with self.state_lock:
            self.mute_all_keys_until = max(
                self.mute_all_keys_until,
                time.monotonic() + max(0.0, duration),
            )

    def mark_injected_key(self, key_name: str) -> None:
        """Mark one synthetic key event so the global hook ignores it."""
        self._mark_injected_input("key", key_name)

    def mark_injected_mouse(self, button: Button) -> None:
        """Mark one synthetic mouse event so it cannot toggle the engine."""
        self._mark_injected_input("mouse", get_mouse_button_name(button))

    def _mark_injected_input(self, kind: str, name: str) -> None:
        now = time.monotonic()
        with self.state_lock:
            pending = self._injected_inputs[(kind, name.strip().lower())]
            while pending and pending[0] < now:
                pending.popleft()
            pending.append(now + 0.25)

    def _consume_injected_input(self, kind: str, name: str) -> bool:
        token = (kind, name.strip().lower())
        now = time.monotonic()
        with self.state_lock:
            expirations = self._injected_inputs.get(token)
            if expirations:
                while expirations and expirations[0] < now:
                    expirations.popleft()
                if expirations:
                    expirations.popleft()
                    if not expirations:
                        self._injected_inputs.pop(token, None)
                    return True
                self._injected_inputs.pop(token, None)

            if len(self._injected_inputs) > 32:
                for item, pending in list(self._injected_inputs.items()):
                    while pending and pending[0] < now:
                        pending.popleft()
                    if not pending:
                        self._injected_inputs.pop(item, None)
        return False

    def log_activity(
        self,
        token: str,
        message: str,
        minimum_interval: float = 1.0,
    ) -> None:
        """Yüksek hızlı makroların GUI ve günlük kuyruğunu doldurmasını önle."""
        now = time.monotonic()
        with self.state_lock:
            previous = self._activity_log_times.get(token, 0.0)
            if now - previous < minimum_interval:
                return
            self._activity_log_times[token] = now
        self.log(message)

    def _publish_state(self, active: bool, reason: str | None = None) -> None:
        self.log("Makro başlatıldı." if active else "Makro durduruldu.")
        if reason:
            self.log(reason)
        if self.state_callback:
            self.state_callback(active)

    def set_enabled(self, active: bool, reason: str | None = None) -> None:
        with self.state_lock:
            previous = self.manual_enabled
            self.manual_enabled = active
            if active:
                if not previous:
                    grouped_ids = grouped_macro_ids(self.sequence_groups)
                    self._runtime_enabled = {
                        config.id_token: False if config.id_token in grouped_ids else config.enabled
                        for config in self.key_configs
                    }
                self.enabled_event.set()
            else:
                self.enabled_event.clear()
        if previous and not active:
            self.sequence_runner.cancel()
            with self.state_lock:
                self._runtime_enabled.clear()
        if not previous and active:
            for group in self.sequence_groups:
                self.sequence_runner.start_group(group.id_token)
            self._request_refresh()
        if previous != active:
            self._publish_state(active, reason)
        elif reason:
            self.log(reason)

    def refresh_enabled_state(self, reason: str | None = None) -> None:
        self.set_enabled(self.manual_enabled, reason)

    def toggle_manual(self) -> None:
        with self.state_lock:
            target = not self.manual_enabled
        self.set_enabled(
            target,
            "Sistem aktif edildi." if target else "Sistem durduruldu.",
        )
        self.update_key_workers(self.key_configs, force_restart=False)

    def set_config_enabled(
        self,
        config: KeyConfig,
        active: bool,
        *,
        trigger_sequence: bool = True,
        runtime_only: bool = False,
    ) -> bool:
        with self.state_lock:
            if self.is_running:
                was_active = self._runtime_enabled.get(config.id_token, config.enabled)
                self._runtime_enabled[config.id_token] = active
            elif runtime_only:
                return False
            else:
                was_active = config.enabled
                config.enabled = active
            changed = was_active != active
        if changed and active and trigger_sequence:
            self.sequence_runner.trigger_for_macro(config.id_token)
        return changed

    def is_config_enabled(self, config: KeyConfig) -> bool:
        with self.state_lock:
            return self._runtime_enabled.get(config.id_token, config.enabled)

    def start_sequence(self, group_id: str) -> bool:
        return self.sequence_runner.start_group(group_id)

    def _activate_macro_by_id(self, macro_id: str) -> bool:
        for config in self.key_configs:
            if config.id_token == macro_id:
                return self.set_config_enabled(
                    config,
                    True,
                    trigger_sequence=False,
                    runtime_only=True,
                )
        return False

    def _request_persist(self) -> None:
        if not self.is_running and self.persist_callback:
            self.persist_callback()

    def _request_refresh(self) -> None:
        if self.refresh_callback:
            self.refresh_callback()

    def _publish_sequence_state(self, group_id: str, active: bool) -> None:
        if self.sequence_state_callback:
            self.sequence_state_callback(group_id, active)

    def configure(
        self,
        configs: list[KeyConfig],
        *,
        sequence_groups: list[SequenceGroup] | None = None,
        restart: bool = True,
    ) -> None:
        if sequence_groups is not None:
            self.sequence_groups = sequence_groups
            self.sequence_runner.configure(sequence_groups)
        self.update_key_workers(configs, force_restart=restart)

    def _stop_workers(self) -> bool:
        workers = list(self.key_workers)
        for worker in workers:
            worker.stop()

        current = threading.current_thread()
        deadline = time.monotonic() + 1.5
        for worker in workers:
            if worker is not current:
                worker.join(timeout=max(0.0, deadline - time.monotonic()))

        alive = [worker for worker in workers if worker.is_alive()]
        self.key_workers = alive
        if alive:
            names = ", ".join(worker.name for worker in alive)
            self.log(f"Bazı makro iş parçacıkları zamanında kapanmadı: {names}")
        return not alive

    def update_key_workers(
        self,
        configs: list[KeyConfig],
        *,
        force_restart: bool = True,
    ) -> None:
        with self.worker_lock:
            self.key_configs = list(configs)
            if not force_restart and self.key_workers:
                return

            if not self._stop_workers():
                self.log("Makrolar güvenli biçimde yenilenemedi; yeniden denenecek.")
                return
            if self.stop_event.is_set():
                return

            self.key_workers = [
                KeyClickerWorker(config, self.keyboard, self)
                for config in self.key_configs
            ]
            for worker in self.key_workers:
                worker.start()

    def stop(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        self.set_enabled(False)
        self.sequence_runner.stop()
        with self.worker_lock:
            self._stop_workers()

    def on_mouse_click(
        self,
        x: int,
        y: int,
        button: Button,
        pressed: bool,
    ) -> bool:
        if self.stop_event.is_set():
            return True
        button_name = get_mouse_button_name(button)
        if not button_name:
            return True
        if pressed and self._consume_injected_input("mouse", button_name):
            return True
        if button == Button.left and self.pixel_capture_callback is not None:
            if pressed:
                self._pixel_capture_down = (x, y)
            elif self._pixel_capture_down is not None:
                point = self._pixel_capture_down
                self._pixel_capture_down = None
                callback = self.pixel_capture_callback
                self.pixel_capture_callback = None
                callback(*point)
            return True
        if not pressed:
            return True
        if self.capturing_callback is not None:
            self.capturing_callback(button_name)
            return True
        if button != Button.middle:
            return True

        now = time.monotonic()
        with self.state_lock:
            if now - self.last_toggle_at < 0.25:
                return True
            self.last_toggle_at = now
        self.toggle_manual()
        return True

    def on_key_press(self, key: keyboard.KeyCode | keyboard.Key) -> None:
        key_name = get_key_name(key)
        if not key_name:
            return
        if self._consume_injected_input("key", key_name):
            return
        if self.pixel_capture_callback is not None and key_name == "esc":
            self.pixel_capture_callback = None
            self._pixel_capture_down = None
            if self.pixel_capture_cancel_callback is not None:
                self.pixel_capture_cancel_callback()
            return
        if self.capturing_callback is not None:
            self.capturing_callback(key_name)
            return
        if key_name != self.app_config.panic_key.strip().lower():
            return

        self.toggle_manual()
        if self.refresh_callback:
            self.refresh_callback()

    def _load_initial_profile(self) -> None:
        if self.key_configs:
            return
        profiles = load_profiles()
        active = profiles.get("active_profile", DEFAULT_PROFILE)
        configs = [
            key_config_from_dict(item)
            for item in profiles["profiles"].get(active, [])
            if isinstance(item, dict)
        ]
        groups = sequence_groups_from_list(
            profiles.get("groups", {}).get(active, [])
        )
        self.configure(configs, sequence_groups=groups)

    def run(self) -> None:
        try:
            self._load_initial_profile()
            with keyboard.Listener(on_press=self.on_key_press) as keyboard_listener, \
                    MouseListener(on_click=self.on_mouse_click) as mouse_listener:
                self.log(
                    "Hazır. Kısayol tuşu veya orta fare tuşuyla sistemi "
                    "başlatıp durdurabilirsiniz."
                )
                self.stop_event.wait()
                keyboard_listener.stop()
                mouse_listener.stop()
        except Exception as exc:
            self.log(f"Motor hatası: {exc}")
        finally:
            self.stop()
