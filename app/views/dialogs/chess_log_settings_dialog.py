"""Dialog for Chess Log settings: choose active preset and manage custom categories."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.views.style import StyleManager
from app.views.style.line_edit import generate_line_edit_stylesheet


class ChessLogSettingsDialog(QDialog):
    """Settings dialog for Chess Log: active preset and custom category management.

    Mirrors the AI Model Settings dialog constructor pattern:
    __init__(config, user_settings_service, parent=None).
    """

    _PRESETS = ["CLAMP", "CCT", "3x3", "Custom"]
    _PRESET_DISPLAY_NAMES = {"3x3": "3x3 Method"}

    def __init__(self, config: Dict[str, Any], user_settings_service, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self._user_settings_service = user_settings_service

        chess_log = user_settings_service.get_chess_log()
        self._active_preset: str = chess_log.get("active_preset", "CLAMP")
        raw_cats = chess_log.get("custom_categories", [])
        self._categories: List[str] = list(raw_cats) if isinstance(raw_cats, list) else []

        self._load_config()
        self._setup_ui()
        self._apply_styling()
        self._apply_size()
        self.setWindowTitle("Chess Log Settings")

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        dc = self.config.get("ui", {}).get("dialogs", {}).get("chess_log_settings", {})
        self._dialog_width = dc.get("width", 400)
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
        root.setSpacing(12)

        # --- Preset selection ---
        preset_group = QGroupBox("Active Preset")
        preset_group.setFont(QFont(self._label_font, self._label_size))
        preset_layout = QVBoxLayout(preset_group)
        preset_layout.setSpacing(6)

        self._preset_radio_group = QButtonGroup(self)
        self._radio_buttons: Dict[str, QRadioButton] = {}

        preset_descriptions = {
            "CLAMP": "Checks · Loose Pieces · Alignment · Mobility · Promotion",
            "CCT": "Checks · Captures · Threats",
            "3x3": "Three guided Whys per game moment",
            "Custom": "Your own category vocabulary (manage below)",
        }

        preset_attributions = {
            "CLAMP": "Developed by Dr. Can Kabadayi",
            "3x3": "Developed by GM Noel Studer",
        }

        dim_color = (
            f"color: rgb({max(0, self._label_color.red()-40)},"
            f"{max(0, self._label_color.green()-40)},"
            f"{max(0, self._label_color.blue()-40)});"
        )
        attr_color = (
            f"color: rgb({max(0, self._label_color.red()-70)},"
            f"{max(0, self._label_color.green()-70)},"
            f"{max(0, self._label_color.blue()-70)}); font-style: italic;"
        )

        for preset in self._PRESETS:
            row = QHBoxLayout()
            rb = QRadioButton(self._PRESET_DISPLAY_NAMES.get(preset, preset))
            rb.setFont(QFont(self._label_font, self._label_size))
            rb.setChecked(preset == self._active_preset)
            self._preset_radio_group.addButton(rb)
            self._radio_buttons[preset] = rb
            row.addWidget(rb)
            desc = QLabel(preset_descriptions[preset])
            desc.setFont(QFont(self._label_font, max(9, self._label_size - 1)))
            desc.setStyleSheet(dim_color)
            row.addWidget(desc)
            row.addStretch(1)
            preset_layout.addLayout(row)
            rb.toggled.connect(self._on_preset_toggled)
            if preset in preset_attributions:
                attr_row = QHBoxLayout()
                attr_row.addSpacing(20)
                attr_lbl = QLabel(preset_attributions[preset])
                attr_lbl.setFont(QFont(self._label_font, max(8, self._label_size - 2)))
                attr_lbl.setStyleSheet(attr_color)
                attr_row.addWidget(attr_lbl)
                attr_row.addStretch(1)
                preset_layout.addLayout(attr_row)

        root.addWidget(preset_group)

        # --- Custom picklist manager ---
        self._custom_section = QGroupBox("Custom Categories")
        self._custom_section.setFont(QFont(self._label_font, self._label_size))
        custom_layout = QVBoxLayout(self._custom_section)
        custom_layout.setSpacing(6)

        hint = QLabel("Add your own tag vocabulary. Each category becomes a chip in the tagging dialog.")
        hint.setWordWrap(True)
        hint.setFont(QFont(self._label_font, max(9, self._label_size - 1)))
        hint.setStyleSheet(
            f"color: rgb({max(0, self._label_color.red()-40)},"
            f"{max(0, self._label_color.green()-40)},"
            f"{max(0, self._label_color.blue()-40)});"
        )
        custom_layout.addWidget(hint)

        # Scrollable category list
        self._cat_list_widget = QWidget()
        self._cat_list_layout = QVBoxLayout(self._cat_list_widget)
        self._cat_list_layout.setContentsMargins(0, 0, 0, 0)
        self._cat_list_layout.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(160)
        scroll.setWidget(self._cat_list_widget)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        custom_layout.addWidget(scroll)

        # Populate existing categories
        self._cat_rows: List[tuple[QLineEdit, QPushButton]] = []
        for cat in self._categories:
            self._add_category_row(cat)

        # Add button
        add_row = QHBoxLayout()
        self._add_btn = QPushButton("+ Add category")
        self._add_btn.setFixedHeight(self._button_height)
        self._add_btn.clicked.connect(self._on_add_category)
        add_row.addWidget(self._add_btn)
        add_row.addStretch(1)
        custom_layout.addLayout(add_row)

        root.addWidget(self._custom_section)

        # Show/hide Custom section based on initial preset
        self._custom_section.setVisible(self._active_preset == "Custom")

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

    def _add_category_row(self, text: str = "") -> None:
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
            padding=[6, 4],
            hover_border_offset=self._input_hover_border_offset,
            disabled_brightness_factor=self._input_disabled_factor,
        )
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        edit = QLineEdit(text)
        edit.setPlaceholderText("Category name…")
        edit.setStyleSheet(le_ss)
        row_layout.addWidget(edit, 1)

        del_btn = QPushButton("×")
        del_btn.setFixedSize(24, 24)
        del_btn.setToolTip("Remove this category")
        del_btn.clicked.connect(lambda: self._on_delete_category(row_widget, edit, del_btn))
        row_layout.addWidget(del_btn)

        self._cat_list_layout.addWidget(row_widget)
        self._cat_rows.append((edit, del_btn))

    def _on_delete_category(self, row_widget: QWidget, edit: QLineEdit, del_btn: QPushButton) -> None:
        row_widget.deleteLater()
        self._cat_rows = [(e, d) for e, d in self._cat_rows if e is not edit]

    def _on_add_category(self) -> None:
        self._add_category_row("")

    def _on_preset_toggled(self) -> None:
        selected = next(
            (name for name, rb in self._radio_buttons.items() if rb.isChecked()), "CLAMP"
        )
        self._custom_section.setVisible(selected == "Custom")
        self.adjustSize()

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

        label_ss = (
            f"color: rgb({self._label_color.red()},{self._label_color.green()},{self._label_color.blue()});"
        )
        group_ss = (
            f"QGroupBox {{ color: rgb({self._label_color.red()},{self._label_color.green()},{self._label_color.blue()}); "
            f"border: 1px solid rgb({self._dialog_border_rgb[0]},{self._dialog_border_rgb[1]},{self._dialog_border_rgb[2]}); "
            f"border-radius: 4px; margin-top: 8px; padding-top: 8px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}"
        )
        for rb in self._radio_buttons.values():
            rb.setStyleSheet(label_ss)
        for w in [self._custom_section, preset_group := self.findChild(QGroupBox)]:
            if w:
                w.setStyleSheet(group_ss)

        StyleManager.style_buttons(
            [self._add_btn],
            self.config,
            self._dialog_bg_rgb,
            self._dialog_border_rgb,
            min_width=120,
            min_height=self._button_height,
        )

    def _apply_size(self) -> None:
        self.setMinimumWidth(int(self._dialog_width))

    # ------------------------------------------------------------------
    # Accept
    # ------------------------------------------------------------------

    def _on_ok(self) -> None:
        selected_preset = next(
            (name for name, rb in self._radio_buttons.items() if rb.isChecked()), "CLAMP"
        )
        cats = [
            edit.text().strip()
            for edit, _ in self._cat_rows
            if edit.text().strip()
        ]
        self._user_settings_service.update_chess_log_settings({
            "active_preset": selected_preset,
            "custom_categories": cats,
        })
        self._user_settings_service.save()
        self.accept()
