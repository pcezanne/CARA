"""Chess Log Charts detail-panel tab (§5.1 + §5.2).

Layout (top to bottom):
  [Data Source + Player selector row]
  [QScrollArea → stacked ChessLogCategoryChartWidget, one per preset]
  [Narrative panel: Generate button, QTextEdit, "Also flagged" collapsible]

Placeholder text is shown at the chart area when no data is present.
The narrative panel is disabled (with an explanatory hint) when no LLM is configured.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.controllers.chess_log_charts_controller import ChessLogChartsController
from app.services.chess_log_stats_service import ChessLogPresetSeries
from app.utils.font_utils import resolve_font_family, scale_font_size
from app.views.widgets.chess_log_category_chart_widget import ChessLogCategoryChartWidget


_SOURCE_LABELS = [
    "None",
    "Active Database",
    "All Open Databases",
    "Selected games (Active Database)",
    "Selected games (All Open Databases)",
]


class DetailChessLogChartsView(QWidget):
    """Chess Log Charts tab view."""

    def __init__(
        self,
        config: Dict[str, Any],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._controller: Optional[ChessLogChartsController] = None
        self._chart_widgets: List[ChessLogCategoryChartWidget] = []

        self._build_ui()
        self._apply_styling()

    # ------------------------------------------------------------------
    # Controller wiring
    # ------------------------------------------------------------------

    def set_controller(self, controller: ChessLogChartsController) -> None:
        if self._controller:
            try:
                self._controller.charts_updated.disconnect(self._on_charts_updated)
                self._controller.charts_unavailable.disconnect(self._on_charts_unavailable)
                self._controller.players_ready.disconnect(self._on_players_ready)
                self._controller.narrative_ready.disconnect(self._on_narrative_ready)
                self._controller.narrative_failed.disconnect(self._on_narrative_failed)
                self._controller.ai_configured_changed.disconnect(self._on_ai_configured_changed)
            except RuntimeError:
                pass

        self._controller = controller
        if not controller:
            return

        controller.charts_updated.connect(self._on_charts_updated)
        controller.charts_unavailable.connect(self._on_charts_unavailable)
        controller.players_ready.connect(self._on_players_ready)
        controller.narrative_ready.connect(self._on_narrative_ready)
        controller.narrative_failed.connect(self._on_narrative_failed)
        controller.ai_configured_changed.connect(self._on_ai_configured_changed)

        self._refresh_ai_state()

    def refresh_ai_state(self) -> None:
        """Called externally when AI model settings change."""
        self._refresh_ai_state()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self._build_selector())

        # Chart area
        self._chart_scroll = QScrollArea()
        self._chart_scroll.setWidgetResizable(True)
        self._chart_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._charts_container = QWidget()
        self._charts_layout = QVBoxLayout(self._charts_container)
        self._charts_layout.setContentsMargins(0, 0, 0, 0)
        self._charts_layout.setSpacing(12)
        self._chart_scroll.setWidget(self._charts_container)

        self._placeholder = QLabel(
            "No Chess Log moments in the selected data.\n"
            "Tag some via right-click on a move in the Moves List."
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setVisible(True)

        chart_frame = QWidget()
        chart_frame_layout = QVBoxLayout(chart_frame)
        chart_frame_layout.setContentsMargins(0, 0, 0, 0)
        chart_frame_layout.setSpacing(0)
        chart_frame_layout.addWidget(self._placeholder)
        chart_frame_layout.addWidget(self._chart_scroll)
        self._chart_scroll.setVisible(False)

        root.addWidget(chart_frame, stretch=3)
        root.addWidget(self._build_narrative_panel(), stretch=2)

    def _build_selector(self) -> QWidget:
        frame = QFrame()
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Data Source:"))
        self._source_combo = QComboBox()
        for label in _SOURCE_LABELS:
            self._source_combo.addItem(label)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        layout.addWidget(self._source_combo)

        layout.addSpacing(16)

        layout.addWidget(QLabel("Player:"))
        self._player_combo = QComboBox()
        self._player_combo.addItem("All players")
        self._player_combo.currentIndexChanged.connect(self._on_player_changed)
        layout.addWidget(self._player_combo)

        layout.addStretch()
        return frame

    def _build_narrative_panel(self) -> QWidget:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        btn_row = QHBoxLayout()
        self._generate_btn = QPushButton("Generate Narrative Summary")
        self._generate_btn.clicked.connect(self._on_generate_clicked)
        self._generate_btn.setEnabled(False)
        btn_row.addWidget(self._generate_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._ai_hint = QLabel(
            "Configure an AI provider in Chess Log → AI Model Settings to enable narrative summaries."
        )
        self._ai_hint.setWordWrap(True)
        self._ai_hint.setVisible(True)
        layout.addWidget(self._ai_hint)

        self._narrative_edit = QTextEdit()
        self._narrative_edit.setReadOnly(True)
        self._narrative_edit.setPlaceholderText(
            "Click 'Generate Narrative Summary' to get an AI-written reflection on your Chess Log moments."
        )
        layout.addWidget(self._narrative_edit)

        self._flagged_box = QGroupBox("Also flagged")
        self._flagged_box.setCheckable(True)
        self._flagged_box.setChecked(False)
        flagged_layout = QVBoxLayout(self._flagged_box)
        self._flagged_label = QLabel()
        self._flagged_label.setWordWrap(True)
        self._flagged_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        flagged_layout.addWidget(self._flagged_label)
        self._flagged_box.setVisible(False)
        layout.addWidget(self._flagged_box)

        return frame

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    def _apply_styling(self) -> None:
        panel_cfg = self._config.get("ui", {}).get("panels", {}).get("detail", {})
        cl_cfg = panel_cfg.get("chess_log_charts", {})
        colors = cl_cfg.get("colors", {})

        bg = colors.get("background", [28, 28, 33])
        text = colors.get("text", [210, 210, 220])
        input_bg = colors.get("input_background", [38, 38, 44])
        border = colors.get("border", [60, 60, 68])
        hint_text = colors.get("hint_text", [150, 150, 160])

        bg_s = f"rgb({bg[0]},{bg[1]},{bg[2]})"
        text_s = f"rgb({text[0]},{text[1]},{text[2]})"
        input_s = f"rgb({input_bg[0]},{input_bg[1]},{input_bg[2]})"
        border_s = f"rgb({border[0]},{border[1]},{border[2]})"
        hint_s = f"rgb({hint_text[0]},{hint_text[1]},{hint_text[2]})"

        self.setStyleSheet(f"""
            QWidget {{ background-color: {bg_s}; color: {text_s}; }}
            QFrame {{ border: 1px solid {border_s}; border-radius: 4px; }}
            QScrollArea {{ border: none; }}
            QComboBox {{
                background-color: {input_s}; color: {text_s};
                border: 1px solid {border_s}; border-radius: 3px; padding: 2px 6px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QLabel {{ border: none; color: {text_s}; }}
            QPushButton {{
                background-color: {input_s}; color: {text_s};
                border: 1px solid {border_s}; border-radius: 4px; padding: 4px 12px;
            }}
            QPushButton:disabled {{ color: {hint_s}; }}
            QTextEdit {{
                background-color: {input_s}; color: {text_s};
                border: 1px solid {border_s}; border-radius: 4px;
            }}
            QGroupBox {{ border: 1px solid {border_s}; border-radius: 4px; margin-top: 8px; }}
            QGroupBox::title {{ color: {text_s}; subcontrol-origin: margin; left: 8px; }}
        """)
        self._ai_hint.setStyleSheet(f"color: {hint_s}; border: none;")
        self._placeholder.setStyleSheet(f"color: {hint_s}; border: none;")

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_source_changed(self, index: int) -> None:
        if self._controller:
            self._controller.set_source_selection(index)

    def _on_player_changed(self, index: int) -> None:
        if not self._controller:
            return
        player = "" if index == 0 else self._player_combo.currentText()
        self._controller.set_player_selection(player)

    def _on_generate_clicked(self) -> None:
        if self._controller:
            self._generate_btn.setEnabled(False)
            self._narrative_edit.setPlainText("Generating…")
            self._controller.request_narrative()

    def _on_charts_updated(self, data: Dict[str, ChessLogPresetSeries]) -> None:
        self._clear_charts()
        if not data:
            self._show_placeholder()
            return
        self._placeholder.setVisible(False)
        self._chart_scroll.setVisible(True)
        for preset in sorted(data):
            widget = ChessLogCategoryChartWidget(config=self._config)
            widget.set_series(data[preset], colors=self._cat_colors_for_preset(preset))
            self._charts_layout.addWidget(widget)
            self._chart_widgets.append(widget)

    def _on_charts_unavailable(self, reason: str) -> None:
        self._clear_charts()
        self._show_placeholder()

    def _on_players_ready(self, players: List[str]) -> None:
        current = self._player_combo.currentText()
        self._player_combo.blockSignals(True)
        self._player_combo.clear()
        self._player_combo.addItem("All players")
        for p in players:
            self._player_combo.addItem(p)
        idx = self._player_combo.findText(current)
        self._player_combo.setCurrentIndex(max(0, idx))
        self._player_combo.blockSignals(False)

    def _on_narrative_ready(self, narrative: str, flags: List[str]) -> None:
        self._narrative_edit.setPlainText(narrative)
        if flags:
            self._flagged_label.setText("\n".join(f"• {f}" for f in flags))
            self._flagged_box.setVisible(True)
        else:
            self._flagged_box.setVisible(False)
        self._refresh_ai_state()

    def _on_narrative_failed(self, message: str) -> None:
        self._narrative_edit.setPlainText(f"Error: {message}")
        self._refresh_ai_state()

    def _on_ai_configured_changed(self, configured: bool) -> None:
        self._refresh_ai_state()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cat_colors_for_preset(self, preset: str) -> Dict[str, "QColor"]:
        from PyQt6.QtGui import QColor
        panel_cfg = self._config.get("ui", {}).get("panels", {}).get("detail", {})
        cat_colors_cfg = panel_cfg.get("chess_log_charts", {}).get("category_colors", {})
        preset_map = cat_colors_cfg.get(preset, {})
        result: Dict[str, "QColor"] = {}
        for cat, rgb in preset_map.items():
            if isinstance(rgb, list) and len(rgb) >= 3:
                result[cat] = QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))
        return result

    def _clear_charts(self) -> None:
        for w in self._chart_widgets:
            self._charts_layout.removeWidget(w)
            w.deleteLater()
        self._chart_widgets.clear()

    def _show_placeholder(self) -> None:
        self._placeholder.setVisible(True)
        self._chart_scroll.setVisible(False)

    def _refresh_ai_state(self) -> None:
        configured = self._controller and self._controller.is_ai_configured()
        self._generate_btn.setEnabled(bool(configured))
        self._ai_hint.setVisible(not configured)
