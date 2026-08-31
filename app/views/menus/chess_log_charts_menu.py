"""Chess Log Charts time-series settings menu controller (menubar).

Creates and syncs the 'Time series settings' submenu for Chess Log Charts.
Structure (3 groups, 6 items — mirrors PlayerStatsTimeSeriesMenuController):
  Group A: Progression bins / Binning mode
  Group B: X axis layout / Max gap segment
  Group C: Progression line style / Smoothing strength

Reads and writes settings via UserSettingsService directly, so no reference to
ChessLogChartsController is needed at menu-build time.  All 6 keys are written
together on every selection to prevent the shallow-merge loss that would occur
if only one key were written at a time.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from app.services.chess_log_charts_user import (
    CHOICES_MAX_GAP_SEGMENT_DAYS,
    CHOICES_SMOOTHING_STRENGTH,
    CHOICES_TARGET_BINS,
    normalize_chess_log_charts_settings,
)
from app.services.user_settings_service import UserSettingsService


class ChessLogChartsMenuController:
    """Creates and syncs the nested 'Time series settings' menu for Chess Log Charts."""

    def __init__(self, action_parent, style_submenu: Callable[[QMenu], None]) -> None:
        self._parent = action_parent
        self._style = style_submenu
        self.top_menu: Optional[QMenu] = None
        # Group A
        self._bins_actions: Dict[int, QAction] = {}
        self._mode_quantile: Optional[QAction] = None
        self._mode_equal: Optional[QAction] = None
        # Group B
        self._x_uniform: Optional[QAction] = None
        self._x_gap: Optional[QAction] = None
        self._x_cal: Optional[QAction] = None
        self._gap_seg_actions: Dict[int, QAction] = {}
        # Group C
        self._line_smooth: Optional[QAction] = None
        self._line_straight: Optional[QAction] = None
        self._strength_actions: Dict[float, QAction] = {}

    def attach_to_parent_menu(self, parent_menu: QMenu) -> QMenu:
        """Add 'Time series settings' under ``parent_menu``; build once."""
        self.top_menu = parent_menu.addMenu("Time series settings")
        self._style(self.top_menu)
        self._ensure_actions()
        self._populate_tree(self.top_menu)
        self.sync_from_settings()
        return self.top_menu

    def _ensure_actions(self) -> None:
        if self._bins_actions:
            return
        p = self._parent

        # Group A — Binning
        for n in CHOICES_TARGET_BINS:
            act = QAction(str(n), p)
            act.setCheckable(True)
            act.setMenuRole(QAction.MenuRole.NoRole)
            act.triggered.connect(lambda _c=False, v=n: self._on_bins_selected(v))
            self._bins_actions[int(n)] = act

        self._mode_quantile = QAction("Quantile (equal games per bin)", p)
        self._mode_quantile.setCheckable(True)
        self._mode_quantile.setMenuRole(QAction.MenuRole.NoRole)
        self._mode_quantile.triggered.connect(lambda _c=False: self._on_binning_mode_selected("quantile"))

        self._mode_equal = QAction("Equal calendar width", p)
        self._mode_equal.setCheckable(True)
        self._mode_equal.setMenuRole(QAction.MenuRole.NoRole)
        self._mode_equal.triggered.connect(lambda _c=False: self._on_binning_mode_selected("equal_width"))

        # Group B — X axis
        self._x_uniform = QAction("Uniform bins", p)
        self._x_uniform.setCheckable(True)
        self._x_uniform.setMenuRole(QAction.MenuRole.NoRole)
        self._x_uniform.triggered.connect(lambda _c=False: self._on_x_axis_selected("uniform_bins"))

        self._x_gap = QAction("Gap compressed", p)
        self._x_gap.setCheckable(True)
        self._x_gap.setMenuRole(QAction.MenuRole.NoRole)
        self._x_gap.triggered.connect(lambda _c=False: self._on_x_axis_selected("gap_compressed"))

        self._x_cal = QAction("Calendar linear", p)
        self._x_cal.setCheckable(True)
        self._x_cal.setMenuRole(QAction.MenuRole.NoRole)
        self._x_cal.triggered.connect(lambda _c=False: self._on_x_axis_selected("calendar_linear"))

        for n in CHOICES_MAX_GAP_SEGMENT_DAYS:
            act = QAction(str(n), p)
            act.setCheckable(True)
            act.setMenuRole(QAction.MenuRole.NoRole)
            act.triggered.connect(lambda _c=False, v=n: self._on_gap_segment_selected(v))
            self._gap_seg_actions[int(n)] = act

        # Group C — Line style
        self._line_smooth = QAction("Smooth", p)
        self._line_smooth.setCheckable(True)
        self._line_smooth.setMenuRole(QAction.MenuRole.NoRole)
        self._line_smooth.triggered.connect(lambda _c=False: self._on_line_style_selected("smooth"))

        self._line_straight = QAction("Straight segments", p)
        self._line_straight.setCheckable(True)
        self._line_straight.setMenuRole(QAction.MenuRole.NoRole)
        self._line_straight.triggered.connect(lambda _c=False: self._on_line_style_selected("straight"))

        for x in CHOICES_SMOOTHING_STRENGTH:
            act = QAction(str(x), p)
            act.setCheckable(True)
            act.setMenuRole(QAction.MenuRole.NoRole)
            act.triggered.connect(lambda _c=False, v=x: self._on_strength_selected(v))
            self._strength_actions[float(x)] = act

    def _populate_tree(self, ts_menu: QMenu) -> None:
        m_bins = ts_menu.addMenu("Progression bins")
        self._style(m_bins)
        for n in CHOICES_TARGET_BINS:
            m_bins.addAction(self._bins_actions[int(n)])

        m_mode = ts_menu.addMenu("Binning mode")
        self._style(m_mode)
        assert self._mode_quantile and self._mode_equal
        m_mode.addAction(self._mode_quantile)
        m_mode.addAction(self._mode_equal)

        ts_menu.addSeparator()

        m_x = ts_menu.addMenu("X axis layout")
        self._style(m_x)
        assert self._x_uniform and self._x_gap and self._x_cal
        m_x.addAction(self._x_uniform)
        m_x.addAction(self._x_gap)
        m_x.addAction(self._x_cal)

        m_gap = ts_menu.addMenu("Max gap segment (calendar days)")
        self._style(m_gap)
        for n in CHOICES_MAX_GAP_SEGMENT_DAYS:
            m_gap.addAction(self._gap_seg_actions[int(n)])

        ts_menu.addSeparator()

        m_line = ts_menu.addMenu("Progression line style")
        self._style(m_line)
        assert self._line_smooth and self._line_straight
        m_line.addAction(self._line_smooth)
        m_line.addAction(self._line_straight)

        m_str = ts_menu.addMenu("Smoothing strength")
        self._style(m_str)
        for x in CHOICES_SMOOTHING_STRENGTH:
            m_str.addAction(self._strength_actions[float(x)])

    def sync_from_settings(self) -> None:
        """Refresh all checked states from persisted user settings."""
        if not self._bins_actions:
            return
        charts = self._current_charts()

        nb = int(charts["target_bins"])
        for n, a in self._bins_actions.items():
            a.blockSignals(True)
            a.setChecked(n == nb)
            a.blockSignals(False)

        om = str(charts["binning_mode"])
        assert self._mode_quantile and self._mode_equal
        self._mode_quantile.blockSignals(True)
        self._mode_equal.blockSignals(True)
        self._mode_quantile.setChecked(om == "quantile")
        self._mode_equal.setChecked(om == "equal_width")
        self._mode_quantile.blockSignals(False)
        self._mode_equal.blockSignals(False)

        xm = str(charts["x_axis_layout"])
        assert self._x_uniform and self._x_gap and self._x_cal
        self._x_uniform.blockSignals(True)
        self._x_gap.blockSignals(True)
        self._x_cal.blockSignals(True)
        self._x_uniform.setChecked(xm == "uniform_bins")
        self._x_gap.setChecked(xm == "gap_compressed")
        self._x_cal.setChecked(xm == "calendar_linear")
        self._x_uniform.blockSignals(False)
        self._x_gap.blockSignals(False)
        self._x_cal.blockSignals(False)

        gd = int(charts["max_gap_segment_days"])
        for n, a in self._gap_seg_actions.items():
            a.blockSignals(True)
            a.setChecked(n == gd)
            a.blockSignals(False)

        st = str(charts["line_style"])
        assert self._line_smooth and self._line_straight
        self._line_smooth.blockSignals(True)
        self._line_straight.blockSignals(True)
        self._line_smooth.setChecked(st == "smooth")
        self._line_straight.setChecked(st == "straight")
        self._line_smooth.blockSignals(False)
        self._line_straight.blockSignals(False)

        ss = float(charts["smoothing_strength"])
        for x, a in self._strength_actions.items():
            a.blockSignals(True)
            a.setChecked(abs(x - ss) < 1e-9)
            a.blockSignals(False)

    # ------------------------------------------------------------------
    # Handlers — each reads all 6 current keys, updates one, writes all 6
    # ------------------------------------------------------------------

    def _on_bins_selected(self, value: int) -> None:
        for n, a in self._bins_actions.items():
            a.blockSignals(True)
            a.setChecked(n == value)
            a.blockSignals(False)
        charts = self._current_charts()
        charts["target_bins"] = value
        self._write_charts(charts)

    def _on_binning_mode_selected(self, mode: str) -> None:
        assert self._mode_quantile and self._mode_equal
        self._mode_quantile.blockSignals(True)
        self._mode_equal.blockSignals(True)
        self._mode_quantile.setChecked(mode == "quantile")
        self._mode_equal.setChecked(mode == "equal_width")
        self._mode_quantile.blockSignals(False)
        self._mode_equal.blockSignals(False)
        charts = self._current_charts()
        charts["binning_mode"] = mode
        self._write_charts(charts)

    def _on_x_axis_selected(self, mode: str) -> None:
        assert self._x_uniform and self._x_gap and self._x_cal
        self._x_uniform.blockSignals(True)
        self._x_gap.blockSignals(True)
        self._x_cal.blockSignals(True)
        self._x_uniform.setChecked(mode == "uniform_bins")
        self._x_gap.setChecked(mode == "gap_compressed")
        self._x_cal.setChecked(mode == "calendar_linear")
        self._x_uniform.blockSignals(False)
        self._x_gap.blockSignals(False)
        self._x_cal.blockSignals(False)
        charts = self._current_charts()
        charts["x_axis_layout"] = mode
        self._write_charts(charts)

    def _on_gap_segment_selected(self, value: int) -> None:
        for n, a in self._gap_seg_actions.items():
            a.blockSignals(True)
            a.setChecked(n == value)
            a.blockSignals(False)
        charts = self._current_charts()
        charts["max_gap_segment_days"] = value
        self._write_charts(charts)

    def _on_line_style_selected(self, style: str) -> None:
        assert self._line_smooth and self._line_straight
        self._line_smooth.blockSignals(True)
        self._line_straight.blockSignals(True)
        self._line_smooth.setChecked(style == "smooth")
        self._line_straight.setChecked(style == "straight")
        self._line_smooth.blockSignals(False)
        self._line_straight.blockSignals(False)
        charts = self._current_charts()
        charts["line_style"] = style
        self._write_charts(charts)

    def _on_strength_selected(self, value: float) -> None:
        for x, a in self._strength_actions.items():
            a.blockSignals(True)
            a.setChecked(abs(x - value) < 1e-9)
            a.blockSignals(False)
        charts = self._current_charts()
        charts["smoothing_strength"] = value
        self._write_charts(charts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_charts(self) -> dict:
        """Return the normalized current charts sub-dict (all 6 keys)."""
        return normalize_chess_log_charts_settings(
            UserSettingsService.get_instance().get_chess_log().get("charts", {})
        )

    def _write_charts(self, charts: dict) -> None:
        """Persist all 6 chart keys together to avoid shallow-merge loss."""
        UserSettingsService.get_instance().update_chess_log_settings({"charts": charts})
