from __future__ import annotations

import os
import threading
import time
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from kodlar.config import AppConfig
from kodlar.engine import RandomizedAutoClicker
from kodlar.models import KeyConfig
from kodlar.sequences import (SequenceGroup, SequenceItem, WritingBlock, writing_layout,
                              move_group_item, sequence_groups_from_list, sequence_group_to_dict)
from kodlar.writing import WritingGate


def group_for(*ids):
    return SequenceGroup(children=[SequenceItem('macro', macro_id=key, delay_seconds=0) for key in ids])


class WritingModelTests(unittest.TestCase):
    def test_multiple_blocks_roles_and_profile_round_trip(self):
        group = group_for('a', 'b', 'c', 'd', 'e', 'f', 'g')
        group.writing_blocks = [WritingBlock('b', 'd'), WritingBlock('e', 'g')]
        loaded = sequence_groups_from_list([sequence_group_to_dict(group)])[0]
        self.assertEqual(loaded, group)
        roles, errors = writing_layout(loaded)
        self.assertFalse(errors)
        self.assertEqual({k: v[0] for k, v in roles.items()},
                         dict(b='open', c='body', d='close', e='open', f='body', g='close'))

    def test_missing_reversed_and_overlapping_boundaries_never_auto_repair(self):
        for blocks in ([WritingBlock('a')], [WritingBlock('deleted', 'c')],
                       [WritingBlock('c', 'a')], [WritingBlock('a', 'c'), WritingBlock('b', 'd')]):
            with self.subTest(blocks=blocks):
                group = group_for('a', 'b', 'c', 'd')
                group.writing_blocks = blocks
                loaded = sequence_groups_from_list([sequence_group_to_dict(group)])[0]
                self.assertTrue(writing_layout(loaded)[1])
                self.assertEqual(loaded.writing_blocks, blocks)

    def test_opening_moves_whole_block_and_body_can_cross_boundary(self):
        group = group_for('x', 'a', 'b', 'c', 'y')
        group.writing_blocks = [WritingBlock('a', 'c')]
        self.assertTrue(move_group_item(group, 'a', 5))
        self.assertEqual([i.macro_id for i in group.children], ['x', 'y', 'a', 'b', 'c'])
        self.assertTrue(move_group_item(group, 'b', 0))
        self.assertNotIn('b', writing_layout(group)[0])
        self.assertTrue(move_group_item(group, 'x', 4))
        self.assertEqual(writing_layout(group)[0]['x'][0], 'body')
        self.assertFalse(move_group_item(group, 'c', 0))


class WritingGateTests(unittest.TestCase):
    def test_reservation_drains_press_blocks_others_and_is_fifo(self):
        gate = WritingGate()
        cancel = threading.Event()
        trace = []
        release = threading.Event()
        started = threading.Event()
        def active():
            with gate.input(cancel.is_set) as admitted:
                self.assertTrue(admitted)
                started.set()
                release.wait(1)
                trace.append('released')
        def writer(name):
            with gate.exclusive(cancel.is_set) as admitted:
                if admitted:
                    trace.append(name)
                    time.sleep(0.015)
        def normal():
            with gate.input(cancel.is_set) as admitted:
                if admitted:
                    trace.append('normal')
        threads = [threading.Thread(target=active)]
        threads[0].start()
        self.assertTrue(started.wait(1))
        for name in ('first', 'second'):
            thread = threading.Thread(target=writer, args=(name,))
            threads.append(thread)
            thread.start()
            deadline = time.monotonic()+1
            while len(gate.waiters) < len(threads)-1 and time.monotonic() < deadline:
                time.sleep(0.001)
        threads.append(threading.Thread(target=normal))
        threads[-1].start()
        self.assertEqual(trace, [])
        release.set()
        for thread in threads:
            thread.join(1)
            self.assertFalse(thread.is_alive())
        self.assertEqual(trace, ['released', 'first', 'second', 'normal'])
        self.assertEqual(gate.active, 0)
        self.assertIsNone(gate.owner)

    def test_paused_clock_and_wait_keep_remaining_time(self):
        gate = WritingGate()
        cancel = threading.Event()
        entered = threading.Event()
        release = threading.Event()
        def writer():
            with gate.exclusive(cancel.is_set):
                entered.set()
                release.wait(1)
        thread = threading.Thread(target=writer)
        thread.start()
        self.assertTrue(entered.wait(1))
        before = gate.clock()
        time.sleep(0.04)
        self.assertAlmostEqual(gate.clock(), before, delta=0.005)
        result = []
        waiter = threading.Thread(target=lambda: result.append(gate.wait(0.04, cancel.is_set)))
        waiter.start()
        time.sleep(0.03)
        self.assertEqual(result, [])
        released_at = time.monotonic()
        release.set()
        thread.join(1)
        waiter.join(1)
        self.assertEqual(result, [False])
        self.assertGreaterEqual(time.monotonic()-released_at, 0.035)

    def test_cancelled_waiter_and_exception_release_ownership(self):
        gate = WritingGate()
        cancel = threading.Event()
        cancel.set()
        with gate.exclusive(cancel.is_set) as admitted:
            self.assertFalse(admitted)
        self.assertFalse(gate.waiters)
        with self.assertRaises(RuntimeError):
            with gate.exclusive(lambda: False):
                raise RuntimeError('test')
        self.assertIsNone(gate.owner)
        self.assertTrue(gate.allowed())


