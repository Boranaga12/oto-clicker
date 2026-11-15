from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import Mock, patch

from kodlar.sequence_runner import SequenceRunner
from kodlar.sequences import SequenceGroup, SequenceItem, WritingBlock, sequence_group_to_dict, sequence_groups_from_list, migrate_group_timing
from kodlar.models import KeyConfig
from types import SimpleNamespace


class SequenceTests(unittest.TestCase):
    def test_transition_migration_preserves_legacy_values_once(self):
        config = KeyConfig('a', .4, .2)
        group = SequenceGroup(children=[SequenceItem('macro', macro_id=config.id_token)])
        migrate_group_timing([group], [config])
        self.assertEqual((group.children[0].gap_seconds, group.children[0].gap_random_seconds), (.4, .2))
        config.interval_seconds = 9
        migrate_group_timing([group], [config])
        restored = sequence_groups_from_list([sequence_group_to_dict(group)])[0].children[0]
        self.assertEqual((restored.gap_seconds, restored.gap_random_seconds), (.4, .2))

    def test_explicit_transition_waits_after_release_and_adds_random_once(self):
        clock, waits = [0.0], []
        class Stop:
            def is_set(self): return False
            def wait(self, seconds):
                waits.append(seconds)
                return True
        def execute(_key, _stop):
            clock[0] += .28
            return True
        group = SequenceGroup(children=[SequenceItem('macro', macro_id='a', gap_seconds=.2, gap_random_seconds=.3)])
        legacy = Mock(side_effect=AssertionError('Legacy card timing used'))
        runner = self.runner(execute, legacy)
        with patch('kodlar.sequences.random.uniform', return_value=.1) as jitter, \
             patch('kodlar.sequence_runner.time.monotonic', side_effect=lambda: clock[0]):
            runner._run(group, Stop())
        self.assertAlmostEqual(waits[0], .3)
        jitter.assert_called_once_with(0.0, .3)
        legacy.assert_not_called()

    def test_skipped_card_does_not_wait_or_repeat_its_monitor(self):
        calls, waits = [], []
        class Stop:
            def is_set(self): return False
            def wait(self, seconds):
                waits.append(seconds)
                return True
        group = SequenceGroup(children=[SequenceItem('macro', macro_id='a', gap_seconds=99),
                                        SequenceItem('macro', macro_id='b', gap_seconds=.2)])
        runner = self.runner(lambda key, _stop: calls.append(key) or key == 'b')
        runner._run(group, Stop())
        self.assertEqual(calls, ['a', 'b'])
        self.assertEqual(waits, [.2])

    def test_input_error_stops_group_instead_of_advancing_to_next_card(self):
        errors, calls = [], []
        runner = self.runner(lambda key, _stop: calls.append(key) or SimpleNamespace(value='error'))
        runner._log = errors.append
        group = SequenceGroup(children=[SequenceItem('macro', macro_id='a', gap_seconds=0), SequenceItem('macro', macro_id='b')])
        runner._run(group, threading.Event())
        self.assertEqual(calls, ['a'])
        self.assertIn('gönderilemedi', errors[-1])

    def test_writing_closing_transition_runs_once_outside_the_block(self):
        waits = []
        class Stop:
            def is_set(self): return False
            def wait(self, seconds):
                waits.append(seconds)
                return True
        group = SequenceGroup(children=[SequenceItem('macro', macro_id=key, gap_seconds=delay)
            for key, delay in (('open', .1), ('body', .2), ('close', .4))],
            writing_blocks=[WritingBlock('open', 'close')])
        execute = Mock()
        runner = self.runner(execute)
        runner.execute_writing = Mock(return_value=True)
        runner._run(group, Stop())
        self.assertEqual(waits, [.4])
        execute.assert_not_called()
        runner.execute_writing.assert_called_once()

    def runner(self, execute, delay=lambda _macro_id: 0.01):
        return SequenceRunner(execute, delay, lambda *_args: None, lambda _message: None)

    def test_legacy_nested_groups_flatten_in_order_without_duplicate_macros(self):
        nested = SequenceGroup(children=[SequenceItem('macro', macro_id='b'), SequenceItem('macro', macro_id='a')])
        source = SequenceGroup(name='Ana', children=[SequenceItem('macro', macro_id='a'), SequenceItem('group', group=nested), SequenceItem('macro', macro_id='c')])
        groups = sequence_groups_from_list([sequence_group_to_dict(source)])
        self.assertEqual([item.macro_id for item in groups[0].children], ['a', 'b', 'c'])
        self.assertTrue(all(item.kind == 'macro' for item in groups[0].children))

    def test_same_macro_cannot_run_in_two_groups(self):
        source = [{'name': 'A', 'children': [{'kind': 'macro', 'macro_id': 'a'}]},
                  {'name': 'B', 'children': [{'kind': 'macro', 'macro_id': 'a'}, {'kind': 'macro', 'macro_id': 'b'}]}]
        groups = sequence_groups_from_list(source)
        self.assertEqual([[item.macro_id for item in group.children] for group in groups], [['a'], ['b']])

    def test_group_repeats_in_order_and_never_overlaps_its_steps(self):
        calls = []
        finished = threading.Event()
        active = []
        def execute(macro_id, _stop):
            active.append(macro_id)
            self.assertEqual(len(active), 1)
            calls.append(macro_id)
            active.pop()
            if len(calls) == 4:
                finished.set()
            return True
        runner = self.runner(execute, lambda _id: 0.02)
        group = SequenceGroup(children=[SequenceItem('macro', macro_id='a'), SequenceItem('macro', macro_id='b')])
        runner.configure([group])
        self.assertTrue(runner.start_group(group.id_token))
        self.assertFalse(runner.start_group(group.id_token))
        self.assertTrue(finished.wait(1))
        runner.stop()
        self.assertEqual(calls[:4], ['a', 'b', 'a', 'b'])

    def test_automatic_delays_replace_legacy_manual_transition_values(self):
        calls, waits = [], []
        class Stop:
            done = False
            def is_set(self): return self.done
            def wait(self, seconds):
                waits.append(seconds)
                self.done = len(waits) == 3
                return self.done
        group = SequenceGroup(children=[SequenceItem('macro', macro_id='a', delay_seconds=999), SequenceItem('macro', macro_id='b', delay_seconds=888)])
        runner = self.runner(lambda key, _stop: calls.append(key) or True, lambda key: {'a': 0.2, 'b': 0.4}[key])
        with patch('kodlar.sequence_runner.time.monotonic', return_value=0):
            runner._run(group, Stop())
        self.assertEqual(calls, ['a', 'b', 'a'])
        self.assertEqual(waits, [0.2, 0.4, 0.2])

    def test_time_spent_pressing_is_not_added_as_extra_transition_delay(self):
        clock, waits = [0.0], []
        class Stop:
            done = False
            def is_set(self): return self.done
            def wait(self, seconds):
                waits.append(seconds)
                self.done = True
                return True
        def execute(_key, _stop):
            clock[0] += 0.08
            return True
        group = SequenceGroup(children=[SequenceItem('macro', macro_id='a')])
        runner = self.runner(execute, lambda _id: 0.1)
        with patch('kodlar.sequence_runner.time.monotonic', side_effect=lambda: clock[0]):
            runner._run(group, Stop())
        self.assertAlmostEqual(waits[0], 0.02)

    def test_stop_interrupts_a_long_automatic_delay_and_allows_restart(self):
        calls = []
        fired = threading.Event()
        def execute(key, _stop):
            calls.append(key)
            fired.set()
            return True
        runner = self.runner(execute, lambda _id: 5.0)
        group = SequenceGroup(children=[SequenceItem('macro', macro_id='a'), SequenceItem('macro', macro_id='b')])
        runner.configure([group])
        runner.start_group(group.id_token)
        self.assertTrue(fired.wait(1))
        before = time.monotonic()
        runner.cancel()
        self.assertLess(time.monotonic() - before, 0.5)
        self.assertEqual(calls, ['a'])
        fired.clear()
        self.assertTrue(runner.start_group(group.id_token))
        self.assertTrue(fired.wait(1))
        runner.stop()
        self.assertEqual(calls, ['a', 'a'])

    def test_matching_or_disabled_steps_do_not_busy_loop(self):
        execute = Mock(return_value=False)
        delay = Mock(return_value=1)
        runner = self.runner(execute, delay)
        group = SequenceGroup(children=[SequenceItem('macro', macro_id='a')])
        runner.configure([group])
        runner.start_group(group.id_token)
        time.sleep(0.12)
        runner.stop()
        self.assertLess(execute.call_count, 6)
        delay.assert_not_called()


if __name__ == '__main__':
    unittest.main()
