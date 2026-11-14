from __future__ import annotations

import random
import threading
import time
from typing import Any, Protocol

from pynput import keyboard
from pynput.mouse import Button

from .models import KeyConfig
from .platform_win import PixelSampler, is_color_close


LEFT_MOUSE_NAMES = {"sol klik", "left click", "sol tık"}
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

    def set_config_enabled(
        self,
        config: KeyConfig,
        active: bool,
        *,
        trigger_sequence: bool = True,
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

    def press_key(self) -> None:
        key_name = self.config.key.strip().lower()
        if not key_name:
            return

        try:
            mouse_button = self._mouse_button(key_name)
            with self.clicker.input_lock:
                if mouse_button is not None:
                    self.clicker.mark_injected_mouse(mouse_button)
                    if self.config.has_click_target:
                        original = self.clicker.mouse.position
                        try:
                            self.clicker.mouse.position = (
                                self.config.click_x,
                                self.config.click_y,
                            )
                            # Let the target process observe the cursor move before pressing.
                            if self.wait(0.03) or not self._can_run():
                                return
                            self.clicker.mouse.press(mouse_button)
                            try:
                                self.wait(random.uniform(0.06, 0.08))
                            finally:
                                self.clicker.mouse.release(mouse_button)
                        finally:
                            self.clicker.mouse.position = original
                    else:
                        self.clicker.mouse.press(mouse_button)
                        try:
                            self.wait(random.uniform(0.06, 0.08))
                        finally:
                            self.clicker.mouse.release(mouse_button)
                    self.clicker.log_activity(
                        self.config.id_token,
                        f"Fare tetiklendi: {self.config.key.upper()}",
                    )
                    return

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
                f"Tuş basıldı: {self.config.key.upper()}",
            )
        except Exception as exc:
            self.clicker.log_activity(
                f"{self.config.id_token}:error",
                f"Tetikleme hatası ({self.config.key}): {exc}",
            )

    def monitor_color_loop(self) -> None:
        reference = ""
        self.clicker.log(f"{self.config.key.upper()} için renk değişimi izleniyor.")
        with PixelSampler() as pixels:
            while not self.stop_event.is_set():
                if not self.clicker.enabled_event.is_set() or not self.config.enabled:
                    self.wait(0.2)
                    continue
                if not self.config.has_click_target:
                    break

                if not reference:
                    reference = pixels.get(self.config.click_x, self.config.click_y)
                    if not reference:
                        self.wait(0.2)
                        continue

                current = pixels.get(self.config.click_x, self.config.click_y)
                if current and not is_color_close(current, reference):
                    self.clicker.extend_mute(20.0)
                    self.clicker.log(
                        f"{self.config.key.upper()} konumunda renk değişti; "
                        "fare dışı makrolar 20 saniye susturuldu."
                    )
                    if self.wait(20.0):
                        break
                    reference = pixels.get(self.config.click_x, self.config.click_y)
                else:
                    self.wait(0.1)

    def _can_run(self) -> bool:
        if not self.clicker.enabled_event.is_set() or not self.config.enabled:
            return False
        if not self.is_mouse and time.monotonic() < self.clicker.mute_all_keys_until:
            return False
        return True

    def _interruptible_delay(self, seconds: float, pixel_check: Any = None) -> bool:
        deadline = time.monotonic() + max(0.0, seconds)
        while not self.stop_event.is_set() and self._can_run():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            if self.wait(min(0.05, remaining)):
                return False
            if pixel_check is not None and pixel_check():
                return False
        return False

    def _run_screen_mode(self, pixels: PixelSampler) -> None:
        # Her renk-yokluğu döneminde yalnızca bir kez tetikle.
        triggered = False
        target = None
        while not self.stop_event.is_set():
            current_target = (
                self.config.pixel_x, self.config.pixel_y,
                self.config.target_color, self.config.invert_color,
            )
            if current_target != target:
                target = current_target
                triggered = False
            if not self._can_run() or not self.config.has_pixel_target:
                triggered = False
                self.wait(0.1)
                continue

            color = pixels.get(self.config.pixel_x, self.config.pixel_y)
            if not color:
                self.wait(0.1)
                continue

            matches = is_color_close(color, self.config.target_color)
            should_trigger = matches if self.config.invert_color else not matches
            if not should_trigger:
                triggered = False
                self.wait(0.05)
                continue
            if triggered:
                self.wait(0.05)
                continue

            delay = self.config.interval_seconds + random.uniform(
                0.0, self.config.random_seconds
            )

            def color_returned() -> bool:
                current = pixels.get(self.config.pixel_x, self.config.pixel_y)
                if not current:
                    return True  # Do not act on an unreadable pixel.
                matches_now = is_color_close(current, self.config.target_color)
                return not (matches_now if self.config.invert_color else not matches_now)

            if (
                self._interruptible_delay(delay, color_returned)
                and self._can_run()
                and not color_returned()
            ):
                self.press_key()
                self.execute_chain_actions()
                triggered = True

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
            while not self.stop_event.is_set():
                if not self._can_run():
                    self.wait(0.05)
                    continue
                self.press_key()
                self.execute_chain_actions()
                delay = self.config.interval_seconds + random.uniform(
                    0.0, self.config.random_seconds
                )
                self._interruptible_delay(delay)

        if self.color_thread and self.color_thread.is_alive():
            self.color_thread.join(timeout=0.5)

    def execute_chain_actions(self) -> None:
        if not self.config.action_chain:
            return

        changed = False
        for action in self.config.actions:
            action_type = action.get("type", "Aktif Et")
            if action_type == "Aktif Et":
                target_id = str(action.get("target_id", ""))
                for target in self.clicker.key_configs:
                    if target.id_token == target_id and not target.enabled:
                        changed = self.clicker.set_config_enabled(target, True)
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
            if self.clicker.persist_callback:
                self.clicker.persist_callback()
            if self.clicker.refresh_callback:
                self.clicker.refresh_callback()
