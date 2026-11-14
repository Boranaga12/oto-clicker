from __future__ import annotations

import threading
from collections.abc import Callable

from .sequences import SequenceGroup, SequenceItem, iter_groups


class SequenceRunner:
    """İç içe grupları iptal edilebilir arka plan sıraları olarak çalıştırır."""

    def __init__(
        self,
        activate_macro: Callable[[str], bool],
        persist: Callable[[], None],
        refresh: Callable[[], None],
        state_changed: Callable[[str, bool], None],
        log: Callable[[str], None],
    ) -> None:
        self._activate_macro = activate_macro
        self._persist = persist
        self._refresh = refresh
        self._state_changed = state_changed
        self._log = log
        self._groups: list[SequenceGroup] = []
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._active_groups: set[str] = set()
        self._threads: set[threading.Thread] = set()

    def configure(self, groups: list[SequenceGroup]) -> None:
        self.stop()
        self._groups = groups
        self._stop_event = threading.Event()

    def cancel(self) -> None:
        """Çalışan sıraları iptal et, aynı grup yapısını yeniden kullanılabilir bırak."""
        self.stop()
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        current = threading.current_thread()
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            if thread is not current:
                thread.join(timeout=0.5)
        with self._lock:
            self._threads = {thread for thread in self._threads if thread.is_alive()}
            active = list(self._active_groups)
            self._active_groups.clear()
        for group_id in active:
            self._state_changed(group_id, False)

    def start_group(self, group_id: str) -> bool:
        group = self._find_group(group_id)
        if group is None or not group.children:
            return False
        return self._spawn(group, skip_first=False)

    def trigger_for_macro(self, macro_id: str) -> None:
        for group in list(iter_groups(self._groups)):
            first = group.children[0] if group.children else None
            if first and first.kind == "macro" and first.macro_id == macro_id:
                self._spawn(group, skip_first=True)

    def _start_parents_for_group(self, child_group_id: str) -> None:
        for group in list(iter_groups(self._groups)):
            first = group.children[0] if group.children else None
            if (
                first
                and first.kind == "group"
                and first.group is not None
                and first.group.id_token == child_group_id
            ):
                self._spawn(group, skip_first=True)

    def _find_group(self, group_id: str) -> SequenceGroup | None:
        return next(
            (group for group in iter_groups(self._groups) if group.id_token == group_id),
            None,
        )

    def _spawn(self, group: SequenceGroup, *, skip_first: bool) -> bool:
        with self._lock:
            if group.id_token in self._active_groups or self._stop_event.is_set():
                return False
            self._active_groups.add(group.id_token)

        thread = threading.Thread(
            target=self._run_thread,
            args=(group, skip_first, self._stop_event),
            name=f"sequence-{group.id_token[:8]}",
            daemon=True,
        )
        with self._lock:
            self._threads.add(thread)
        thread.start()
        return True

    def _run_thread(
        self,
        group: SequenceGroup,
        skip_first: bool,
        stop_event: threading.Event,
    ) -> None:
        self._state_changed(group.id_token, True)
        self._log(f"Sıra başladı: {group.name}")
        try:
            self._execute_children(group, skip_first=skip_first, stop_event=stop_event)
        finally:
            with self._lock:
                self._active_groups.discard(group.id_token)
                self._threads.discard(threading.current_thread())
            self._state_changed(group.id_token, False)
            if not stop_event.is_set():
                self._log(f"Sıra tamamlandı: {group.name}")
                self._start_parents_for_group(group.id_token)

    def _execute_children(
        self,
        group: SequenceGroup,
        *,
        skip_first: bool,
        stop_event: threading.Event,
    ) -> None:
        start_index = 1 if skip_first else 0
        for index, item in enumerate(group.children[start_index:], start=start_index):
            if stop_event.is_set():
                return
            if index > 0 and stop_event.wait(max(0.0, item.delay_seconds)):
                return
            self._execute_item(item, stop_event)

    def _execute_item(self, item: SequenceItem, stop_event: threading.Event) -> None:
        if item.kind == "macro" and item.macro_id:
            if self._activate_macro(item.macro_id):
                self._persist()
                self._refresh()
        elif item.kind == "group" and item.group is not None:
            nested = item.group
            with self._lock:
                if nested.id_token in self._active_groups:
                    return
                self._active_groups.add(nested.id_token)
            self._state_changed(nested.id_token, True)
            try:
                self._execute_children(
                    nested,
                    skip_first=False,
                    stop_event=stop_event,
                )
            finally:
                with self._lock:
                    self._active_groups.discard(nested.id_token)
                self._state_changed(nested.id_token, False)
