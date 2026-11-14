from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .sequences import SequenceGroup, flatten_groups, writing_layout


class SequenceRunner:
    """One ordered, cancellable loop per flat group; no background macro overlap."""

    def __init__(self, execute_macro: Callable[[str, threading.Event], bool],
                 macro_delay: Callable[[str], float],
                 state_changed: Callable[[str, bool], None], log: Callable[[str], None]):
        self.clock = lambda: time.monotonic()
        self.execute_writing = None
        self.wait_delay = lambda seconds, stop: stop.wait(seconds)
        self._execute_macro = execute_macro
        self._macro_delay = macro_delay
        self._state_changed = state_changed
        self._log = log
        self._groups: list[SequenceGroup] = []
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}

    def configure(self, groups: list[SequenceGroup]) -> None:
        self.cancel()
        self._groups = flatten_groups(groups)

    def cancel(self) -> None:
        self.stop()
        with self._lock:
            if not self._threads:
                self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1.0)

    def start_group(self, group_id: str) -> bool:
        group = next((item for item in self._groups if item.id_token == group_id), None)
        if group is None or not group.children:
            return False
        with self._lock:
            if self._stop_event.is_set() or group_id in self._threads:
                return False
            thread = threading.Thread(target=self._run, args=(group, self._stop_event),
                                      name=f'sequence-{group_id[:8]}', daemon=True)
            self._threads[group_id] = thread
            thread.start()
        return True

    def _run(self, group: SequenceGroup, stop: threading.Event) -> None:
        try:
            self._state_changed(group.id_token, True)
            self._log(f'Sıra başladı: {group.name}')
            while not stop.is_set():
                executed = False
                roles, errors = writing_layout(group)
                if errors:
                    raise ValueError(errors[0])
                for item in group.children:
                    role, block = roles.get(item.macro_id, (None, None))
                    if role in ("body", "close"):
                        continue
                    if role == "open":
                        if self.execute_writing is not None:
                            executed = self.execute_writing(group, block, stop) or executed
                        continue
                    if stop.is_set():
                        return
                    started = self.clock()
                    if self._execute_macro(item.macro_id, stop):
                        executed = True
                        period = max(0.001, self._macro_delay(item.macro_id))
                        remaining = max(0.0, period - (self.clock() - started))
                        if self.wait_delay(remaining, stop):
                            return
                if not executed:
                    stop.wait(0.05)  # Disabled/matching monitored steps must not busy-loop.
        except Exception as error:
            self._log(f'Grup durduruldu ({group.name}): {error}')
        finally:
            with self._lock:
                self._threads.pop(group.id_token, None)
            self._state_changed(group.id_token, False)
