from __future__ import annotations

import threading
import random
import time
import logging
from collections import defaultdict, deque
from datetime import datetime
from typing import Callable

from pynput import keyboard
from pynput.mouse import Button, Controller, Listener as MouseListener

from .config import AppConfig
from .models import KeyConfig, key_config_from_dict, clamp_click_interval
from .profile_store import DEFAULT_PROFILE, load_profiles
from .sequence_runner import SequenceRunner
from .sequences import SequenceGroup, grouped_macro_ids, sequence_groups_from_list, flatten_groups
from .workers import KeyClickerWorker, StepResult, MOUSE_NAMES
from .writing import WritingGate
from .position_controller import PositionController
from .position_model import PositionConfig
from .tab_watchdog import TabWatchdog
from .platform_win import foreground_window, foreground_is_ours
from .sequences import writing_layout, migrate_group_timing, transition_delay

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
        self._group_workers: dict[str, KeyClickerWorker] = {}
        self._worker_entries = {}

        self.enabled_event = threading.Event()
        self.stop_event = threading.Event()
        self.state_lock = threading.RLock()
        self.worker_lock = threading.RLock()
        self.input_lock = threading.RLock()
        self.writing_gate = WritingGate()
        self.position_controller = PositionController(self)
        self.tab_watchdog = TabWatchdog(self)
        self._writing_target = None
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
            execute_macro=self.execute_group_step,
            macro_delay=self.macro_delay,
            state_changed=self._publish_sequence_state,
            log=self.log,
        )

        self.sequence_runner.clock = self.writing_gate.clock
        self.sequence_runner.execute_writing = self.execute_writing_block
        self.sequence_runner.wait_delay = lambda seconds, stop: self.writing_gate.wait(
            seconds, lambda: stop.is_set() or not self.is_running)

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
        if active and self.position_controller.config.enabled:
            issue = self.position_controller.activation_issue()
            if issue:
                self.log('Konum kontrolü bekliyor; normal makrolar devam edecek. ' + issue)
        if active and not self.is_running:
            for group in self.sequence_groups:
                if not group.enabled:
                    continue
                _roles, errors = writing_layout(group)
                known = {c.id_token for c in self.key_configs}
                if errors or (group.writing_blocks and any(item.macro_id not in known for item in group.children)):
                    self.log(f"{group.name}: " + (errors[0] if errors else "Eksik tuş kaydı."))
                    return
        if active and not self.is_running:
            self.sequence_runner.cancel()
            # Close admission before waking any macro worker on startup.
            self.position_controller.running_changed(True)
        with self.state_lock:
            previous = self.manual_enabled
            self.manual_enabled = active
            if previous != active:
                self.pixel_capture_callback = None
                self.pixel_capture_cancel_callback = None
                self._pixel_capture_down = None
                self.capturing_callback = None
            if active:
                if not previous:
                    self._writing_target = None
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
        if previous and not active:
            self.position_controller.running_changed(False)
        if previous != active:
            self._publish_state(active, reason)
        elif reason:
            self.log(reason)
        if not previous and active:
            self.tab_watchdog.start_session()
            for group in self.sequence_groups:
                if not self.is_running:
                    break
                self.sequence_runner.start_group(group.id_token)
            self._request_refresh()

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
        return changed

    def is_config_enabled(self, config: KeyConfig) -> bool:
        if self.position_manages_config(config):
            return False
        with self.state_lock:
            return self._runtime_enabled.get(config.id_token, config.enabled)

    def position_manages_config(self, config):
        if self.position_controller.reading_lost and not self.position_controller.motion.holding:
            return False
        if not self.position_controller.config.enabled or config.key.lower().strip() not in {'w', 'a', 's', 'd'}:
            return False
        for group in self.sequence_groups:
            roles, _errors = writing_layout(group)
            if config.id_token in roles:
                return False
        return True

    def start_sequence(self, group_id: str) -> bool:
        return self.sequence_runner.start_group(group_id)

    def execute_group_step(self, macro_id: str, cancel: threading.Event) -> StepResult:
        worker = self._group_workers.get(macro_id)
        if cancel.is_set() or not self.is_running:
            return StepResult.CANCELLED
        if any(not group.enabled and macro_id in grouped_macro_ids([group]) for group in self.sequence_groups):
            return StepResult.SKIPPED
        if worker is None or not worker.config.enabled or self.position_manages_config(worker.config):
            return StepResult.SKIPPED
        with self.state_lock:
            self._runtime_enabled[macro_id] = True
        try:
            return worker.press_once(cancel)
        finally:
            with self.state_lock:
                self._runtime_enabled[macro_id] = False

    def observe_input_target(self):
        if self._writing_target is None and (any(g.writing_blocks for g in self.sequence_groups)
                or any(c.key.strip().lower() == 'tab' and c.screen_mode for c in self.key_configs)):
            target = foreground_window()
            if target is not None and not foreground_is_ours():
                self._writing_target = target

    def is_toggle_macro(self, config):
        return config.key.strip().lower() == self.app_config.panic_key.strip().lower()

    def macro_key_sent(self, config):
        self.tab_watchdog.record(config)
        if not self.is_toggle_macro(config):
            return
        # Do not join a runner while this input transaction owns the gate.
        with self.state_lock:
            self.manual_enabled = False
            self.enabled_event.clear()
            self._runtime_enabled.clear()
        self.sequence_runner._stop_event.set()
        self.position_controller.running_changed(False)
        self._publish_state(False, 'Aç/kapa makrosu çalıştı; sistem durduruldu.')

    def abort_writing(self, reason):
        # Never join another runner while this thread owns the writing gate.
        with self.state_lock:
            self.manual_enabled = False
            self.enabled_event.clear()
            self._runtime_enabled.clear()
        self.sequence_runner._stop_event.set()
        self._publish_state(False, "Yazı kesildi; sohbeti kontrol edip yeniden başlatın. " + reason)

    def execute_writing_block(self, group, block, cancel):
        ids = [item.macro_id for item in group.children]
        members = ids[ids.index(block.opening):ids.index(block.closing)+1]
        cancelled = lambda: cancel.is_set() or not self.is_running
        with self.writing_gate.exclusive(cancelled) as admitted:
            if not admitted:
                return False
            workers = [self._group_workers.get(key) for key in members]
            if (time.monotonic() < self.mute_all_keys_until and any(worker and not worker.is_mouse for worker in workers)) or not all(worker and worker.ready_for_writing() for worker in workers):
                return False
            target = self._writing_target or foreground_window()
            if target is not None and foreground_is_ours():
                self.log_activity("writing:focus", "Yazı bekliyor: oyun penceresine geçin.")
                return False
            self._writing_target = target
            def check_focus():
                if target is not None and foreground_window() != target:
                    raise RuntimeError("Oyun penceresinin odağı değişti.")
            self.writing_gate.focus_check = check_focus
            try:
                self.log(f"Yazı başladı: {group.name}")
                items = {item.macro_id: item for item in group.children}
                for index, key in enumerate(members):
                    if cancelled():
                        return False
                    check_focus()
                    started = time.monotonic()
                    result = self.execute_group_step(key, cancel)
                    if not result:
                        if not cancelled():
                            reason = "Tuş gönderilemedi." if result is StepResult.ERROR else "İzleme koşulu değişti."
                            raise RuntimeError(reason)
                        return False
                    item = items[key]
                    if item.gap_seconds is not None:
                        if index == len(members)-1:
                            continue  # Closing wait runs outside the writing reservation.
                        delay = transition_delay(item)
                    else:
                        delay = max(0.0, self.macro_delay(key) - (time.monotonic()-started))
                    if self.writing_gate.wait(delay, cancelled):
                        return False
                self.log(f"Yazı tamamlandı: {group.name}")
                for worker in workers:
                    worker.execute_chain_actions()
                return True
            except Exception as error:
                self.abort_writing(str(error))
                return False

    def macro_delay(self, macro_id: str) -> float:
        for config in self.key_configs:
            if config.id_token == macro_id:
                return clamp_click_interval(config.key, config.interval_seconds) + random.uniform(0.0, config.random_seconds)
        return 0.0

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
            migrate_group_timing(sequence_groups, configs)
            self.sequence_groups = flatten_groups(sequence_groups)
            self.sequence_runner.configure(sequence_groups)
        self.update_key_workers(configs, force_restart=restart)

    def _stop_workers(self) -> bool:
        self._worker_entries.clear()
        for worker in self._group_workers.values():
            worker.stop()
        self._group_workers.clear()
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

    @staticmethod
    def worker_mode(config, grouped):
        # Timing, RGB and coordinates are read live. Only loop architecture needs a restart.
        return (grouped, config.screen_mode, config.key.strip().lower() in MOUSE_NAMES,
                config.action_chain, config.has_click_target,
                any(a.get("type") == "Sustur" and a.get("use_color_change") for a in config.actions))

    def update_key_workers(self, configs: list[KeyConfig], *, force_restart: bool = True) -> None:
        with self.worker_lock:
            self.key_configs = list(configs)
            if self.stop_event.is_set():
                return
            grouped = grouped_macro_ids(self.sequence_groups)
            desired = {config.id_token: (config, self.worker_mode(config, config.id_token in grouped))
                       for config in self.key_configs}
            deadline = time.monotonic() + 1.5
            for key, entry in list(self._worker_entries.items()):
                config, mode = desired.get(key, (None, None))
                if not entry["retiring"] and config is entry["config"] and mode == entry["mode"]:
                    continue
                worker = entry["worker"]
                worker.stop()
                entry["retiring"] = True
                if not entry["mode"][0] and worker is not threading.current_thread():
                    worker.join(timeout=max(0.0, deadline-time.monotonic()))
                if not entry["mode"][0] and worker.is_alive():
                    self.log_activity("worker-retiring:"+key, "Tuş çalışanı kapanıyor; yenisi henüz başlatılmadı.")
                    continue
                del self._worker_entries[key]
            for key, (config, mode) in desired.items():
                if key in self._worker_entries:
                    continue
                worker = KeyClickerWorker(config, self.keyboard, self)
                worker.grouped = mode[0]
                self._worker_entries[key] = dict(worker=worker, config=config, mode=mode, retiring=False)
                if not mode[0]:
                    worker.start()
            order = list(desired) + [key for key in self._worker_entries if key not in desired]
            self.key_workers = [self._worker_entries[key]["worker"] for key in order
                                if key in self._worker_entries and not self._worker_entries[key]["mode"][0]]
            self._group_workers = {key: e["worker"] for key, e in self._worker_entries.items()
                                   if e["mode"][0] and not e["retiring"]}

    def stop(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        self.set_enabled(False)
        self.position_controller.stop()
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
        if button == Button.left and self.pixel_capture_callback is not None and not self.is_running:
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
        if self.capturing_callback is not None and not self.is_running:
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
        if key_name == 'tab' and self.is_running:
            for config in self.key_configs:
                if config.key.strip().lower() == 'tab':
                    self.tab_watchdog.record(config)
        if self.pixel_capture_callback is not None and key_name == "esc" and not self.is_running:
            self.pixel_capture_callback = None
            self._pixel_capture_down = None
            if self.pixel_capture_cancel_callback is not None:
                self.pixel_capture_cancel_callback()
            return
        if self.capturing_callback is not None and not self.is_running:
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
        self.position_controller.configure(active, PositionConfig.from_dict(
            profiles.get('positions', {}).get(active)))
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