class WritingEngineTests(unittest.TestCase):
    def setUp(self):
        for name in ('Controller', 'keyboard.Controller'):
            patcher = patch('kodlar.engine.'+name, return_value=Mock())
            patcher.start()
            self.addCleanup(patcher.stop)
        self.engine = RandomizedAutoClicker(AppConfig())
        self.addCleanup(self.engine.stop)
        self.configs = [KeyConfig(key, 0.025, 0) for key in ('enter', 'h', 'i', 'enter', 'f1', 'f2')]
        self.group = group_for(*(c.id_token for c in self.configs[:4]))
        self.group.writing_blocks = [WritingBlock(self.configs[0].id_token, self.configs[3].id_token)]
        self.other = group_for(self.configs[5].id_token)

    def configure(self):
        self.engine.configure(self.configs, sequence_groups=[self.group, self.other])

    def test_writing_is_contiguous_with_other_group_and_independent_worker(self):
        self.configure()
        before = deepcopy(self.configs)
        trace = []
        completed = threading.Event()
        def pressed(key):
            trace.append(str(key))
        self.engine.keyboard.press.side_effect = pressed
        self.engine.log_callback = lambda message: completed.set() if 'Yazı tamamlandı' in message else None
        self.engine.set_enabled(True)
        self.assertTrue(completed.wait(2))
        self.engine.set_enabled(False)
        start = trace.index('Key.enter')
        self.assertEqual(trace[start:start+4], ['Key.enter', 'h', 'i', 'Key.enter'])
        self.assertEqual(self.configs, before)
        self.assertIsNone(self.engine.writing_gate.owner)

    def test_incomplete_block_refuses_start(self):
        self.group.writing_blocks[0].closing = ''
        self.configure()
        self.engine.set_enabled(True)
        self.assertFalse(self.engine.is_running)
        self.engine.keyboard.press.assert_not_called()

    def test_disabled_member_skips_entire_block(self):
        self.configs[1].enabled = False
        self.configure()
        self.engine.set_enabled(True)
        time.sleep(0.1)
        self.engine.set_enabled(False)
        keys = [str(call.args[0]) for call in self.engine.keyboard.press.call_args_list]
        self.assertNotIn('Key.enter', keys)
        self.assertNotIn('i', keys)

    def test_changed_monitor_mid_block_stops_all_without_extra_keys(self):
        self.configure()
        self.configs[1].screen_mode = True
        self.configs[1].target_color = '#ffffff'
        # Preflight passes; the final per-press check sees the recovered reference.
        with patch('kodlar.workers.KeyClickerWorker.ready_for_writing', return_value=True), \
             patch('kodlar.workers.PixelSampler') as sampler:
            sampler.return_value.__enter__.return_value.get.return_value = '#ffffff'
            self.engine.set_enabled(True)
            deadline = time.monotonic()+2
            while self.engine.is_running and time.monotonic() < deadline:
                time.sleep(0.005)
        self.assertFalse(self.engine.is_running)
        keys = [str(call.args[0]) for call in self.engine.keyboard.press.call_args_list]
        start = keys.index('Key.enter')
        self.assertEqual(keys[start:], ['Key.enter'])

    def test_focus_loss_stops_everything_and_can_restart(self):
        self.configure()
        focus = [123]
        pressed = threading.Event()
        def key_down(key):
            if str(key) == 'Key.enter':
                pressed.set()
                focus[0] = 456
        self.engine.keyboard.press.side_effect = key_down
        with patch('kodlar.engine.foreground_window', side_effect=lambda: focus[0]), \
             patch('kodlar.engine.foreground_is_ours', return_value=False):
            self.engine.set_enabled(True)
            self.assertTrue(pressed.wait(1))
            deadline = time.monotonic()+1
            while self.engine.is_running and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertFalse(self.engine.is_running)
            self.engine.keyboard.press.side_effect = None
            focus[0] = 123
            self.engine.set_enabled(True)
            self.assertTrue(self.engine.is_running)
            self.engine.set_enabled(False)

    def test_stop_inside_writing_delay_is_cancellable_and_releases_keys(self):
        self.configs[0].interval_seconds = 10
        self.configure()
        down = threading.Event()
        self.engine.keyboard.press.side_effect = lambda key: down.set() if str(key) == 'Key.enter' else None
        self.engine.set_enabled(True)
        self.assertTrue(down.wait(1))
        start = time.monotonic()
        self.engine.set_enabled(False)
        self.assertLess(time.monotonic()-start, 0.4)
        self.assertIsNone(self.engine.writing_gate.owner)
        self.assertTrue(any(str(c.args[0]) == 'Key.enter' for c in self.engine.keyboard.release.call_args_list))

    def test_unreadable_or_matching_pixel_skips_the_whole_block(self):
        self.configs[0].screen_mode = True
        self.configs[0].target_color = '#ffffff'
        self.configure()
        for color in ('', '#ffffff'):
            with self.subTest(color=color), patch('kodlar.workers.PixelSampler') as sampler:
                sampler.return_value.__enter__.return_value.get.return_value = color
                self.engine.set_enabled(True)
                time.sleep(0.07)
                self.engine.set_enabled(False)
        self.assertFalse(any(str(c.args[0]) == 'Key.enter' for c in self.engine.keyboard.press.call_args_list))

    def test_send_failure_stops_all_and_releases_transaction(self):
        self.configure()
        def pressed(key):
            if str(key) == 'h':
                raise OSError('injection failed')
        self.engine.keyboard.press.side_effect = pressed
        self.engine.set_enabled(True)
        deadline = time.monotonic()+1
        while self.engine.is_running and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(self.engine.is_running)
        self.engine.sequence_runner.cancel()
        self.assertIsNone(self.engine.writing_gate.owner)
        keys = [str(c.args[0]) for c in self.engine.keyboard.press.call_args_list]
        start = keys.index('Key.enter')
        self.assertEqual(keys[start:], ['Key.enter', 'h'])

    def test_chain_actions_wait_until_closing_has_been_released(self):
        self.configure()
        close_released = threading.Event()
        released = []
        chains = []
        def release(key):
            released.append(str(key))
            if released.count('Key.enter') == 2:
                close_released.set()
        self.engine.keyboard.release.side_effect = release
        completed = threading.Event()
        for config in self.configs[:4]:
            worker = self.engine._group_workers[config.id_token]
            worker.execute_chain_actions = lambda: chains.append(close_released.is_set())
        self.engine.log_callback = lambda message: completed.set() if 'Yazı tamamlandı' in message else None
        self.engine.set_enabled(True)
        self.assertTrue(completed.wait(1))
        self.engine.set_enabled(False)
        self.assertEqual(chains[:4], [True]*4)

    def test_two_writing_groups_never_interleave_and_both_get_turns(self):
        self.other = group_for(self.configs[4].id_token, self.configs[5].id_token)
        self.other.writing_blocks = [WritingBlock(self.configs[4].id_token, self.configs[5].id_token)]
        self.configure()
        trace = []
        done = threading.Event()
        self.engine.keyboard.press.side_effect = lambda key: trace.append(str(key))
        def log(message):
            if 'Yazı tamamlandı' in message and all(k in trace for k in ('h', 'Key.f1', 'Key.f2')):
                done.set()
        self.engine.log_callback = log
        self.engine.set_enabled(True)
        self.assertTrue(done.wait(2))
        self.engine.set_enabled(False)
        # Each completed opening is followed by only its own body and closing.
        index = 0
        while index < len(trace):
            expected = ['Key.enter', 'h', 'i', 'Key.enter'] if trace[index] == 'Key.enter' else ['Key.f1', 'Key.f2']
            available = min(len(expected), len(trace)-index)
            self.assertEqual(trace[index:index+available], expected[:available])
            index += len(expected)



if __name__ == '__main__':
    unittest.main()
