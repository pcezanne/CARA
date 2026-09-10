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
    QCheckBox,
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
from app.services.bulk_analysis_service import BulkAnalysisService
from app.services.chess_log_stats_service import ChessLogPresetSeries
from app.utils.font_utils import resolve_font_family, scale_font_size
from app.utils.pgn_variation_path import decode_path
from app.views.dialogs._tag_row_helpers import node_info as _node_info, ply_for_path as _ply_for_path
from app.views.style.style_manager import StyleManager
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
        controller.ai_configured_changed.connect(self._on_ai_configured_changed)

        self._refresh_ai_state()
        self._refresh_tags_report()

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
        self._tags_report_outer = self._build_tags_report_panel()
        content_layout.addWidget(self._tags_report_outer)
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

        # Checkbox: include also-flagged step in the prompt (default checked).
        self._include_flags_check = QCheckBox("Also flag shallow notes")
        self._include_flags_check.setChecked(True)
        self._include_flags_check.stateChanged.connect(self._on_include_flags_changed)
        layout.addWidget(self._include_flags_check)

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
    # Tags Report panel
    # ------------------------------------------------------------------

    def _build_tags_report_panel(self) -> QWidget:
        """Build the Tags Report panel container; call _refresh_tags_report() to populate."""
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._tags_report_inner_layout = QVBoxLayout(container)
        self._tags_report_inner_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_report_inner_layout.setSpacing(0)
        self._tags_report_row_widgets: List = []  # List[Tuple[game, path_key, preset, _TagRowWidget]]
        self._tags_report_built = False
        return container

    def _refresh_tags_report(self) -> None:
        """Rebuild the Tags Report panel contents from the current data source."""
        from io import StringIO
        import chess.pgn
        from app.views.dialogs.show_tags_dialog import _TagRowWidget

        # Clear existing content
        while self._tags_report_inner_layout.count():
            item = self._tags_report_inner_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._tags_report_row_widgets = []

        panel_cfg = self._config.get("ui", {}).get("panels", {}).get("detail", {})
        cl_cfg = panel_cfg.get("chess_log_charts", {})
        colors = cl_cfg.get("colors", {})
        bg = colors.get("background", [28, 28, 33])
        text_color = colors.get("text", [210, 210, 220])
        border = colors.get("border", [60, 60, 68])

        if not self._controller:
            return

        from app.services.chess_log_storage_service import ChessLogStorageService

        games = self._controller.resolve_games()
        custom_cats = self._controller.get_custom_categories()

        # Collect (game, paths_data, pgn_game) triples that have tags
        tagged_games = []
        for game in games:
            tags = self._controller.get_tags_for_game(game)
            if not any(tags.values()):
                continue
            try:
                pgn_game = chess.pgn.read_game(StringIO(game.pgn)) if game.pgn else None
            except Exception:
                pgn_game = None
            tagged_games.append((game, tags, pgn_game))

        if not tagged_games:
            lbl = QLabel("No tagged moments in the current selection.")
            tr, tg, tb = text_color
            lbl.setStyleSheet(f"color: rgb({tr},{tg},{tb}); padding: 8px 0;")
            self._tags_report_inner_layout.addWidget(lbl)
            return

        # Sort games by date ascending, game_number as tiebreak
        def _sort_key(triple):
            game, _, __ = triple
            date_str = str(getattr(game, "date", "") or "")
            return (date_str, getattr(game, "game_number", 0))

        tagged_games.sort(key=_sort_key)

        # Decide whether to group by database (only when >1 distinct database)
        _PRESET_ORDER = ["CLAMP", "CCT", "3x3", "Custom"]
        preset_rank = {p: i for i, p in enumerate(_PRESET_ORDER)}

        def _db_name(game):
            try:
                db = self._controller._database_controller.find_database_model_for_game(game)
                if db:
                    return db.display_name
            except Exception:
                pass
            return "Unknown"

        db_names = [_db_name(g) for g, _, __ in tagged_games]
        multi_db = len(set(db_names)) > 1

        # Build rows
        all_rows = []  # (game, path_key, preset, entries, pgn_game)
        for (game, tags, pgn_game) in tagged_games:
            for path_key, all_entries in tags.items():
                if not all_entries:
                    continue
                path = decode_path(path_key)
                if path is None:
                    continue
                ply = _ply_for_path(pgn_game, path)
                by_preset: Dict[str, list] = {}
                for entry in all_entries:
                    p = entry.get("preset", "")
                    by_preset.setdefault(p, []).append(entry)
                for preset, entries in by_preset.items():
                    rank = preset_rank.get(preset, len(_PRESET_ORDER))
                    all_rows.append((ply, rank, game, path_key, preset, entries, pgn_game))

        total_row_count = len(all_rows)

        # Container that holds separator labels + row widgets
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)

        br, bg_v, bb = bg
        tr, tg, tb = text_color
        bor, bog, bob = border

        last_db = None
        last_game = None

        # Sort all_rows: by game (same order), then within game by ply and preset rank
        # Since tagged_games is already sorted, group by game preserving that order
        from itertools import groupby
        game_row_groups = {}
        for (ply, rank, game, path_key, preset, entries, pgn_game) in all_rows:
            gid = id(game)
            if gid not in game_row_groups:
                game_row_groups[gid] = (game, pgn_game, [])
            game_row_groups[gid][2].append((ply, rank, path_key, preset, entries))

        for (game, _, __) in tagged_games:
            gid = id(game)
            if gid not in game_row_groups:
                continue
            _, pgn_game, g_rows = game_row_groups[gid]
            g_rows.sort(key=lambda r: (r[0], r[1]))  # sort by ply, then preset rank

            db_name = _db_name(game)

            # Database header
            if multi_db and db_name != last_db:
                db_header = QLabel(db_name)
                dh_bg_r = min(255, br + 38)
                dh_bg_g = min(255, bg_v + 38)
                dh_bg_b = min(255, bb + 38)
                db_header.setStyleSheet(
                    f"background-color: rgb({dh_bg_r},{dh_bg_g},{dh_bg_b}); "
                    f"color: rgb({tr},{tg},{tb}); font-weight: bold; "
                    f"padding: 4px 8px; "
                    f"border-top: 1px solid rgb({bor},{bog},{bob}); "
                    f"border-bottom: 1px solid rgb({bor},{bog},{bob});"
                )
                inner_layout.addWidget(db_header)
                inner_layout.addSpacing(12)
                last_db = db_name
                last_game = None

            # Game header
            if last_game is not game:
                if last_game is not None:
                    inner_layout.addSpacing(6)
                game_label = BulkAnalysisService.format_game_label(game)
                game_header = QLabel(game_label)
                gh_bg_r = min(255, br + 20)
                gh_bg_g = min(255, bg_v + 20)
                gh_bg_b = min(255, bb + 20)
                game_header.setStyleSheet(
                    f"background-color: rgb({gh_bg_r},{gh_bg_g},{gh_bg_b}); "
                    f"color: rgb({tr},{tg},{tb}); "
                    f"padding: 3px 8px; "
                    f"border-top: 1px solid rgb({bor},{bog},{bob}); "
                    f"border-bottom: 1px solid rgb({bor},{bog},{bob});"
                )
                inner_layout.addWidget(game_header)
                last_game = game

            for i, (ply, rank, path_key, preset, entries) in enumerate(g_rows):
                if i > 0:
                    sep = QFrame()
                    sep.setFrameShape(QFrame.Shape.HLine)
                    sep.setFixedHeight(1)
                    sep.setStyleSheet(f"background-color: rgb({bor},{bog},{bob}); border: none;")
                    inner_layout.addWidget(sep)

                fen, played_move, move_label = _node_info(pgn_game, path_key)
                row = _TagRowWidget(
                    self._config,
                    preset,
                    entries,
                    custom_cats,
                    move_label,
                    fen or None,
                    played_move,
                    bg,
                    text_color,
                )
                row.edited.connect(
                    lambda g=game, pk=path_key, pr=preset, w=row:
                        self._on_tag_row_edited(g, pk, pr, w)
                )
                inner_layout.addWidget(row)
                self._tags_report_row_widgets.append((game, path_key, preset, row))

            inner_layout.addSpacing(2)

        inner_layout.addStretch(1)

        # Wrap in a scroll area only if row count > 9
        if total_row_count > 9:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(inner)
            scroll.setMaximumHeight(700)
            StyleManager.style_scroll_area(
                scroll, self._config, bg, border, border_radius=0, include_scroll_area_border=False
            )
            self._tags_report_inner_layout.addWidget(scroll)
        else:
            self._tags_report_inner_layout.addWidget(inner)

    def _on_tag_row_edited(self, game, path_key: str, preset: str, row) -> None:
        """Persist a live Tags Report edit to the multi-game cache."""
        if self._controller:
            self._controller.tag_row_edited(game, path_key, preset, row.get_current_entries())

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
        self._refresh_tags_report()

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

    def _on_include_flags_changed(self, state: int) -> None:
        if self._controller:
            self._controller.set_narrative_include_flags(bool(state))

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

    def _refresh_ai_state(self) -> None:
        configured = bool(self._controller and self._controller.is_ai_configured())
        self._generate_btn.setEnabled(configured)
        self._ai_hint.setVisible(not configured)
        self._include_flags_check.setEnabled(configured)
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
