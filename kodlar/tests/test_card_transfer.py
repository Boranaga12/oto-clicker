from __future__ import annotations

import unittest

from kodlar.models import KeyConfig
from kodlar.sequences import SequenceGroup, SequenceItem, WritingBlock, transfer_macro, writing_layout


class CardTransferTests(unittest.TestCase):
    def setUp(self):
        self.configs = [KeyConfig(key, .7, .1) for key in ('a', 'b', 'c', 'd')]
        self.ids = [c.id_token for c in self.configs]
        self.group = SequenceGroup(children=[SequenceItem('macro', macro_id=self.ids[1], gap_seconds=.4)])
        self.other = SequenceGroup()
        self.groups = [self.group, self.other]

    def move(self, key, destination, index):
        return transfer_macro(self.configs, self.groups, key, destination, index)

    def test_independent_card_enters_group_with_timing_and_no_duplicate(self):
        self.assertTrue(self.move(self.ids[0], self.group, 0))
        self.assertEqual([i.macro_id for i in self.group.children], self.ids[:2])
        self.assertEqual((self.group.children[0].gap_seconds, self.group.children[0].gap_random_seconds), (.7, .1))
        self.assertEqual(len(self.configs), 4)

    def test_group_card_moves_out_before_a_chosen_independent_card(self):
        self.assertTrue(self.move(self.ids[1], None, 1))
        self.assertEqual(self.group.children, [])
        self.assertEqual([c.id_token for c in self.configs], self.ids)

    def test_independent_card_reorders_in_both_directions(self):
        self.assertTrue(self.move(self.ids[0], None, 3))
        roots = [c.id_token for c in self.configs if c.id_token != self.ids[1]]
        self.assertEqual(roots, [self.ids[2], self.ids[3], self.ids[0]])
        self.assertTrue(self.move(self.ids[0], None, 0))
        self.assertEqual(self.configs[0].id_token, self.ids[0])

    def test_group_transfer_preserves_transition_settings(self):
        item = self.group.children[0]
        self.assertTrue(self.move(self.ids[1], self.other, 0))
        self.assertIs(self.other.children[0], item)
        self.assertEqual(item.gap_seconds, .4)
        self.assertEqual(self.group.children, [])

    def test_disabled_group_rejects_transfer_without_mutation(self):
        self.group.enabled = False
        self.assertFalse(self.move(self.ids[0], self.group, 0))
        self.assertFalse(self.move(self.ids[1], None, 0))
        self.assertEqual(len(self.group.children), 1)

    def test_writing_section_moves_as_whole_to_another_group(self):
        self.group.children = [SequenceItem('macro', macro_id=key) for key in self.ids[:3]]
        block = WritingBlock(self.ids[0], self.ids[2])
        self.group.writing_blocks = [block]
        self.assertFalse(self.move(self.ids[1], self.other, 0))
        self.assertFalse(self.move(self.ids[0], None, 0))
        self.assertTrue(self.move(self.ids[0], self.other, 0))
        self.assertEqual([i.macro_id for i in self.other.children], self.ids[:3])
        self.assertEqual(self.other.writing_blocks, [block])
        self.assertEqual(self.group.writing_blocks, [])
        self.assertEqual(writing_layout(self.other)[1], [])
