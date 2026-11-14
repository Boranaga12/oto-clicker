from __future__ import annotations

import random
import threading
import time
from enum import Enum
from contextlib import nullcontext
from typing import Any, Protocol
from collections.abc import Callable

from pynput import keyboard
from pynput.mouse import Button

from .models import KeyConfig, LEFT_MOUSE_NAMES, clamp_click_interval
from .platform_win import MONITOR_COLOR_TOLERANCE, PixelSampler, is_color_close, screen_bounds, foreground_description


RIGHT_MOUSE_NAMES = {"sağ klik", "sag klik", "right click", "sağ tık"}
MIDDLE_MOUSE_NAMES = {"orta klik", "middle click", "orta tık"}
X1_MOUSE_NAMES = {"mouse x1", "x1"}
X2_MOUSE_NAMES = {"mouse x2", "x2"}
MOUSE_NAMES = (
    LEFT_MOUSE_NAMES
    | RIGHT_MOUSE_NAMES
    | MIDDLE_MOUSE_NAMES
    | X1_MOUSE_NAMES
    | X2_MOUSE_NAMES
)


class StepResult(Enum):
    SENT = "sent"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    ERROR = "error"

    def __bool__(self):
        return self is StepResult.SENT


class EngineContext(Protocol):
    enabled_event: threading.Event
    input_lock: threading.RLock
    key_configs: list[KeyConfig]
    mute_all_keys_until: float
    mouse: Any
    refresh_callback: Any
    persist_callback: Any

    def log(self, message: str) -> None: ...

    def log_activity(self, token: str, message: str) -> None: ...

    def extend_mute(self, duration: float) -> None: ...

    def mark_injected_key(self, key_name: str) -> None: ...

    def mark_injected_mouse(self, button: Button) -> None: ...

    def is_config_enabled(self, config: KeyConfig) -> bool: ...

    def set_config_enabled(
        self,
        config: KeyConfig,
        active: bool,
        *,
        trigger_sequence: bool = True,
        runtime_only: bool = False,
    ) -> bool: ...


class StoppableWorker(threading.Thread):
    def __init__(self, *, name: str) -> None:
        super().__init__(name=name, daemon=True)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def wait(self, seconds: float) -> bool:
        return self.stop_event.wait(max(0.0, seconds))


