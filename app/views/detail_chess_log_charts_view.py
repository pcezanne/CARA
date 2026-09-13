"""Chess Log Charts detail-panel tab (§5.1 + §5.2).

Layout: single QScrollArea wrapping the entire pane, mirroring Player Stats.
Inside (top to bottom):
  [Data Source + Player selector rows]
  [Placeholder label OR stacked ChessLogCategoryChartWidget instances (one per preset)]
  [Narrative panel: Generate button, QTextEdit, "Also flagged" collapsible]

Placeholder text is shown at the chart area when no data is present.
The narrative panel is disabled (with an explanatory hint) when no LLM is configured.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.controllers.chess_log_charts_controller import ChessLogChartsController
from app.services.chess_log_stats_service import ChessLogPresetSeries
from app.utils.font_utils import resolve_font_family, scale_font_size
from app.views.style.style_manager import StyleManager
from app.views.widgets.busy_spinner import BusySpinner
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
                self._controller.charts_loading.disconnect(self._on_charts_loading)
                self._controller.players_ready.disconnect(self._on_players_ready)
                self._controller.player_selection_cleared.disconnect(self._reset_player_selection)
                self._controller.narrative_ready.disconnect(self._on_narrative_ready)
                self._controller.narrative_failed.disconnect(self._on_narrative_failed)
                self._controller.shallow_ready.disconnect(self._on_shallow_ready)
                self._controller.shallow_failed.disconnect(self._on_shallow_failed)
                self._controller.ai_configured_changed.disconnect(self._on_ai_configured_changed)
            except RuntimeError:
                pass

        self._controller = controller
        if not controller:
            return

        controller.charts_updated.connect(self._on_charts_updated)
        controller.charts_unavailable.connect(self._on_charts_unavailable)
        controller.charts_loading.connect(self._on_charts_loading)
        controller.players_ready.connect(self._on_players_ready)
        controller.player_selection_cleared.connect(self._reset_player_selection)
        controller.narrative_ready.connect(self._on_narrative_ready)
        controller.narrative_failed.connect(self._on_narrative_failed)
        controller.shallow_ready.connect(self._on_shallow_ready)
        controller.shallow_failed.connect(self._on_shallow_failed)
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
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        content_widget = QWidget()
        content_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        content_widget.setMinimumWidth(0)

        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(8)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        content_layout.addWidget(self._build_selector())

        # Placeholder + stacked charts in one container (no inner scroll area)
        self._placeholder = QLabel("Select a player to view Chess Log data.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setVisible(True)

        self._charts_container = QWidget()
        self._charts_layout = QVBoxLayout(self._charts_container)
        self._charts_layout.setContentsMargins(0, 0, 0, 0)
        self._charts_layout.setSpacing(12)
        self._charts_container.setVisible(False)

        content_layout.addWidget(self._placeholder)
        content_layout.addWidget(self._charts_container)
        content_layout.addWidget(self._build_narrative_panel())
        content_layout.addStretch()

        self._scroll_area.setWidget(content_widget)
        root.addWidget(self._scroll_area)

    def _build_selector(self) -> QWidget:
        from PyQt6.QtGui import QFont
        selector_font = QFont(
            resolve_font_family("Helvetica Neue"),
            int(scale_font_size(11)),
        )

        frame = QFrame()
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        label_names = ("Data Source:", "Player:")
        fm = QFontMetrics(selector_font)
        label_width = max(fm.horizontalAdvance(s) for s in label_names) + 8

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_label = QLabel("Data Source:")
        source_label.setFont(selector_font)
        source_label.setMinimumWidth(label_width)
        source_row.addWidget(source_label)
        self._source_combo = QComboBox()
        self._source_combo.setFont(selector_font)
        self._source_combo.setEditable(True)
        self._source_combo.lineEdit().setReadOnly(True)
        for label in _SOURCE_LABELS:
            self._source_combo.addItem(label)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        source_row.addWidget(self._source_combo, 1)
        source_row.addStretch()
        outer.addLayout(source_row)

        player_row = QHBoxLayout()
        player_row.setSpacing(8)
        player_label = QLabel("Player:")
        player_label.setFont(selector_font)
        player_label.setMinimumWidth(label_width)
        player_row.addWidget(player_label)
        self._player_combo = QComboBox()
        self._player_combo.setFont(selector_font)
        self._player_combo.setEditable(True)
        self._player_combo.lineEdit().setReadOnly(True)
        self._player_combo.setPlaceholderText("Select player")
        self._player_combo.setCurrentIndex(-1)
        self._player_combo.currentIndexChanged.connect(self._on_player_changed)
        player_row.addWidget(self._player_combo, 1)
        outer.addLayout(player_row)

        return frame

    def _build_narrative_panel(self) -> QWidget:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._ai_hint = QLabel(
            "Configure an AI provider in Chess Log → AI Model Settings to enable narrative summaries."
        )
        self._ai_hint.setWordWrap(True)
        self._ai_hint.setVisible(True)
        layout.addWidget(self._ai_hint)

        # Model / timeout / tokens row (mirrors AI Summary's input row, no reactive layout).
        model_row = QHBoxLayout()
        model_row.setSpacing(8)

        model_label = QLabel("Model:")
        model_row.addWidget(model_label)
        self._model_combo = QComboBox()
        self._model_combo.setEditable(False)
        self._model_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._model_combo.currentTextChanged.connect(self._on_narrative_model_changed)
        model_row.addWidget(self._model_combo, 1)

        timeout_label = QLabel("Timeout (s):")
        model_row.addWidget(timeout_label)
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._timeout_spin.setRange(10, 600)
        self._timeout_spin.setValue(60)
        self._timeout_spin.setFixedWidth(56)
        self._timeout_spin.valueChanged.connect(self._on_narrative_timeout_changed)
        model_row.addWidget(self._timeout_spin)

        tokens_label = QLabel("Tokens:")
        model_row.addWidget(tokens_label)
        self._tokens_spin = QSpinBox()
        self._tokens_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self._tokens_spin.setRange(256, 16000)
        self._tokens_spin.setSingleStep(100)
        self._tokens_spin.setValue(4000)
        self._tokens_spin.setFixedWidth(70)
        self._tokens_spin.valueChanged.connect(self._on_narrative_tokens_changed)
        model_row.addWidget(self._tokens_spin)

        layout.addLayout(model_row)

        shallow_row = QHBoxLayout()
        self._show_shallow_btn = QPushButton("Show Shallow Tags")
        self._show_shallow_btn.clicked.connect(self._on_show_shallow_clicked)
        self._show_shallow_btn.setEnabled(False)
        shallow_row.addWidget(self._show_shallow_btn)
        self._shallow_spinner = BusySpinner(color=QColor(180, 180, 200), size=18, line_width=2)
        shallow_row.addWidget(self._shallow_spinner)
        self._shallow_status_label = QLabel("Generating Shallow Tags…")
        self._shallow_status_label.setVisible(False)
        shallow_row.addWidget(self._shallow_status_label)
        shallow_row.addStretch()
        layout.addLayout(shallow_row)

        btn_row = QHBoxLayout()
        self._generate_btn = QPushButton("Generate Narrative Summary")
        self._generate_btn.clicked.connect(self._on_generate_clicked)
        self._generate_btn.setEnabled(False)
        btn_row.addWidget(self._generate_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._narrative_edit = QTextEdit()
        self._narrative_edit.setReadOnly(True)
        self._narrative_edit.setPlaceholderText(
            "Click 'Generate Narrative Summary' to get an AI-written reflection on your Chess Log moments."
        )
        self._narrative_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._narrative_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._narrative_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._narrative_edit.document().contentsChanged.connect(self._fit_narrative_height)
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
            QComboBox QLineEdit {{
                background-color: {input_s}; color: {text_s};
                border: none; padding: 0px 2px;
            }}
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
        self._reset_player_selection()
        if self._controller:
            self._controller.set_source_selection(index)

    def _on_player_changed(self, index: int) -> None:
        if not self._controller or index < 0:
            return
        raw_name = self._player_combo.itemData(index)
        if raw_name:
            self._controller.set_player_selection(raw_name)

    def _on_generate_clicked(self) -> None:
        if self._controller:
            self._generate_btn.setEnabled(False)
            self._narrative_edit.setPlainText("Generating…")
            self._controller.request_narrative()

    def _on_charts_loading(self) -> None:
        self._clear_charts()
        self._placeholder.setVisible(False)
        self._charts_container.setVisible(False)

    def _on_charts_updated(self, data: Dict[str, ChessLogPresetSeries]) -> None:
        self._clear_charts()
        if not data:
            self._show_placeholder()
            return
        self._placeholder.setVisible(False)
        self._charts_container.setVisible(True)
        for preset in sorted(data):
            widget = ChessLogCategoryChartWidget(config=self._config)
            widget.set_series(data[preset], colors=self._cat_colors_for_preset(preset))
            self._charts_layout.addWidget(widget)
            self._chart_widgets.append(widget)

    def _on_charts_unavailable(self, reason: str) -> None:
        self._clear_charts()
        if reason == "no_player":
            self._set_placeholder_text("Select a player to view Chess Log data.")
        elif reason == "no_source":
            self._set_placeholder_text("Select a Data Source to view Chess Log data.")
        else:
            self._set_placeholder_text(
                "No Chess Log moments in the selected data.\n"
                "Tag some via right-click on a move in the Moves List."
            )
        self._show_placeholder()

    def _on_players_ready(self, players: List) -> None:
        current_raw = self._player_combo.itemData(self._player_combo.currentIndex())
        had_selection = self._player_combo.currentIndex() >= 0
        self._player_combo.blockSignals(True)
        self._player_combo.clear()
        for name, count in players:
            self._player_combo.addItem(f"{name} ({count} tagged)", name)
        if had_selection and players:
            idx = self._player_combo.findData(current_raw)
            self._player_combo.setCurrentIndex(idx)  # -1 if not found → stay unselected
        else:
            self._player_combo.setCurrentIndex(-1)
        self._player_combo.blockSignals(False)
        if not players:
            self._set_placeholder_text("No players found in this data.")

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

    def _on_narrative_model_changed(self, text: str) -> None:
        if self._controller:
            self._controller.set_narrative_model_override(text or None)

    def _on_narrative_timeout_changed(self, value: int) -> None:
        if self._controller:
            self._controller.set_narrative_timeout_seconds(value)

    def _on_narrative_tokens_changed(self, value: int) -> None:
        if self._controller:
            self._controller.set_narrative_token_limit(value)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fit_narrative_height(self) -> None:
        """Resize _narrative_edit to its document height so the outer scroll area handles overflow."""
        doc = self._narrative_edit.document()
        width = self._narrative_edit.viewport().width()
        if width > 0:
            doc.setTextWidth(width)
        h = int(doc.size().height())
        margins = self._narrative_edit.contentsMargins()
        total = h + margins.top() + margins.bottom() + 4
        self._narrative_edit.setMinimumHeight(max(total, 60))

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

    def _reset_player_selection(self) -> None:
        self._player_combo.blockSignals(True)
        self._player_combo.setCurrentIndex(-1)
        self._player_combo.blockSignals(False)
        self._set_placeholder_text("Select a player to view Chess Log data.")

    def _set_placeholder_text(self, text: str) -> None:
        self._placeholder.setText(text)

    def _show_placeholder(self) -> None:
        self._placeholder.setVisible(True)
        self._charts_container.setVisible(False)

    def _on_show_shallow_clicked(self) -> None:
        if not self._controller:
            return
        self._show_shallow_btn.setEnabled(False)
        self._shallow_spinner.start()
        self._shallow_status_label.setVisible(True)
        self._controller.request_flag_shallow_notes()

    def _on_shallow_ready(self, shallow_keys) -> None:
        self._shallow_spinner.stop()
        self._shallow_status_label.setVisible(False)
        self._refresh_ai_state()
        if not self._controller:
            return
        if not shallow_keys:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No Shallow Notes", "No shallow notes found — great job.")
            return
        games = self._controller.resolve_games()
        chess_log_ctrl = self._controller.get_chess_log_controller()
        if not chess_log_ctrl:
            return
        from app.views.dialogs.show_shallow_tags_dialog import ShowShallowTagsDialog
        dlg = ShowShallowTagsDialog(
            config=self._config,
            games=games,
            controller=chess_log_ctrl,
            shallow_keys=shallow_keys,
            parent=self,
        )
        dlg.exec()

    def _on_shallow_failed(self, message: str) -> None:
        self._shallow_spinner.stop()
        self._shallow_status_label.setVisible(False)
        self._refresh_ai_state()
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Shallow Tags Error", f"Could not classify notes:\n{message}")

    def _refresh_ai_state(self) -> None:
        configured = bool(self._controller and self._controller.is_ai_configured())
        self._generate_btn.setEnabled(configured)
        self._show_shallow_btn.setEnabled(configured)
        self._ai_hint.setVisible(not configured)
        self._model_combo.setEnabled(configured)
        self._timeout_spin.setEnabled(configured)
        self._tokens_spin.setEnabled(configured)

        if configured and self._controller:
            models = self._controller.get_available_models()
            default_model = self._controller.get_default_narrative_model() or ""
            timeout = self._controller.get_narrative_timeout_seconds()

            # Repopulate combo without firing model-changed signal.
            self._model_combo.blockSignals(True)
            self._model_combo.clear()
            for m in models:
                self._model_combo.addItem(m)
            if default_model:
                idx = self._model_combo.findText(default_model)
                self._model_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._model_combo.blockSignals(False)

            # Sync timeout from shared setting without triggering valueChanged persist.
            self._timeout_spin.blockSignals(True)
            self._timeout_spin.setValue(timeout)
            self._timeout_spin.blockSignals(False)
