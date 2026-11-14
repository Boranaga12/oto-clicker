from __future__ import annotations

import threading
import time
import unittest

from kodlar.sequence_runner import SequenceRunner
from kodlar.sequences import (
    SequenceGroup,
    SequenceItem,
    sequence_group_from_dict,
    sequence_group_to_dict,
)


class SequenceTests(unittest.TestCase):
    def test_group_round_trip_preserves_nested_order(self) -> None:
        nested = SequenceGroup(
            name="İç Grup",
            children=[SequenceItem(kind="macro", macro_id="b")],
        )
        source = SequenceGroup(
            name="Ana Grup",
            children=[
                SequenceItem(kind="macro", macro_id="a", delay_seconds=0),
                SequenceItem(kind="group", group=nested, delay_seconds=1.25),
            ],
        )
        restored = sequence_group_from_dict(sequence_group_to_dict(source))
        self.assertEqual(restored.name, "Ana Grup")
        self.assertEqual(restored.children[0].macro_id, "a")
        self.assertEqual(restored.children[1].delay_seconds, 1.25)
        self.assertEqual(restored.children[1].group.name, "İç Grup")

    def test_first_macro_activation_starts_remaining_members(self) -> None:
        activated: list[str] = []
        finished = threading.Event()
        group = SequenceGroup(
            name="Sıra",
            children=[
                SequenceItem(kind="macro", macro_id="first", delay_seconds=0),
                SequenceItem(kind="macro", macro_id="second", delay_seconds=0.01),
                SequenceItem(kind="macro", macro_id="third", delay_seconds=0.01),
            ],
        )
        runner = SequenceRunner(
            activate_macro=lambda macro_id: activated.append(macro_id) is None,
            persist=lambda: None,
            refresh=lambda: None,
            state_changed=lambda _group_id, active: finished.set() if not active else None,
            log=lambda _message: None,
        )
        runner.configure([group])
        runner.trigger_for_macro("first")
        self.assertTrue(finished.wait(1.0))
        self.assertEqual(activated, ["second", "third"])
        runner.stop()

    def test_nested_group_completes_before_next_sibling(self) -> None:
        activated: list[str] = []
        finished = threading.Event()
        nested = SequenceGroup(
            name="İç",
            children=[
                SequenceItem(kind="macro", macro_id="nested-1"),
                SequenceItem(kind="macro", macro_id="nested-2", delay_seconds=0.01),
            ],
        )
        root = SequenceGroup(
            name="Ana",
            children=[
                SequenceItem(kind="macro", macro_id="root-1"),
                SequenceItem(kind="group", group=nested, delay_seconds=0.01),
                SequenceItem(kind="macro", macro_id="root-2", delay_seconds=0.01),
            ],
        )
        runner = SequenceRunner(
            activate_macro=lambda macro_id: activated.append(macro_id) is None,
            persist=lambda: None,
            refresh=lambda: None,
            state_changed=lambda group_id, active: (
                finished.set() if group_id == root.id_token and not active else None
            ),
            log=lambda _message: None,
        )
        runner.configure([root])
        self.assertTrue(runner.start_group(root.id_token))
        self.assertTrue(finished.wait(1.0))
        self.assertEqual(
            activated,
            ["root-1", "nested-1", "nested-2", "root-2"],
        )
        runner.stop()

    def test_nested_first_member_continues_parent_after_nested_finishes(self) -> None:
        activated: list[str] = []
        finished = threading.Event()
        nested = SequenceGroup(
            name="İç",
            children=[
                SequenceItem(kind="macro", macro_id="nested-1"),
                SequenceItem(kind="macro", macro_id="nested-2", delay_seconds=0.01),
            ],
        )
        root = SequenceGroup(
            name="Ana",
            children=[
                SequenceItem(kind="group", group=nested),
                SequenceItem(kind="macro", macro_id="root-2", delay_seconds=0.01),
            ],
        )
        runner = SequenceRunner(
            activate_macro=lambda macro_id: activated.append(macro_id) is None,
            persist=lambda: None,
            refresh=lambda: None,
            state_changed=lambda group_id, active: (
                finished.set() if group_id == root.id_token and not active else None
            ),
            log=lambda _message: None,
        )
        runner.configure([root])
        runner.trigger_for_macro("nested-1")
        self.assertTrue(finished.wait(1.0))
        self.assertEqual(activated, ["nested-2", "root-2"])
        runner.stop()

    def test_stopping_group_interrupts_long_delay(self) -> None:
        activated: list[str] = []
        group = SequenceGroup(
            children=[
                SequenceItem(kind="macro", macro_id="first"),
                SequenceItem(kind="macro", macro_id="second", delay_seconds=5.0),
            ]
        )
        runner = SequenceRunner(
            activate_macro=lambda macro_id: activated.append(macro_id) is None,
            persist=lambda: None,
            refresh=lambda: None,
            state_changed=lambda _group_id, _active: None,
            log=lambda _message: None,
        )
        runner.configure([group])
        runner.start_group(group.id_token)
        time.sleep(0.02)
        runner.stop()
        self.assertEqual(activated, ["first"])

    def test_cancel_allows_group_to_be_started_again(self) -> None:
        activated: list[str] = []
        finished = threading.Event()
        group = SequenceGroup(
            children=[SequenceItem(kind="macro", macro_id="first")]
        )
        runner = SequenceRunner(
            activate_macro=lambda macro_id: activated.append(macro_id) is None,
            persist=lambda: None,
            refresh=lambda: None,
            state_changed=lambda _group_id, active: finished.set() if not active else None,
            log=lambda _message: None,
        )
        runner.configure([group])
        runner.cancel()
        self.assertTrue(runner.start_group(group.id_token))
        self.assertTrue(finished.wait(1.0))
        self.assertEqual(activated, ["first"])
        runner.stop()


if __name__ == "__main__":
    unittest.main()