class KeyClickerWorker(StoppableWorker):
    def __init__(self, config: KeyConfig, keyboard_controller: Any, clicker: EngineContext) -> None:
        super().__init__(name=f"macro-{config.id_token[:8]}")
        self.config = config
        self.keyboard_controller = keyboard_controller
        self.clicker = clicker
        self.color_thread: threading.Thread | None = None
        self.last_press_error: Exception | None = None

    @property
    def is_mouse(self) -> bool:
        return self.config.key.strip().lower() in MOUSE_NAMES

    def _mouse_button(self, key_name: str) -> Button | None:
        if key_name in LEFT_MOUSE_NAMES:
            return Button.left
        if key_name in RIGHT_MOUSE_NAMES:
            return Button.right
        if key_name in MIDDLE_MOUSE_NAMES:
            return Button.middle
        if key_name in X1_MOUSE_NAMES and hasattr(Button, "x1"):
            return Button.x1
        if key_name in X2_MOUSE_NAMES and hasattr(Button, "x2"):
            return Button.x2
        return None

    def press_key(self, before_press: Callable[[], bool] | None = None) -> bool:
        gate = getattr(self.clicker, "writing_gate", None)
        if gate is None:
            return self._press_key(before_press)
        with gate.input(lambda: not self._can_run()) as admitted:
            if not admitted:
                return False
            gate.check_focus()
            self.clicker.observe_input_target()
            return self._press_key(before_press)

    def _press_key(self, before_press: Callable[[], bool] | None = None) -> bool:
        self.last_press_error = None
        key_name = self.config.key.strip().lower()
        if not key_name:
            return False

        try:
            mouse_button = self._mouse_button(key_name)
            with self.clicker.input_lock:
                if not self._can_run() or (before_press is not None and not before_press()):
                    return False
                gate = getattr(self.clicker, "writing_gate", None)
                if gate is not None:
                    gate.check_focus()
                if mouse_button is not None:
                    if self.config.has_click_target:
                        original = self.clicker.mouse.position
                        try:
                            self.clicker.mouse.position = (
                                self.config.click_x,
                                self.config.click_y,
                            )
                            # Let the target process observe the cursor move before pressing.
                            if (
                                self.wait(0.03) or not self._can_run()
                                or (before_press is not None and not before_press())
                            ):
                                return False
                            if gate is not None:
                                gate.check_focus()
                            self.clicker.mark_injected_mouse(mouse_button)
                            self.clicker.mouse.press(mouse_button)
                            try:
                                self.wait(random.uniform(0.06, 0.08))
                            finally:
                                self.clicker.mouse.release(mouse_button)
                            # Frame-polled UI buttons must see button-up at the target
                            # before the cursor is restored to the user's position.
                            self.wait(0.05)
                        finally:
                            self.clicker.mouse.position = original
                    else:
                        self.clicker.mark_injected_mouse(mouse_button)
                        self.clicker.mouse.press(mouse_button)
                        try:
                            self.wait(random.uniform(0.06, 0.08))
                        finally:
                            self.clicker.mouse.release(mouse_button)
                    self.clicker.log_activity(
                        self.config.id_token,
                        f"Fare tetiklendi: {self.config.key.upper()} [{self.config.id_token[:6]}]",
                    )
                    return True

                if hasattr(keyboard.Key, key_name):
                    key: Any = getattr(keyboard.Key, key_name)
                elif key_name.startswith("f") and key_name[1:].isdigit():
                    key = keyboard.Key[key_name]
                else:
                    key = key_name

                self.clicker.mark_injected_key(key_name)
                self.keyboard_controller.press(key)
                try:
                    self.wait(random.uniform(0.02, 0.05))
                finally:
                    self.keyboard_controller.release(key)
            self.clicker.log_activity(
                self.config.id_token,
                f"Tuş basıldı: {self.config.key.upper()} [{self.config.id_token[:6]}]",
            )
            return True
        except Exception as exc:
            self.last_press_error = exc
            self.clicker.log_activity(
                f"{self.config.id_token}:error",
                f"Tetikleme hatası ({self.config.key}): {exc}",
            )

        return False

    def monitor_color_loop(self) -> None:
        reference = ""
        self.clicker.log(f"{self.config.key.upper()} için renk değişimi izleniyor.")
        with PixelSampler() as pixels:
            while not self.stop_event.is_set():
                if not self.clicker.enabled_event.is_set() or not self.clicker.is_config_enabled(self.config):
                    self.wait(0.2)
                    continue
                if not self.config.has_click_target:
                    break

                gate = getattr(self.clicker, "writing_gate", None)
                admission = gate.input(lambda: not self._can_run()) if gate is not None else nullcontext(True)
                changed = False
                with admission as admitted:
                    if not admitted:
                        continue
                    if not reference:
                        reference = pixels.get(self.config.click_x, self.config.click_y)
                    if reference:
                        current = pixels.get(self.config.click_x, self.config.click_y)
                        changed = bool(current and not is_color_close(current, reference))
                        if changed:
                            self.clicker.extend_mute(20.0)
                if changed:
                    self.clicker.log(
                        f"{self.config.key.upper()} konumunda renk değişti; "
                        "fare dışı makrolar 20 saniye susturuldu."
                    )
                    if self.wait(20.0):
                        break
                    reference = ""
                else:
                    self.wait(0.1)

    def _can_run(self) -> bool:
        if self.stop_event.is_set() or not self.clicker.enabled_event.is_set() or not self.clicker.is_config_enabled(self.config):
            return False
        if not self.is_mouse and time.monotonic() < self.clicker.mute_all_keys_until:
            return False
        return True

    def _interruptible_delay(self, seconds: float, pixel_check: Any = None) -> bool:
        remaining = max(0.0, seconds)
        gate = getattr(self.clicker, "writing_gate", None)
        while self._can_run():
            if remaining <= 0:
                return True
            step = min(0.02, remaining)
            if gate is not None:
                if gate.wait(step, lambda: not self._can_run()):
                    return False
            elif self.wait(step):
                return False
            remaining -= step
            if pixel_check is not None and pixel_check():
                return False
        return False

    def report_pixel(self, color, target, bounds):
        status = "eşleşiyor" if color and is_color_close(color, target[2], threshold=MONITOR_COLOR_TOLERANCE) else "farklı" if color else "okunamadı"
        self.clicker.log_activity(
            self.config.id_token + ":pixel",
            f"İzleme {self.config.key.upper()} [{self.config.id_token[:6]}] ({target[0]}, {target[1]}): referans={target[2]}, okunan={color or 'yok'}, {status}; tolerans={MONITOR_COLOR_TOLERANCE}; ekran={bounds}; {foreground_description()}",
        )

    def _run_screen_mode(self, pixels: PixelSampler) -> None:
        # Repeat while the condition holds; never queue presses after recovery.
        last_report = None
        while not self.stop_event.is_set():
            if not self._can_run() or not self.config.has_pixel_target:
                self.wait(0.1)
                continue

            target = (self.config.pixel_x, self.config.pixel_y, self.config.target_color, self.config.pixel_screen_bounds)
            bounds = screen_bounds()
            if target[3] is not None and bounds is not None and target[3] != bounds:
                self.clicker.log_activity(self.config.id_token + ":display", "Ekran çözünürlüğü değişti; izleme duraklatıldı. Piksel Seç ile oyun içindeki noktayı yeniden seçin.")
                self.wait(0.2)
                continue
            color = pixels.get(target[0], target[1])
            report = (target, color, bounds)
            if report != last_report:
                self.report_pixel(color, target, bounds)
                last_report = report
            if not color:
                self.wait(0.1)
                continue

            if is_color_close(color, target[2], threshold=MONITOR_COLOR_TOLERANCE):
                self.wait(0.05)
                continue

            delay = clamp_click_interval(self.config.key, self.config.interval_seconds) + random.uniform(
                0.0, self.config.random_seconds
            )

            def color_returned() -> bool:
                if target != (self.config.pixel_x, self.config.pixel_y, self.config.target_color, self.config.pixel_screen_bounds):
                    return True  # A new selection cancels the old pending press.
                current_bounds = screen_bounds()
                if target[3] is not None and current_bounds is not None and current_bounds != target[3]:
                    return True
                current = pixels.get(target[0], target[1])
                return not current or is_color_close(current, target[2], threshold=MONITOR_COLOR_TOLERANCE)

            if (
                self._interruptible_delay(delay, color_returned)
                and self._can_run()
                and not color_returned()
            ):
                if self.press_key(before_press=lambda: not color_returned()):
                    self.execute_chain_actions()

    def ready_for_writing(self) -> bool:
        if not self.config.enabled:
            return False
        if not self.config.screen_mode:
            return True
        if not self.config.has_pixel_target:
            return False
        bounds = screen_bounds()
        if self.config.pixel_screen_bounds is not None and bounds != self.config.pixel_screen_bounds:
            return False
        with PixelSampler() as pixels:
            color = pixels.get(self.config.pixel_x, self.config.pixel_y)
        return bool(color and not is_color_close(color, self.config.target_color,
                                               threshold=MONITOR_COLOR_TOLERANCE))

    def press_once(self, cancel: threading.Event) -> StepResult:
        """A group owns this worker and executes a single step synchronously."""
        def allowed():
            return not cancel.is_set() and self._can_run()
        self.last_press_error = None
        if not allowed():
            return StepResult.CANCELLED if cancel.is_set() else StepResult.SKIPPED
        if self.config.screen_mode:
            if not self.config.has_pixel_target:
                return StepResult.SKIPPED
            target = (self.config.pixel_x, self.config.pixel_y, self.config.target_color, self.config.pixel_screen_bounds)
            with PixelSampler() as pixels:
                def changed():
                    if not allowed() or target != (self.config.pixel_x, self.config.pixel_y, self.config.target_color, self.config.pixel_screen_bounds):
                        return False
                    bounds = screen_bounds()
                    if target[3] is not None and bounds is not None and target[3] != bounds:
                        return False
                    current = pixels.get(target[0], target[1])
                    self.report_pixel(current, target, bounds)
                    return bool(current and not is_color_close(current, target[2], threshold=MONITOR_COLOR_TOLERANCE))
                sent = self.press_key(before_press=changed)
        else:
            sent = self.press_key(before_press=allowed)
        gate = getattr(self.clicker, "writing_gate", None)
        if sent and allowed() and (gate is None or gate.owner != threading.get_ident()):
            self.execute_chain_actions()
        if sent:
            return StepResult.SENT
        if self.last_press_error is not None:
            return StepResult.ERROR
        return StepResult.CANCELLED if cancel.is_set() or not self.clicker.enabled_event.is_set() else StepResult.SKIPPED

    def run(self) -> None:
        if self.wait(random.uniform(0.05, 0.2)):
            return

        if self.is_mouse and self.config.action_chain and self.config.has_click_target:
            watches_color = any(
                action.get("type") == "Sustur"
                and action.get("use_color_change", False)
                for action in self.config.actions
            )
            if watches_color:
                self.color_thread = threading.Thread(
                    target=self.monitor_color_loop,
                    name=f"color-{self.config.id_token[:8]}",
                    daemon=True,
                )
                self.color_thread.start()

        if self.config.screen_mode:
            with PixelSampler() as pixels:
                self._run_screen_mode(pixels)
        else:
            mode_reported = False
            while not self.stop_event.is_set():
                if not self._can_run():
                    mode_reported = False
                    self.wait(0.05)
                    continue
                if not mode_reported:
                    self.clicker.log_activity(
                        self.config.id_token + ":mode",
                        f"Zamanlayıcı {self.config.key.upper()} [{self.config.id_token[:6]}]: izleme kapalı, aralık={self.config.interval_seconds:.3f}, kayıtlı Aktif={self.config.enabled}",
                    )
                    mode_reported = True
                if self.press_key():
                    self.execute_chain_actions()
                delay = clamp_click_interval(self.config.key, self.config.interval_seconds) + random.uniform(
                    0.0, self.config.random_seconds
                )
                self._interruptible_delay(delay)

        if self.color_thread and self.color_thread.is_alive():
            self.color_thread.join(timeout=0.5)

    def execute_chain_actions(self) -> None:
        if not self.config.action_chain:
            return
        gate = getattr(self.clicker, "writing_gate", None)
        cancelled = lambda: self.stop_event.is_set() or not self.clicker.enabled_event.is_set()
        admission = gate.input(cancelled) if gate is not None else nullcontext(True)
        with admission as admitted:
            if admitted:
                self._execute_chain_actions()

    def _execute_chain_actions(self) -> None:
        if not self.config.action_chain:
            return

        changed = False
        for action in self.config.actions:
            action_type = action.get("type", "Aktif Et")
            if action_type == "Aktif Et":
                target_id = str(action.get("target_id", ""))
                for target in self.clicker.key_configs:
                    if target.id_token == target_id and not self.clicker.is_config_enabled(target):
                        changed = self.clicker.set_config_enabled(target, True, runtime_only=True) or changed
                        break
            elif action_type == "Sustur" and not action.get("use_color_change", False):
                try:
                    duration = max(0.0, float(action.get("mute_duration", 1.0)))
                except (TypeError, ValueError):
                    duration = 1.0
                self.clicker.extend_mute(duration)
                self.clicker.log_activity(
                    f"{self.config.id_token}:mute",
                    f"Fare dışı makrolar {duration:.2f} saniye susturuldu."
                )

        if changed:
            if self.clicker.refresh_callback:
                self.clicker.refresh_callback()
