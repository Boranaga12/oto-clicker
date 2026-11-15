from __future__ import annotations

import os
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kodlar.magnifier import far_corner, capture_patch, SelectionMagnifier
from kodlar.tests.test_edit_lock import EditLockTests as Fixture


class MagnifierGeometryTests(unittest.TestCase):
    def test_far_corner_stays_inside_negative_monitor_and_keeps_stable_corner(self):
        bounds = (-1920, -100, 0, 980)
        first = far_corner((-1850, 0), bounds, 185)
        self.assertEqual(first, (-201, 779))
        self.assertEqual(far_corner((-1800, 50), bounds, 185, first), first)
        changed = far_corner((-100, 850), bounds, 185, first)
        self.assertNotEqual(changed, first)
        self.assertTrue(-1920 <= changed[0] <= -185)
        self.assertTrue(-100 <= changed[1] <= 795)

    def test_small_monitor_corners_never_extend_outside(self):
        self.assertEqual(far_corner((0, 0), (0, 0, 100, 100), 185), (0, 0))


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Desktop required')
class InteractionPolishTests(unittest.TestCase):
    setUp = Fixture.setUp
    close = Fixture.close

    def event(self, widget, dx=0, dy=0, delta=0):
        return SimpleNamespace(widget=widget, x_root=widget.winfo_rootx()+5+dx,
                               y_root=widget.winfo_rooty()+5+dy, delta=delta)

    def test_card_wheel_reaches_list_and_text_wheel_does_not(self):
        widgets = self.app.config_widgets[id(self.config)]
        event = self.event(widgets['key_btn'], delta=-120)
        with patch.object(self.app.list_container.canvas, 'yview_scroll') as scroll:
            self.app.list_container._on_mousewheel(event)
            scroll.assert_called_once_with(1, 'units')
            scroll.reset_mock()
            self.app.list_container._on_mousewheel(self.event(self.app.log_text, delta=-120))
            scroll.assert_not_called()

    def test_fractional_wheel_movement_accumulates(self):
        card = self.app.config_widgets[id(self.config)]['card']
        with patch.object(self.app.list_container.canvas, 'yview_scroll') as scroll:
            for _ in range(4):
                self.app.list_container._on_mousewheel(self.event(card, delta=-30))
            scroll.assert_called_once_with(1, 'units')

    def test_selection_labels_and_group_border_survive_lock(self):
        widgets = self.app.config_widgets[id(self.config)]
        self.assertEqual(widgets['pixel_btn'].cget('text'), 'İzleme Seç')
        self.assertEqual(widgets['loc_btn'].cget('text'), 'Tıklama Seç')
        outer = self.app.group_widgets[self.group.id_token]['outer']
        self.assertEqual(int(outer.cget('padx')), 2)
        self.group.enabled = False
        self.app.update_group_states()
        self.assertEqual(outer.cget('bg'), '#60738b')

    def test_inactive_position_card_is_faded_but_still_editable(self):
        panel = self.app.position_panel
        self.assertTrue(panel._faded)
        self.assertEqual(panel.select.cget('state'), 'normal')
        self.assertEqual(self.app.content_split.cget('sashcursor'), 'arrow')

    def test_hotkey_assigner_is_between_topmost_and_start(self):
        self.assertEqual(self.app.panic_btn.master, self.app.status_badge.master)
        self.assertGreater(self.app.panic_btn.winfo_x(), self.app.chk_topmost.winfo_x())
        self.assertLess(self.app.panic_btn.winfo_x(), self.app.status_badge.winfo_x())

    def test_log_panel_height_is_saved_and_does_not_hide_list(self):
        height = self.app.content_split.winfo_height()
        self.app.content_split.sash_place(0, 0, height-157)
        self.root.update()
        with patch('kodlar.gui.save_config') as save:
            self.app.save_log_panel_height()
            save.assert_called_once_with(self.engine.app_config)
        self.assertGreaterEqual(self.app.list_container.winfo_height(), 180)
        self.assertGreaterEqual(self.engine.app_config.log_panel_height, 80)

    def test_drag_threshold_preview_and_cancel_do_not_change_order(self):
        widgets = self.app.config_widgets[id(self.grouped)]
        handle = widgets['handle']
        before = [item.macro_id for item in self.group.children]
        self.app.start_group_drag(self.event(handle), self.group, self.grouped.id_token)
        self.app.drag_group_key(self.event(handle, dy=2))
        self.assertFalse(self.app._group_drag_started)
        self.app.drag_group_key(self.event(handle, dy=12))
        self.assertTrue(self.app._group_drag_preview.winfo_exists())
        self.assertTrue(self.app._group_drag_placeholder.winfo_exists())
        preview = self.app._group_drag_preview
        self.app.finish_group_drag(None)
        self.assertFalse(preview.winfo_exists())
        self.assertIsNone(handle.grab_current())
        self.assertEqual([item.macro_id for item in self.group.children], before)

    @unittest.skipUnless(os.name == 'nt', 'Windows GDI required')
    def test_magnifier_center_is_real_pixel_and_cleanup_releases_window(self):
        window = tk.Toplevel(self.root)
        window.overrideredirect(True)
        window.attributes('-topmost', True)
        window.geometry('140x140+40+40')
        window.configure(bg='#123456')
        self.root.update()
        from kodlar.platform_win import flush_desktop
        flush_desktop()
        ppm, color = capture_patch(90, 90)
        self.assertEqual(color, '#123456')
        self.assertTrue(ppm.startswith(b'P6\n25 25\n255\n'))
        magnifier = SelectionMagnifier(self.root)
        try:
            self.assertEqual(magnifier.show_point(90, 90), '#123456')
            self.root.update()
            self.assertEqual(magnifier.canvas.cget('highlightbackground'), '#123456')
        finally:
            magnifier.destroy()
            window.destroy()


del Fixture
