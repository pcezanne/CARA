"""Unit tests for MomentDialog (active-preset design).

Requires a working Qt platform plugin (CI uses QT_QPA_PLATFORM=offscreen).
Tests are skipped automatically when Qt cannot start (e.g. macOS without display).
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qt_starts_cleanly() -> bool:
    """Return True if QApplication can be created in this environment."""
    probe = (
        "import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); "
        "from PyQt6.QtWidgets import QApplication; a = QApplication([]); print('ok')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            timeout=10,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        return result.returncode == 0 and b"ok" in result.stdout
    except Exception:
        return False


_QT_OK = _qt_starts_cleanly()
requires_qt = unittest.skipUnless(_QT_OK, "Qt platform plugin unavailable in this environment")

if _QT_OK:
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication(sys.argv[:1])


def _make(active_preset="CLAMP", custom_categories=None, move_number=5, san="Nf3", is_white=True):
    from app.views.dialogs.moment_dialog import MomentDialog
    return MomentDialog({}, active_preset, custom_categories or [], move_number, san, is_white)


@requires_qt
class TestClampPreset(unittest.TestCase):
    def test_no_selection_returns_empty(self):
        dlg = _make("CLAMP")
        self.assertEqual(dlg.get_entries(), [])

    def test_single_chip_returns_one_entry(self):
        dlg = _make("CLAMP")
        # Find the "M" button
        m_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "M")
        m_btn.setChecked(True)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["preset"], "CLAMP")
        self.assertEqual(entries[0]["cat"], "M")
        self.assertEqual(entries[0]["why"], "")

    def test_multi_select_two_chips(self):
        dlg = _make("CLAMP")
        c_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "C")
        l_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "L")
        c_btn.setChecked(True)
        l_btn.setChecked(True)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 2)
        cats = {e["cat"] for e in entries}
        self.assertEqual(cats, {"C", "L"})
        self.assertTrue(all(e["preset"] == "CLAMP" for e in entries))

    def test_all_five_chips_multi_select(self):
        dlg = _make("CLAMP")
        for _, btn in dlg._chip_buttons:
            btn.setChecked(True)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 5)

    def test_why_shared_across_all_entries(self):
        dlg = _make("CLAMP")
        c_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "C")
        l_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "L")
        c_btn.setChecked(True)
        l_btn.setChecked(True)
        dlg._why_edit.setPlainText("Rook was trapped")
        entries = dlg.get_entries()
        self.assertTrue(all(e["why"] == "Rook was trapped" for e in entries))

    def test_zero_chips_with_why_returns_uncategorized_entry(self):
        dlg = _make("CLAMP")
        dlg._why_edit.setPlainText("general observation")
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["preset"], "CLAMP")
        self.assertEqual(entries[0]["cat"], "")
        self.assertEqual(entries[0]["why"], "general observation")

    def test_zero_chips_empty_why_returns_empty(self):
        dlg = _make("CLAMP")
        self.assertEqual(dlg.get_entries(), [])


@requires_qt
class TestCctPreset(unittest.TestCase):
    def test_no_selection_returns_empty(self):
        dlg = _make("CCT")
        self.assertEqual(dlg.get_entries(), [])

    def test_single_cct_returns_one_entry(self):
        dlg = _make("CCT")
        t_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "Threats")
        t_btn.setChecked(True)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["cat"], "Threats")
        self.assertEqual(entries[0]["preset"], "CCT")

    def test_multiple_cct_returns_multiple_entries_same_why(self):
        dlg = _make("CCT")
        c_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "Checks")
        t_btn = next(btn for cat, btn in dlg._chip_buttons if cat == "Threats")
        c_btn.setChecked(True)
        t_btn.setChecked(True)
        dlg._why_edit.setPlainText("missed the threat")
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 2)
        cats = {e["cat"] for e in entries}
        self.assertEqual(cats, {"Checks", "Threats"})
        self.assertTrue(all(e["why"] == "missed the threat" for e in entries))

    def test_all_three_cct_non_exclusive(self):
        dlg = _make("CCT")
        for _, btn in dlg._chip_buttons:
            btn.setChecked(True)
        self.assertEqual(len(dlg.get_entries()), 3)

    def test_zero_chips_with_why_returns_uncategorized_entry(self):
        dlg = _make("CCT")
        dlg._why_edit.setPlainText("missed a tactic")
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["preset"], "CCT")
        self.assertEqual(entries[0]["cat"], "")
        self.assertEqual(entries[0]["why"], "missed a tactic")

    def test_zero_chips_empty_why_returns_empty(self):
        dlg = _make("CCT")
        self.assertEqual(dlg.get_entries(), [])


@requires_qt
class TestThreeByThreePreset(unittest.TestCase):
    def test_all_three_whys_filled(self):
        dlg = _make("3x3")
        answers = ["I wanted to attack", "It lost a tempo", "Engine moves centrally"]
        for (key, edit), answer in zip(dlg._threexthree_edits, answers):
            edit.setPlainText(answer)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual([e["cat"] for e in entries], ["Why1", "Why2", "Why3"])
        self.assertEqual([e["why"] for e in entries], answers)
        self.assertTrue(all(e["preset"] == "3x3" for e in entries))

    def test_partial_whys_skips_empty(self):
        dlg = _make("3x3")
        # Fill only Why1 and Why3, leave Why2 blank
        dlg._threexthree_edits[0][1].setPlainText("I wanted to attack")
        dlg._threexthree_edits[1][1].setPlainText("")
        dlg._threexthree_edits[2][1].setPlainText("Better central control")
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["cat"], "Why1")
        self.assertEqual(entries[1]["cat"], "Why3")

    def test_all_empty_returns_empty_list(self):
        dlg = _make("3x3")
        self.assertEqual(dlg.get_entries(), [])

    def test_ordering_why1_before_why2_before_why3(self):
        dlg = _make("3x3")
        for _, edit in dlg._threexthree_edits:
            edit.setPlainText("answer")
        entries = dlg.get_entries()
        self.assertEqual([e["cat"] for e in entries], ["Why1", "Why2", "Why3"])


@requires_qt
class TestCustomPreset(unittest.TestCase):
    def test_no_selection_returns_empty(self):
        dlg = _make("Custom", ["Time trouble", "Wrong plan", "Missed defense"])
        self.assertEqual(dlg.get_entries(), [])

    def test_single_checkbox_returns_one_entry(self):
        dlg = _make("Custom", ["Time trouble", "Wrong plan"])
        tt_cb = next(cb for cat, cb in dlg._custom_checkboxes if cat == "Time trouble")
        tt_cb.setChecked(True)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["cat"], "Time trouble")
        self.assertEqual(entries[0]["preset"], "Custom")

    def test_full_category_name_visible(self):
        """Checkboxes must show the full category name, not a truncated abbreviation."""
        dlg = _make("Custom", ["Time trouble", "Wrong plan"])
        for cat, cb in dlg._custom_checkboxes:
            self.assertEqual(cb.text(), cat)

    def test_multi_select_returns_multiple_entries(self):
        dlg = _make("Custom", ["Time trouble", "Wrong plan", "Missed defense"])
        for cat, cb in dlg._custom_checkboxes:
            if cat in ("Time trouble", "Wrong plan"):
                cb.setChecked(True)
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 2)
        cats = {e["cat"] for e in entries}
        self.assertEqual(cats, {"Time trouble", "Wrong plan"})

    def test_why_shared_across_entries(self):
        dlg = _make("Custom", ["A", "B"])
        for _, cb in dlg._custom_checkboxes:
            cb.setChecked(True)
        dlg._why_edit.setPlainText("shared reason")
        entries = dlg.get_entries()
        self.assertTrue(all(e["why"] == "shared reason" for e in entries))

    def test_zero_selection_with_why_returns_uncategorized_entry(self):
        dlg = _make("Custom", ["Time trouble", "Wrong plan"])
        dlg._why_edit.setPlainText("hard to categorize")
        entries = dlg.get_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["preset"], "Custom")
        self.assertEqual(entries[0]["cat"], "")
        self.assertEqual(entries[0]["why"], "hard to categorize")

    def test_zero_selection_empty_why_returns_empty(self):
        dlg = _make("Custom", ["Time trouble", "Wrong plan"])
        self.assertEqual(dlg.get_entries(), [])


@requires_qt
class TestEmptyCustomPreset(unittest.TestCase):
    """Automated coverage for the empty-Custom-picklist boundary case (plan decision 3)."""

    def _make_empty_custom(self):
        return _make("Custom", custom_categories=[])

    def test_warning_label_is_visible(self):
        dlg = self._make_empty_custom()
        self.assertIsNotNone(dlg._warning_label)
        self.assertTrue(dlg._warning_label.isVisible())

    def test_warning_label_mentions_settings(self):
        dlg = self._make_empty_custom()
        self.assertIn("Chess Log Settings", dlg._warning_label.text())

    def test_ok_button_is_disabled(self):
        dlg = self._make_empty_custom()
        self.assertFalse(dlg._ok_btn.isEnabled())

    def test_get_entries_returns_empty(self):
        dlg = self._make_empty_custom()
        self.assertEqual(dlg.get_entries(), [])

    def test_tag_moment_returns_none_on_cancel(self):
        from app.views.dialogs.moment_dialog import MomentDialog
        from unittest.mock import patch
        with patch.object(MomentDialog, "exec", return_value=0):
            result = MomentDialog.tag_moment({}, "Custom", [], 1, "e4", True, None)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
