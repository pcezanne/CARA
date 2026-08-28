"""Dialog for tagging a Chess Log moment (CLAMP, CCT, 3x3, or Custom preset)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.views.style import StyleManager
from app.views.style.line_edit import generate_line_edit_stylesheet


class MomentDialog(QDialog):
    """Tag a game moment with the active preset (CLAMP, CCT, 3x3, or Custom).

    Returns a list of {preset, cat, why} dicts on OK — one entry per selected
    category (CLAMP/CCT/Custom) or one per Why answer (3x3, skipping blanks).
    All entries for a single dialog submission belong to one moment in the 3-cap.
    """

    _CLAMP_CHIPS: List[tuple[str, str]] = [
        ("C", "Checks — missed or overlooked checking moves"),
        ("L", "Loose Pieces — undefended piece or square"),
        ("A", "Alignment — pin, skewer, discovered attack, or fork"),
        ("M", "Mobility — trapped piece or lack of safe squares"),
        ("P", "Pawn Promotion — promotion race or endgame dynamics"),
    ]

    _CCT_CHIPS: List[tuple[str, str]] = [
        ("Checks", "Checks — a checking move that wasn't considered"),
        ("Captures", "Captures — a capture that wasn't considered"),
        ("Threats", "Threats — a non-capturing threat that wasn't considered"),
    ]

    _3X3_PROMPTS: List[tuple[str, str]] = [
        ("Why1", "Why did I make this move?"),
        ("Why2", "Why was it suboptimal?"),
        ("Why3", "Why is the engine's suggestion better?"),
    ]

    def __init__(
        self,
        config: Dict[str, Any],
        active_preset: str,
        custom_categories: List[str],
        move_number: int,
        san: str,
        is_white: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._active_preset = active_preset
        self._custom_categories = list(custom_categories)
        self._move_number = move_number
        self._san = san
        self._is_white = is_white

        self._load_config()
        self._setup_ui()
        self._apply_styling()
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self._apply_size()

        color_str = "White" if is_white else "Black"
        move_label = (
            f"{move_number}. {san}" if is_white else f"{move_number}… {san}"
        )
        self.setWindowTitle(f"Tag this moment — {move_label} ({color_str})")

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

        # Per-preset content
        self._chip_buttons: List[tuple[str, QPushButton]] = []  # (cat_value, btn)
        self._why_edit: Optional[QTextEdit] = None
        self._threexthree_edits: List[tuple[str, QTextEdit]] = []  # (Why1/2/3, edit)
        self._warning_label: Optional[QLabel] = None

        if self._active_preset == "CLAMP":
            self._build_clamp_content(root)
        elif self._active_preset == "CCT":
            self._build_cct_content(root)
        elif self._active_preset == "3x3":
            self._build_threexthree_content(root)
        else:
            # Custom preset
            self._build_custom_content(root)

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

        # Disable OK for empty Custom picklist
        if self._active_preset not in ("CLAMP", "CCT", "3x3") and not self._custom_categories:
            self._ok_btn.setEnabled(False)

    def _label(self, text: str, parent_layout: QVBoxLayout) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont(self._label_font, self._label_size - 1))
        lbl.setStyleSheet(
            f"color: rgb({self._label_color.red()},{self._label_color.green()},{self._label_color.blue()});"
        )
        parent_layout.addWidget(lbl)
        return lbl

    def _build_chip_row(self, chips: List[tuple[str, str]], layout: QVBoxLayout) -> None:
        """Build multi-select chip buttons; each tuple is (cat_value, tooltip)."""
        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        for cat_value, tooltip in chips:
            display = cat_value if len(cat_value) == 1 else cat_value[0]
            btn = QPushButton(display)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setFixedSize(36, 32)
            self._chip_buttons.append((cat_value, btn))
            chip_row.addWidget(btn)
        chip_row.addStretch(1)
        layout.addLayout(chip_row)

    def _build_clamp_content(self, layout: QVBoxLayout) -> None:
        self._label("Select all that apply (more than one may fit):", layout)
        self._build_chip_row(self._CLAMP_CHIPS, layout)
        self._build_why_field(layout)

    def _build_cct_content(self, layout: QVBoxLayout) -> None:
        self._label("Select all that apply (more than one may fit):", layout)
        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        for cat_value, tooltip in self._CCT_CHIPS:
            btn = QPushButton(cat_value)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setMinimumWidth(72)
            btn.setFixedHeight(32)
            self._chip_buttons.append((cat_value, btn))
            chip_row.addWidget(btn)
        chip_row.addStretch(1)
        layout.addLayout(chip_row)
        self._build_why_field(layout)

    def _build_threexthree_content(self, layout: QVBoxLayout) -> None:
        le_ss = self._textedit_stylesheet()
        for key, prompt in self._3X3_PROMPTS:
            self._label(prompt, layout)
            edit = QTextEdit()
            edit.setAcceptRichText(False)
            edit.setFixedHeight(68)
            edit.setStyleSheet(le_ss)
            layout.addWidget(edit)
            self._threexthree_edits.append((key, edit))

    def _build_custom_content(self, layout: QVBoxLayout) -> None:
        if not self._custom_categories:
            warn = QLabel(
                "No custom categories defined yet.\n"
                "Open Chess Log → Chess Log Settings to add some."
            )
            warn.setWordWrap(True)
            warn.setFont(QFont(self._label_font, self._label_size))
            warn.setStyleSheet("color: rgb(220, 160, 60);")
            layout.addWidget(warn)
            self._warning_label = warn
            layout.addStretch(1)
            return

        self._label("Select all that apply (more than one may fit):", layout)
        chips = [(cat, f"Custom category: {cat}") for cat in self._custom_categories]
        self._build_chip_row(chips, layout)
        self._build_why_field(layout)

    def _build_why_field(self, layout: QVBoxLayout) -> None:
        why_label = QLabel("Why did this matter? (optional)")
        why_label.setFont(QFont(self._label_font, self._label_size))
        why_label.setStyleSheet(
            f"color: rgb({self._label_color.red()},{self._label_color.green()},{self._label_color.blue()});"
        )
        layout.addWidget(why_label)
        self._why_edit = QTextEdit()
        self._why_edit.setAcceptRichText(False)
        self._why_edit.setPlaceholderText("Optional — why did this happen?")
        self._why_edit.setFixedHeight(72)
        self._why_edit.setStyleSheet(self._textedit_stylesheet())
        layout.addWidget(self._why_edit)

    def _textedit_stylesheet(self) -> str:
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
        return le_ss.replace("QLineEdit", "QTextEdit")

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

        if self._chip_buttons:
            chip_ss = (
                f"QPushButton {{ background-color: rgb({self._chip_bg_rgb[0]},{self._chip_bg_rgb[1]},{self._chip_bg_rgb[2]}); "
                f"color: rgb({self._chip_text_rgb[0]},{self._chip_text_rgb[1]},{self._chip_text_rgb[2]}); "
                f"border: 1px solid rgb(75,75,82); border-radius: 4px; font-weight: bold; }}"
                f"QPushButton:checked {{ background-color: rgb({self._chip_sel_rgb[0]},{self._chip_sel_rgb[1]},{self._chip_sel_rgb[2]}); "
                f"color: white; border: 1px solid rgb({self._chip_sel_rgb[0]},{self._chip_sel_rgb[1]},{self._chip_sel_rgb[2]}); }}"
                f"QPushButton:hover {{ border: 1px solid rgb(120,120,128); }}"
            )
            for _, btn in self._chip_buttons:
                btn.setStyleSheet(chip_ss)

    def _apply_size(self) -> None:
        self.setFixedWidth(int(self._dialog_width))

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def get_entries(self) -> List[Dict[str, Any]]:
        """Build the list of {preset, cat, why} entries from the current UI state."""
        if self._active_preset == "3x3":
            entries = []
            for key, edit in self._threexthree_edits:
                answer = edit.toPlainText().strip()
                if answer:
                    entries.append({"preset": "3x3", "cat": key, "why": answer})
            return entries

        # CLAMP / CCT / Custom: chip multi-select + optional why
        selected = [cat for cat, btn in self._chip_buttons if btn.isChecked()]
        if not selected:
            return []
        why = self._why_edit.toPlainText().strip() if self._why_edit else ""
        preset = self._active_preset if self._active_preset in ("CLAMP", "CCT") else "Custom"
        return [{"preset": preset, "cat": cat, "why": why} for cat in selected]

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
        active_preset: str,
        custom_categories: List[str],
        move_number: int,
        san: str,
        is_white: bool,
        parent=None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Show the dialog. Returns a list of entries on OK, None on cancel."""
        dlg = MomentDialog(config, active_preset, custom_categories, move_number, san, is_white, parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return dlg.get_entries()
