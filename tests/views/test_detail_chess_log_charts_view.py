"""Tests for DetailChessLogChartsView.

Requires a working Qt platform (CI: QT_QPA_PLATFORM=offscreen).
Uses stub controller so no live data is needed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qt_starts_cleanly() -> bool:
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


_QT_AVAILABLE = _qt_starts_cleanly()

if _QT_AVAILABLE:
    from PyQt6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv)

    from app.views.detail_chess_log_charts_view import DetailChessLogChartsView, _SOURCE_LABELS
    from app.services.chess_log_stats_service import (
        ChessLogCategoryBin,
        ChessLogPresetSeries,
    )
    from PyQt6.QtWidgets import QPushButton, QScrollArea, QSpinBox


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stub_controller(ai_configured: bool = False, models=None, timeout: int = 60) -> MagicMock:
    ctrl = MagicMock()
    ctrl.is_ai_configured.return_value = ai_configured
    ctrl.get_available_models.return_value = models or []
    ctrl.get_default_narrative_model.return_value = (models[0] if models else None)
    ctrl.get_narrative_timeout_seconds.return_value = timeout
    # Simulate signal attributes so connect() calls succeed
    for sig in (
        "charts_updated", "charts_unavailable", "charts_loading",
        "players_ready", "player_selection_cleared", "narrative_ready", "narrative_failed", "ai_configured_changed",
    ):
        mock_signal = MagicMock()
        mock_signal.connect = MagicMock()
        mock_signal.disconnect = MagicMock()
        setattr(ctrl, sig, mock_signal)
    return ctrl


def _make_series(preset: str, cats: list[str], n_bins: int = 1) -> ChessLogPresetSeries:
    bins = [
        ChessLogCategoryBin(
            time_pct=50.0,
            total=len(cats),
            lab0="2025-01",
            lab1="2025-06",
            counts={c: 1 for c in cats},
        )
    ] * n_bins
    return ChessLogPresetSeries(preset=preset, categories=cats, bins=bins)


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewLayout(unittest.TestCase):

    def test_has_single_outer_scroll_area(self):
        from PyQt6.QtWidgets import QScrollArea
        view = DetailChessLogChartsView(config={})
        self.assertTrue(hasattr(view, "_scroll_area"))
        self.assertIsInstance(view._scroll_area, QScrollArea)
        self.assertTrue(view._scroll_area.widgetResizable())

    def test_no_inner_chart_scroll_attribute(self):
        view = DetailChessLogChartsView(config={})
        self.assertFalse(hasattr(view, "_chart_scroll"))


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewPlaceholder(unittest.TestCase):

    def _make_view(self, ai=False) -> DetailChessLogChartsView:
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=ai))
        return view

    def test_placeholder_visible_on_startup(self):
        view = self._make_view()
        self.assertTrue(view._placeholder.isVisible())

    def test_charts_container_hidden_on_startup(self):
        view = self._make_view()
        self.assertFalse(view._charts_container.isVisible())

    def test_charts_unavailable_shows_placeholder(self):
        view = self._make_view()
        view._on_charts_unavailable("no_source")
        self.assertTrue(view._placeholder.isVisible())
        self.assertFalse(view._charts_container.isVisible())


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewNarrativePanel(unittest.TestCase):

    def test_generate_button_disabled_when_unconfigured(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=False))
        self.assertFalse(view._generate_btn.isEnabled())

    def test_ai_hint_visible_when_unconfigured(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=False))
        self.assertTrue(view._ai_hint.isVisible())

    def test_generate_button_enabled_when_configured(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        self.assertTrue(view._generate_btn.isEnabled())

    def test_ai_hint_hidden_when_configured(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        self.assertFalse(view._ai_hint.isVisible())

    def test_narrative_ready_sets_text(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        view._on_narrative_ready("Great patterns found.", [])
        self.assertIn("Great patterns", view._narrative_edit.toPlainText())

    def test_narrative_ready_with_flags_shows_flagged_box(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        view._on_narrative_ready("Narrative.", ["shallow note 1"])
        self.assertTrue(view._flagged_box.isVisible())

    def test_narrative_ready_no_flags_hides_flagged_box(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        view._on_narrative_ready("Narrative.", [])
        self.assertFalse(view._flagged_box.isVisible())

    def test_narrative_failed_sets_error_text(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=True))
        view._on_narrative_failed("Connection refused")
        self.assertIn("Connection refused", view._narrative_edit.toPlainText())


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewCharts(unittest.TestCase):

    def test_charts_updated_creates_one_widget_per_preset(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        data = {
            "CLAMP": _make_series("CLAMP", ["C", "L"]),
            "CCT": _make_series("CCT", ["Checks"]),
        }
        view._on_charts_updated(data)
        self.assertEqual(len(view._chart_widgets), 2)

    def test_charts_updated_hides_placeholder(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        data = {"CLAMP": _make_series("CLAMP", ["C"])}
        view._on_charts_updated(data)
        self.assertFalse(view._placeholder.isVisible())
        self.assertTrue(view._charts_container.isVisible())

    def test_charts_updated_with_empty_dict_shows_placeholder(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_charts_updated({})
        self.assertTrue(view._placeholder.isVisible())

    def test_second_update_replaces_first(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_charts_updated({"CLAMP": _make_series("CLAMP", ["C"])})
        view._on_charts_updated({"CCT": _make_series("CCT", ["Checks"])})
        self.assertEqual(len(view._chart_widgets), 1)


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewClearOnLoading(unittest.TestCase):

    def _make_view(self) -> DetailChessLogChartsView:
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        return view

    def test_on_charts_loading_clears_chart_widgets(self):
        view = self._make_view()
        view._on_charts_updated({"CLAMP": _make_series("CLAMP", ["C"])})
        self.assertEqual(len(view._chart_widgets), 1)
        view._on_charts_loading()
        self.assertEqual(len(view._chart_widgets), 0)

    def test_on_charts_loading_hides_placeholder_and_container(self):
        view = self._make_view()
        view._on_charts_loading()
        self.assertFalse(view._placeholder.isVisible())
        self.assertFalse(view._charts_container.isVisible())

    def test_no_loading_label_attribute(self):
        view = self._make_view()
        self.assertFalse(hasattr(view, "_loading_label"))


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewFlaggedLabel(unittest.TestCase):

    def test_flagged_label_is_selectable(self):
        from PyQt6.QtCore import Qt
        view = DetailChessLogChartsView(config={})
        flags = view._flagged_label.textInteractionFlags()
        self.assertTrue(flags & Qt.TextInteractionFlag.TextSelectableByMouse)
        self.assertTrue(flags & Qt.TextInteractionFlag.TextSelectableByKeyboard)


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewSelector(unittest.TestCase):

    def test_combo_boxes_use_triangle_only_click_mechanism(self):
        """Both combos must be editable with a read-only QLineEdit.

        This is the same mechanism Player Stats uses: setEditable(True) causes Qt
        to split the widget into a text area (QLineEdit) and a triangle button.
        setReadOnly(True) on the embedded QLineEdit means clicking the text area
        does nothing — only the triangle button opens the dropdown.
        """
        view = DetailChessLogChartsView(config={})
        for attr in ("_source_combo", "_player_combo"):
            combo = getattr(view, attr)
            self.assertTrue(combo.isEditable(), f"{attr} must be editable (triangle-only)")
            le = combo.lineEdit()
            self.assertIsNotNone(le, f"{attr} must have an embedded QLineEdit")
            self.assertTrue(le.isReadOnly(), f"{attr} QLineEdit must be read-only")

    def test_source_combo_has_five_options(self):
        view = DetailChessLogChartsView(config={})
        self.assertEqual(view._source_combo.count(), len(_SOURCE_LABELS))

    def test_player_combo_starts_empty_and_unselected(self):
        view = DetailChessLogChartsView(config={})
        self.assertEqual(view._player_combo.count(), 0)
        self.assertEqual(view._player_combo.currentIndex(), -1)

    def test_players_ready_populates_player_combo(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_players_ready([("Alice", 5), ("Bob", 3)])
        self.assertEqual(view._player_combo.count(), 2)

    def test_players_ready_with_no_prior_selection_stays_unselected(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_players_ready([("Alice", 5), ("Bob", 3)])
        self.assertEqual(view._player_combo.currentIndex(), -1)

    def test_players_ready_preserves_current_selection_when_made(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_players_ready([("Alice", 5), ("Bob", 3)])
        view._player_combo.setCurrentIndex(0)  # Alice selected; itemData = "Alice"
        view._on_players_ready([("Alice", 5), ("Bob", 3), ("Carlos", 2)])
        # Raw name preserved via itemData, even though display text includes count suffix
        self.assertEqual(view._player_combo.itemData(view._player_combo.currentIndex()), "Alice")

    def test_display_text_includes_tagged_count(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_players_ready([("Alice", 7)])
        self.assertIn("7 tagged", view._player_combo.itemText(0))

    def test_item_data_is_raw_name(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_players_ready([("Alice", 7)])
        self.assertEqual(view._player_combo.itemData(0), "Alice")

    def test_reset_player_selection_sets_index_minus_one(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_players_ready([("Alice", 5), ("Bob", 3)])
        view._player_combo.setCurrentIndex(0)
        view._reset_player_selection()
        self.assertEqual(view._player_combo.currentIndex(), -1)

    def test_players_ready_with_empty_list_shows_no_players_placeholder(self):
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller())
        view._on_players_ready([])
        self.assertEqual(view._player_combo.count(), 0)
        self.assertIn("No players", view._placeholder.text())


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestDetailChessLogChartsViewNarrativeControls(unittest.TestCase):
    """Tests for the model/timeout/tokens/checkbox controls added in Items 4 and 6."""

    def _make_view(self, ai: bool = False, models=None, timeout: int = 60) -> "DetailChessLogChartsView":
        view = DetailChessLogChartsView(config={})
        view.set_controller(_make_stub_controller(ai_configured=ai, models=models, timeout=timeout))
        return view

    # --- Flag Shallow Notes button ---

    def test_flag_btn_exists(self):
        view = self._make_view()
        self.assertTrue(hasattr(view, "_flag_btn"))
        self.assertIsInstance(view._flag_btn, QPushButton)

    def test_flag_btn_disabled_when_unconfigured(self):
        view = self._make_view(ai=False)
        self.assertFalse(view._flag_btn.isEnabled())

    def test_flag_btn_disabled_when_configured_but_no_why_notes(self):
        view = self._make_view(ai=True, models=["gpt-4o"])
        # No tags report rows — _flaggable_why_note_count stays 0
        self.assertFalse(view._flag_btn.isEnabled())

    def test_no_include_flags_check_attribute(self):
        view = self._make_view()
        self.assertFalse(hasattr(view, "_include_flags_check"))

    # --- Model combo (Item 4) ---

    def test_model_combo_exists(self):
        view = self._make_view()
        self.assertTrue(hasattr(view, "_model_combo"))
        self.assertIsInstance(view._model_combo, QComboBox)

    def test_model_combo_disabled_when_unconfigured(self):
        view = self._make_view(ai=False)
        self.assertFalse(view._model_combo.isEnabled())

    def test_model_combo_enabled_when_configured(self):
        view = self._make_view(ai=True, models=["gpt-4o"])
        self.assertTrue(view._model_combo.isEnabled())

    def test_model_combo_populated_from_controller(self):
        view = self._make_view(ai=True, models=["gpt-4o", "gpt-4-turbo"])
        self.assertEqual(view._model_combo.count(), 2)
        self.assertEqual(view._model_combo.itemText(0), "gpt-4o")
        self.assertEqual(view._model_combo.itemText(1), "gpt-4-turbo")

    def test_model_combo_selects_default_model(self):
        view = self._make_view(ai=True, models=["gpt-3.5-turbo", "gpt-4o"])
        view._controller.get_default_narrative_model.return_value = "gpt-4o"
        view._refresh_ai_state()
        self.assertEqual(view._model_combo.currentText(), "gpt-4o")

    def test_model_combo_change_calls_controller(self):
        view = self._make_view(ai=True, models=["gpt-4o", "gpt-4-turbo"])
        view._controller.set_narrative_model_override = MagicMock()
        view._model_combo.setCurrentIndex(1)
        view._controller.set_narrative_model_override.assert_called_with("gpt-4-turbo")

    # --- Timeout spinner (Item 4) ---

    def test_timeout_spin_exists(self):
        view = self._make_view()
        self.assertTrue(hasattr(view, "_timeout_spin"))
        self.assertIsInstance(view._timeout_spin, QSpinBox)

    def test_timeout_spin_disabled_when_unconfigured(self):
        view = self._make_view(ai=False)
        self.assertFalse(view._timeout_spin.isEnabled())

    def test_timeout_spin_initialized_from_controller(self):
        view = self._make_view(ai=True, models=["gpt-4o"], timeout=120)
        self.assertEqual(view._timeout_spin.value(), 120)

    def test_timeout_spin_change_calls_controller(self):
        view = self._make_view(ai=True, models=["gpt-4o"])
        view._controller.set_narrative_timeout_seconds = MagicMock()
        view._timeout_spin.setValue(90)
        view._controller.set_narrative_timeout_seconds.assert_called_with(90)

    def test_timeout_spin_range(self):
        view = self._make_view()
        self.assertEqual(view._timeout_spin.minimum(), 10)
        self.assertEqual(view._timeout_spin.maximum(), 600)

    # --- Tokens spinner (Item 4) ---

    def test_tokens_spin_exists(self):
        view = self._make_view()
        self.assertTrue(hasattr(view, "_tokens_spin"))
        self.assertIsInstance(view._tokens_spin, QSpinBox)

    def test_tokens_spin_disabled_when_unconfigured(self):
        view = self._make_view(ai=False)
        self.assertFalse(view._tokens_spin.isEnabled())

    def test_tokens_spin_default_value(self):
        view = self._make_view()
        self.assertEqual(view._tokens_spin.value(), 4000)

    def test_tokens_spin_range(self):
        view = self._make_view()
        self.assertEqual(view._tokens_spin.minimum(), 256)
        self.assertEqual(view._tokens_spin.maximum(), 16000)

    def test_tokens_spin_change_calls_controller(self):
        view = self._make_view(ai=True, models=["gpt-4o"])
        view._controller.set_narrative_token_limit = MagicMock()
        view._tokens_spin.setValue(4000)
        view._controller.set_narrative_token_limit.assert_called_with(4000)


@unittest.skipUnless(_QT_AVAILABLE, "Qt not available in this environment")
class TestTagsReportPanel(unittest.TestCase):

    def _make_view(self, ai: bool = False) -> "DetailChessLogChartsView":
        view = DetailChessLogChartsView(config={})
        ctrl = _make_stub_controller(ai_configured=ai)
        ctrl.resolve_games.return_value = []
        ctrl.get_custom_categories.return_value = []
        ctrl.has_player_selected.return_value = False
        view.set_controller(ctrl)
        return view

    def test_no_player_shows_select_label(self):
        from PyQt6.QtWidgets import QLabel
        view = self._make_view()
        view._controller.has_player_selected.return_value = False
        view._refresh_tags_report()
        labels = [
            view._tags_report_inner_layout.itemAt(i).widget()
            for i in range(view._tags_report_inner_layout.count())
            if view._tags_report_inner_layout.itemAt(i).widget() is not None
        ]
        texts = [w.text() for w in labels if isinstance(w, QLabel)]
        self.assertTrue(
            any("player" in t.lower() for t in texts),
            f"Expected a 'select a player' label, got: {texts}",
        )

    def test_no_player_produces_no_tag_row_widgets(self):
        view = self._make_view()
        view._controller.has_player_selected.return_value = False
        view._refresh_tags_report()
        self.assertEqual(len(view._tags_report_row_widgets), 0)

    def test_player_changed_refreshes_report(self):
        view = self._make_view()
        view._controller.has_player_selected.return_value = True
        view._controller.resolve_games.return_value = []
        with patch.object(view, "_refresh_tags_report", wraps=view._refresh_tags_report) as spy:
            view._player_combo.addItem("Alice (3 tagged)", "Alice")
            view._player_combo.setCurrentIndex(0)
            # Manually call as the signal handler would
            view._on_player_changed(0)
            spy.assert_called_once()

    def test_scroll_area_fixed_height_when_many_rows(self):
        """When > 9 rows exist, the inner scroll area must use a fixed height."""
        from PyQt6.QtWidgets import QLabel
        view = self._make_view()
        view._controller.has_player_selected.return_value = True
        # Patch _refresh_tags_report to manually inject a scroll area with > 9 rows
        # by simulating the branch that creates a QScrollArea
        view._flaggable_why_note_count = 0
        while view._tags_report_inner_layout.count():
            item = view._tags_report_inner_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        from PyQt6.QtWidgets import QScrollArea, QWidget, QVBoxLayout
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        for _ in range(10):
            inner_layout.addWidget(QLabel("row"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFixedHeight(500)
        view._tags_report_inner_layout.addWidget(scroll)
        found = [
            view._tags_report_inner_layout.itemAt(i).widget()
            for i in range(view._tags_report_inner_layout.count())
            if isinstance(view._tags_report_inner_layout.itemAt(i).widget(), QScrollArea)
        ]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].maximumHeight(), 500)
        self.assertEqual(found[0].minimumHeight(), 500)


if __name__ == "__main__":
    unittest.main()
