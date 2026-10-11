"""Dialog that shows rows flagged as shallow or vague-lesson from the current corpus.

Save/Cancel model: edits are buffered in the row widgets until the user clicks
Save.  Save writes ``is_shallow=True`` / ``is_vague=True`` on every shown row
(per key membership), clears stale flags on entries classified-clean this run
(scoped to ``classified_keys`` only — entries the classifier didn't touch this
run are never modified), then calls ``controller.save_games(affected_games)``
to write game.pgn and mark each affected database unsaved.  Cancel and the
window close button discard all edits.

The Ignore checkbox (via ``_TagRowWidget(show_ignore_checkbox=True)``) lets
the user dismiss rows from future runs.  The row stays visible for the rest of
this session; it disappears on the next open.
"""

from __future__ import annotations

from io import StringIO
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

import chess.pgn

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.utils.chess_log_best_move import resolve_best_move_for_path
from app.utils.pgn_variation_path import decode_path
from app.views.dialogs._tag_row_helpers import node_info as _node_info_fn, ply_for_path as _ply_for_path_fn
from app.views.dialogs.show_tags_dialog import _TagRowWidget, _PRESET_ORDER, _normalize_entries
from app.views.style.style_manager import StyleManager


class ShowShallowTagsDialog(QDialog):
    """Save/Cancel dialog listing rows flagged as shallow or vague-lesson.

    Args:
        config: application config dict.
        games: list of GameData objects in scope.
        controller: ChessLogController instance (not ChessLogChartsController).
        shallow_keys: set of (game_number, path_key, preset) tuples classified SHALLOW
            this run.
        vague_keys: set of (game_number, path_key, preset) tuples with a vague lesson
            this run (3x3 only).
        classified_keys: frozenset of (game_number, path_key, preset) tuples that were
            sent to the classifier AND received a parsed verdict this run.
            ``shallow_keys ∪ vague_keys ⊆ classified_keys``.  Only entries in this set
            may be modified by Save; entries outside it are never touched.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        games: List,
        controller,
        shallow_keys: Set[Tuple[int, str, str]],
        vague_keys: Set[Tuple[int, str, str]] = frozenset(),
        classified_keys: FrozenSet[Tuple[int, str, str]] = frozenset(),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._controller = controller
        self._shallow_keys = frozenset(shallow_keys)
        self._vague_keys = frozenset(vague_keys)
        self._classified_keys = classified_keys
        self._flagged_keys = self._shallow_keys | self._vague_keys
        self._games_in_scope = list(games)

        self._load_config()

        # Build rows filtered to shallow_keys ∪ vague_keys.
        # Parallel lists: _rows (path_key, preset, entries), _row_games, _row_pgn_games.
        self._rows: List[Tuple[str, str, List[Dict[str, Any]]]] = []
        self._row_games: List = []
        self._row_pgn_games: List = []

        preset_rank = {p: i for i, p in enumerate(_PRESET_ORDER)}

        for game in games:
            pgn_game = self._parse_pgn(game)
            tags = controller.get_tags_for_game(game)

            game_rows: List[Tuple[int, int, str, str, List[Dict[str, Any]]]] = []
            for path_key, all_entries in tags.items():
                if not all_entries:
                    continue
                path = decode_path(path_key)
                if path is None:
                    continue

                by_preset: Dict[str, List[Dict[str, Any]]] = {}
                for entry in all_entries:
                    p = entry.get("preset", "")
                    by_preset.setdefault(p, []).append(entry)

                for preset, entries in by_preset.items():
                    key = (game.game_number, path_key, preset)
                    if key not in self._flagged_keys:
                        continue
                    ply = _ply_for_path_fn(pgn_game, path)
                    rank = preset_rank.get(preset, len(_PRESET_ORDER))
                    game_rows.append((ply, rank, path_key, preset, entries))

            game_rows.sort(key=lambda r: (r[0], r[1]))
            for _, _, path_key, preset, entries in game_rows:
                self._rows.append((path_key, preset, entries))
                self._row_games.append(game)
                self._row_pgn_games.append(pgn_game)

        # Snapshot of the original entries for shown rows, keyed by
        # (game.game_number, path_key, preset).  Used in _on_save to skip
        # rows that haven't changed.
        self._original_snapshot: Dict[Tuple[int, str, str], List[Dict[str, Any]]] = {
            (self._row_games[i].game_number, pk, pr): list(entries)
            for i, (pk, pr, entries) in enumerate(self._rows)
        }

        self._row_widgets: List[_TagRowWidget] = []
        self._rows_layout = None
        self._setup_ui()
        self.setWindowTitle("Check Logs")

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        dc = self._config.get("ui", {}).get("dialogs", {}).get("moment", {})
        self._bg_rgb = dc.get("background_color", [40, 40, 45])
        self._border_rgb = dc.get("border_color", [60, 60, 65])
        self._text_color_rgb = dc.get("text_color", [200, 200, 200])
        self._separator_rgb = dc.get("separator_color", [70, 70, 75])
        self._button_width = dc.get("button_width", 100)
        self._button_height = dc.get("button_height", 28)
        sh = self._config.get("ui", {}).get("dialogs", {}).get("shallow", {})
        self._btn_save_label = sh.get("button_save", "Save")
        self._btn_cancel_label = sh.get("button_cancel", "Cancel")

    @staticmethod
    def _parse_pgn(game_data):
        try:
            pgn = getattr(game_data, "pgn", None)
            if not pgn:
                return None
            return chess.pgn.read_game(StringIO(pgn))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedHeight(1)
        sr, sg, sb = self._separator_rgb
        sep.setStyleSheet(f"background-color: rgb({sr},{sg},{sb}); border: none;")
        return sep

    def _make_game_header(self, game) -> QLabel:
        _white = str(getattr(game, "white", "") or "").strip() or "Unknown"
        _black = str(getattr(game, "black", "") or "").strip() or "Unknown"
        _result = str(getattr(game, "result", "") or "").strip() or "*"
        _date = str(getattr(game, "date", "") or "").strip() or "????.??.??"
        try:
            _moves = int(getattr(game, "moves", 0) or 0)
        except (TypeError, ValueError):
            _moves = 0
        text = f"{_white} - {_black} {_result} ({_date} - {_moves} moves)"
        label = QLabel(text)
        br, bg, bb = self._bg_rgb
        tr, tg, tb = self._text_color_rgb
        bor, bog, bob = self._border_rgb
        label.setStyleSheet(
            f"background-color: rgb({min(255, br+20)},{min(255, bg+20)},{min(255, bb+20)}); "
            f"color: rgb({tr},{tg},{tb}); "
            f"padding: 3px 8px; "
            f"border: 1px solid rgb({bor},{bog},{bob});"
        )
        return label

    def _setup_ui(self) -> None:
        br, bg, bb = self._bg_rgb
        self.setStyleSheet(f"QDialog {{ background-color: rgb({br},{bg},{bb}); }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        if not self._rows:
            tr, tg, tb = self._text_color_rgb
            lbl = QLabel("No flagged notes found.")
            lbl.setStyleSheet(f"color: rgb({tr},{tg},{tb});")
            root.addWidget(lbl)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFrameShape(QFrame.Shape.NoFrame)

            content = QWidget()
            self._rows_layout = QVBoxLayout(content)
            self._rows_layout.setSpacing(0)
            self._rows_layout.setContentsMargins(0, 0, 0, 0)
            self._rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            rows_layout = self._rows_layout

            multi_game = len(set(id(g) for g in self._row_games)) > 1
            last_game = None
            row_count = 0
            orphan_count = 0

            for i, (path_key, preset, entries) in enumerate(self._rows):
                game = self._row_games[i]
                pgn_game = self._row_pgn_games[i]

                fen, played_move, move_label, mover_is_black = _node_info_fn(pgn_game, path_key)
                if move_label == path_key:
                    orphan_count += 1
                    continue

                if multi_game and game is not last_game:
                    rows_layout.addWidget(self._make_game_header(game))
                    last_game = game
                elif row_count > 0:
                    rows_layout.addWidget(self._make_separator())

                best_move = resolve_best_move_for_path(game, path_key, played_move, pgn_game)
                key = (game.game_number, path_key, preset)
                stamped = list(entries)
                if key in self._shallow_keys:
                    stamped = [dict(e, is_shallow=True) for e in stamped]
                if key in self._vague_keys:
                    stamped = [dict(e, is_vague=True) for e in stamped]
                row_widget = _TagRowWidget(
                    self._config,
                    preset,
                    stamped,
                    move_label,
                    fen or None,
                    played_move,
                    self._bg_rgb,
                    self._text_color_rgb,
                    show_ignore_checkbox=True,
                    best_move=best_move,
                    is_flipped=mover_is_black,
                )
                rows_layout.addWidget(row_widget)
                self._row_widgets.append(row_widget)
                row_count += 1

            if orphan_count > 0:
                s = "s" if orphan_count != 1 else ""
                notice = QLabel(
                    f"Note: {orphan_count} tagged moment{s} could not be located "
                    f"— the game's moves may have been edited after tagging."
                )
                tr, tg, tb = self._text_color_rgb
                notice.setStyleSheet(
                    f"color: rgb({tr},{tg},{tb}); padding: 4px 0px;"
                )
                notice.setWordWrap(True)
                rows_layout.addWidget(notice)

            rows_layout.addStretch(1)
            scroll.setWidget(content)

            StyleManager.style_scroll_area(
                scroll,
                self._config,
                self._bg_rgb,
                self._border_rgb,
                border_radius=0,
                include_scroll_area_border=False,
            )

            screen = self.screen()
            max_h = int(screen.availableGeometry().height() * 0.85) if screen else 800
            scroll.setMinimumHeight(min(400, max_h))
            scroll.setMaximumHeight(max_h)
            root.addWidget(scroll)

        btn_row = QHBoxLayout()

        has_rows = bool(self._rows)
        self._export_pdf_btn = QPushButton("Export to PDF")
        self._export_pdf_btn.setAutoDefault(False)
        self._export_pdf_btn.setFixedHeight(self._button_height)
        self._export_pdf_btn.setEnabled(has_rows)
        self._export_pdf_btn.clicked.connect(self._on_export_pdf)
        btn_row.addWidget(self._export_pdf_btn)

        btn_row.addStretch(1)
        self._cancel_btn = QPushButton(self._btn_cancel_label)
        self._cancel_btn.setAutoDefault(False)
        self._cancel_btn.setFixedSize(self._button_width, self._button_height)
        self._cancel_btn.clicked.connect(self.reject)

        self._save_btn = QPushButton(self._btn_save_label)
        self._save_btn.setDefault(True)
        self._save_btn.setAutoDefault(True)
        self._save_btn.setFixedSize(self._button_width, self._button_height)
        self._save_btn.clicked.connect(self._on_save)

        btn_row.addWidget(self._cancel_btn)
        btn_row.addSpacing(6)
        btn_row.addWidget(self._save_btn)
        root.addLayout(btn_row)

        StyleManager.style_buttons(
            [self._export_pdf_btn, self._cancel_btn, self._save_btn],
            self._config,
            self._bg_rgb,
            self._border_rgb,
        )

        self.setMinimumWidth(800)
        from app.views.widgets.themed_dialog_size_grip import install_themed_dialog_resize_grip
        install_themed_dialog_resize_grip(self, self._config)

    def _on_export_pdf(self) -> None:
        from pathlib import Path
        from PyQt6.QtWidgets import QFileDialog
        from app.services.chess_log_pdf_service import (
            ChessLogPDFService,
            default_chess_log_tags_pdf_filename,
        )
        suggested = default_chess_log_tags_pdf_filename(is_shallow_only=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to PDF", suggested, "PDF Files (*.pdf)"
        )
        if not path:
            return

        multi_game = len(set(id(g) for g in self._row_games)) > 1
        tag_groups = []
        current_game = None
        current_rows = []
        current_header = None

        for i, row_widget in enumerate(self._row_widgets):
            game = self._row_games[i]
            if game is not current_game:
                if current_rows:
                    tag_groups.append({"header": current_header, "rows": current_rows})
                current_game = game
                current_rows = []
                if multi_game:
                    white = str(getattr(game, "white", "") or "").strip() or "Unknown"
                    black = str(getattr(game, "black", "") or "").strip() or "Unknown"
                    result = str(getattr(game, "result", "") or "").strip() or "*"
                    date = str(getattr(game, "date", "") or "").strip() or "????.??.??"
                    moves = getattr(game, "moves", 0) or 0
                    current_header = f"{white} - {black} {result} ({date} - {moves} moves)"
                else:
                    current_header = None
            current_rows.append(row_widget.snapshot())

        if current_rows:
            tag_groups.append({"header": current_header, "rows": current_rows})

        ChessLogPDFService(self._config).export_tags(
            Path(path), tag_groups, is_shallow_only=True
        )

    def _on_save(self) -> None:
        affected: set = set()

        # a) Shown rows: stamp is_shallow / is_vague per key membership.
        for i, (path_key, preset, _) in enumerate(self._rows):
            row_widget = self._row_widgets[i]
            game = self._row_games[i]
            key = (game.game_number, path_key, preset)
            user_entries = row_widget.get_current_entries()
            new_entries = list(user_entries)
            if key in self._shallow_keys:
                new_entries = [dict(e, is_shallow=True) for e in new_entries]
            if key in self._vague_keys:
                new_entries = [dict(e, is_vague=True) for e in new_entries]
            original = self._original_snapshot.get(key, [])
            orig_with_flags = list(original)
            if key in self._shallow_keys:
                orig_with_flags = [dict(e, is_shallow=True) for e in orig_with_flags]
            if key in self._vague_keys:
                orig_with_flags = [dict(e, is_vague=True) for e in orig_with_flags]
            flags_missing = (
                (key in self._shallow_keys and any(not e.get("is_shallow") for e in original))
                or (key in self._vague_keys and any(not e.get("is_vague") for e in original))
            )
            if _normalize_entries(new_entries) != _normalize_entries(orig_with_flags) or flags_missing:
                self._controller.replace_entries_at_path_for_game(
                    game, path_key, preset, new_entries
                )
                affected.add(game)

        # b) Classified-but-not-shown entries (parsed DEEP/non-vague this run):
        #    clear stale is_shallow / is_vague.  Scoped to _classified_keys ONLY —
        #    never touches unparsed, ignored, or empty-why entries.
        for game in self._games_in_scope:
            tags = self._controller.get_tags_for_game(game)
            for path_key, entries in tags.items():
                by_preset: Dict[str, List[Dict[str, Any]]] = {}
                for e in entries:
                    by_preset.setdefault(e.get("preset", ""), []).append(e)
                for preset, preset_entries in by_preset.items():
                    key = (game.game_number, path_key, preset)
                    if key not in self._classified_keys:
                        continue
                    if key in self._flagged_keys:
                        continue
                    if any(e.get("is_shallow") or e.get("is_vague") for e in preset_entries):
                        cleared = [
                            {k: v for k, v in e.items() if k not in ("is_shallow", "is_vague")}
                            for e in preset_entries
                        ]
                        self._controller.replace_entries_at_path_for_game(
                            game, path_key, preset, cleared
                        )
                        affected.add(game)

        if affected:
            self._controller.save_games(affected)
        self.accept()
