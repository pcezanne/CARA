"""Dialog for tagging a moment in Chess Log (CLAMP, CCT, or custom category)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.views.style import StyleManager
from app.views.style.line_edit import generate_line_edit_stylesheet


class MomentDialog(QDialog):
    """Tag a game moment with a category (CLAMP, CCT, or custom) and an optional note.

    Returns a list of {preset, cat, why} dicts on OK — one entry per selected
    category.  CLAMP and Custom always return a single-element list.  CCT may
    return up to three (one per selected letter), all sharing the same why text.
    All entries for a single dialog submission belong to one moment in the 3-cap.
    """

    # CLAMP letters with their full names as tooltips
    _CLAMP_CHIPS: List[tuple[str, str]] = [
        ("C", "Checks — missed or overlooked checking moves"),
        ("L", "Loose Pieces — undefended piece or square"),
        ("A", "Alignment — pin, skewer, discovered attack, or fork"),
        ("M", "Mobility — trapped piece or lack of safe squares"),
        ("P", "Pawn Promotion — promotion race or endgame dynamics"),
    ]

    # CCT categories — full words stored to distinguish the two "C"s
    _CCT_CHIPS: List[tuple[str, str, str]] = [
        ("Checks", "C", "Checks — a checking move that wasn't considered"),
        ("Captures", "C", "Captures — a capture that wasn't considered"),
        ("Threats", "T", "Threats — a non-capturing threat that wasn't considered"),
    ]

    def __init__(
        self,
        config: Dict[str, Any],
        move_number: int,
        san: str,
        is_white: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._move_number = move_number
        self._san = san
        self._is_white = is_white

        self._load_config()
        self._setup_ui()
        self._apply_styling()
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self._apply_size()
        self.setWindowTitle("Tag this moment")

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        dc = self.config.get("ui", {}).get("dialogs", {}).get("moment", {})
        self._dialog_width = dc.get("width", 420)
        self._dialog_bg_rgb = dc.get("background_color", [40, 40, 45])
        self._dialog_border_rgb = dc.get("border_color", [60, 60, 65])
        self._button_width = dc.get("button_width", 100)
        self._button_height = dc.get("button_height", 28)

        try:
            from app.utils.font_utils import resolve_font_family, scale_font_size
            self._label_font = resolve_font_family(dc.get("label_font_family", "Helvetica Neue"))
            self._label_size = int(scale_font_size(dc.get("label_font_size", 11)))
        except Exception:
            self._label_font = "Helvetica Neue"
            self._label_size = 11

        self._label_color = QColor(*dc.get("text_color", [200, 200, 200]))
        self._chip_bg_rgb = dc.get("chip_bg_color", [55, 55, 62])
        self._chip_sel_rgb = dc.get("chip_selected_color", [0, 100, 180])
        self._chip_text_rgb = dc.get("chip_text_color", [200, 200, 205])

        inputs = dc.get("inputs", {})
        try:
            from app.utils.font_utils import resolve_font_family, scale_font_size
            self._input_font = resolve_font_family(inputs.get("font_family", "Cascadia Mono"))
            self._input_size = scale_font_size(inputs.get("font_size", 11))
        except Exception:
            self._input_font = "Cascadia Mono"
            self._input_size = 11

        self._input_text_rgb = inputs.get("text_color", [240, 240, 240])
        self._input_bg_rgb = inputs.get("background_color", [30, 30, 35])
        self._input_border_rgb = inputs.get("border_color", [60, 60, 65])

        styles_le = self.config.get("ui", {}).get("styles", {}).get("line_edit", {})
        self._input_focus_border_rgb = inputs.get(
            "focus_border_color", styles_le.get("focus_border_color", [0, 120, 212])
        )
        self._input_border_width = styles_le.get("border_width", 1)
        self._input_hover_border_offset = styles_le.get("hover_border_offset", 20)
        self._input_disabled_factor = float(styles_le.get("disabled_brightness_factor", 0.5))

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        # Header
        label = (
            f"Move {self._move_number}. {self._san}"
            if self._is_white
            else f"Move {self._move_number}… {self._san}"
        )
        header = QLabel(f"Tag moment — {label}")
        header.setFont(QFont(self._label_font, self._label_size))
        header.setStyleSheet(f"color: rgb({self._label_color.red()},{self._label_color.green()},{self._label_color.blue()});")
        root.addWidget(header)

        # Tab widget: CLAMP | CCT | Custom
        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        self._tabs.addTab(self._build_clamp_tab(), "CLAMP")
        self._tabs.addTab(self._build_cct_tab(), "CCT")
        self._tabs.addTab(self._build_custom_tab(), "Custom")

        # Why field (shared)
        why_label = QLabel("Why did this matter? (optional)")
        why_label.setFont(QFont(self._label_font, self._label_size))
        why_label.setStyleSheet(f"color: rgb({self._label_color.red()},{self._label_color.green()},{self._label_color.blue()});")
        root.addWidget(why_label)

        self._why_edit = QTextEdit()
        self._why_edit.setAcceptRichText(False)
        self._why_edit.setPlaceholderText("Optional — why did this happen?")
        self._why_edit.setFixedHeight(72)
        root.addWidget(self._why_edit)

        # Validation hint
        self._hint = QLabel("")
        self._hint.setStyleSheet("color: rgb(220, 80, 80); font-size: 10px;")
        self._hint.setVisible(False)
        root.addWidget(self._hint)

        # OK / Cancel
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setAutoDefault(False)
        self._cancel_btn.clicked.connect(self.reject)
        self._ok_btn = QPushButton("OK")
        self._ok_btn.setDefault(True)
        self._ok_btn.setAutoDefault(True)
        self._ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(self._ok_btn)
        root.addLayout(btn_row)

    def _build_clamp_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        desc = QLabel("Select which thinking process you missed:")
        desc.setFont(QFont(self._label_font, self._label_size - 1))
        desc.setStyleSheet(f"color: rgb({self._label_color.red()},{self._label_color.green()},{self._label_color.blue()});")
        layout.addWidget(desc)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        self._clamp_group = QButtonGroup(self)
        self._clamp_group.setExclusive(True)
        self._clamp_buttons: List[QPushButton] = []

        for letter, tooltip in self._CLAMP_CHIPS:
            btn = QPushButton(letter)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setFixedSize(36, 32)
            self._clamp_group.addButton(btn)
            self._clamp_buttons.append(btn)
            chip_row.addWidget(btn)
        chip_row.addStretch(1)
        layout.addLayout(chip_row)
        layout.addStretch(1)
        return tab

    def _build_cct_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        desc = QLabel("Select all that apply (more than one may fit):")
        desc.setFont(QFont(self._label_font, self._label_size - 1))
        desc.setStyleSheet(f"color: rgb({self._label_color.red()},{self._label_color.green()},{self._label_color.blue()});")
        layout.addWidget(desc)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        self._cct_buttons: List[tuple[str, QPushButton]] = []

        for cat_value, letter, tooltip in self._CCT_CHIPS:
            btn = QPushButton(letter)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setFixedSize(36, 32)
            self._cct_buttons.append((cat_value, btn))
            chip_row.addWidget(btn)

        # Full-name labels below each chip
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        for cat_value, _, _ in self._CCT_CHIPS:
            lbl = QLabel(cat_value)
            lbl.setFont(QFont(self._label_font, max(8, self._label_size - 2)))
            lbl.setStyleSheet(f"color: rgb({self._label_color.red()},{self._label_color.green()},{self._label_color.blue()});")
            lbl.setFixedWidth(36)
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            name_row.addWidget(lbl)

        chip_row.addStretch(1)
        name_row.addStretch(1)
        layout.addLayout(chip_row)
        layout.addLayout(name_row)
        layout.addStretch(1)
        return tab

    def _build_custom_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        desc = QLabel("Enter your own category:")
        desc.setFont(QFont(self._label_font, self._label_size - 1))
        desc.setStyleSheet(f"color: rgb({self._label_color.red()},{self._label_color.green()},{self._label_color.blue()});")
        layout.addWidget(desc)

        self._custom_edit = QLineEdit()
        self._custom_edit.setPlaceholderText("e.g. King safety, Zwischenzug, …")
        layout.addWidget(self._custom_edit)
        layout.addStretch(1)
        return tab

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    def _apply_styling(self) -> None:
        bg = QColor(*self._dialog_bg_rgb)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), bg)
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        StyleManager.style_buttons(
            [self._ok_btn, self._cancel_btn],
            self.config,
            self._dialog_bg_rgb,
            self._dialog_border_rgb,
            min_width=self._button_width,
            min_height=self._button_height,
        )

        chip_normal_ss = (
            f"QPushButton {{ background-color: rgb({self._chip_bg_rgb[0]},{self._chip_bg_rgb[1]},{self._chip_bg_rgb[2]}); "
            f"color: rgb({self._chip_text_rgb[0]},{self._chip_text_rgb[1]},{self._chip_text_rgb[2]}); "
            f"border: 1px solid rgb(75,75,82); border-radius: 4px; font-weight: bold; }}"
            f"QPushButton:checked {{ background-color: rgb({self._chip_sel_rgb[0]},{self._chip_sel_rgb[1]},{self._chip_sel_rgb[2]}); "
            f"color: white; border: 1px solid rgb({self._chip_sel_rgb[0]},{self._chip_sel_rgb[1]},{self._chip_sel_rgb[2]}); }}"
            f"QPushButton:hover {{ border: 1px solid rgb(120,120,128); }}"
        )
        for btn in self._clamp_buttons:
            btn.setStyleSheet(chip_normal_ss)
        for _, btn in self._cct_buttons:
            btn.setStyleSheet(chip_normal_ss)

        le_ss = generate_line_edit_stylesheet(
            self.config,
            self._input_text_rgb,
            self._input_font,
            self._input_size,
            self._input_bg_rgb,
            self._input_border_rgb,
            self._input_focus_border_rgb,
            border_width=self._input_border_width,
            border_radius=3,
            padding=[8, 6],
            hover_border_offset=self._input_hover_border_offset,
            disabled_brightness_factor=self._input_disabled_factor,
        )
        self._custom_edit.setStyleSheet(le_ss)
        self._why_edit.setStyleSheet(le_ss.replace("QLineEdit", "QTextEdit"))

    def _apply_size(self) -> None:
        self.setFixedWidth(int(self._dialog_width))

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def get_entries(self) -> List[Dict[str, Any]]:
        """Build the list of {preset, cat, why} entries from the current UI state."""
        why = self._why_edit.toPlainText().strip()
        idx = self._tabs.currentIndex()

        if idx == 0:  # CLAMP
            checked = self._clamp_group.checkedButton()
            if checked is None:
                return []
            return [{"preset": "CLAMP", "cat": checked.text(), "why": why}]

        if idx == 1:  # CCT
            selected = [cat for cat, btn in self._cct_buttons if btn.isChecked()]
            if not selected:
                return []
            return [{"preset": "CCT", "cat": cat, "why": why} for cat in selected]

        # Custom
        cat = self._custom_edit.text().strip()
        if not cat:
            return []
        return [{"preset": "custom", "cat": cat, "why": why}]

    def _on_ok(self) -> None:
        entries = self.get_entries()
        if not entries:
            self._hint.setText("Please select or enter a category.")
            self._hint.setVisible(True)
            return
        self._hint.setVisible(False)
        self.accept()

    # ------------------------------------------------------------------
    # Static factory
    # ------------------------------------------------------------------

    @staticmethod
    def tag_moment(
        config: Dict[str, Any],
        move_number: int,
        san: str,
        is_white: bool,
        parent=None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Show the dialog. Returns a list of entries on OK, None on cancel."""
        dlg = MomentDialog(config, move_number, san, is_white, parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return dlg.get_entries()
