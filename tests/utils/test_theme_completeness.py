"""Verify that every Chess Log dialog config key is present in all three theme files."""

from __future__ import annotations

import unittest


def _load_config(style_ref: str) -> dict:
    from app.config.config_loader import ConfigLoader
    return ConfigLoader().load_with_style_override(style_ref)


_MOMENT_KEYS = [
    "background_color",
    "border_color",
    "text_color",
    "hint_color",
    "muted_color",
    "separator_color",
    "label_font_family",
    "label_font_size",
    "chip_bg_color",
    "chip_selected_color",
    "chip_text_color",
    "chip_border_color",
    "chip_hover_border_color",
]

_MOMENT_INPUT_KEYS = [
    "font_family",
    "font_size",
    "text_color",
    "background_color",
    "border_color",
    "focus_border_color",
]

_CHESS_LOG_SETTINGS_KEYS = [
    "background_color",
    "border_color",
    "text_color",
]


class TestMomentDialogKeysInAllThemes(unittest.TestCase):
    def _check_theme(self, style_ref: str) -> None:
        config = _load_config(style_ref)
        dc = config.get("ui", {}).get("dialogs", {}).get("moment")
        self.assertIsNotNone(dc, f"ui.dialogs.moment missing in {style_ref}")
        for key in _MOMENT_KEYS:
            self.assertIn(key, dc, f"ui.dialogs.moment.{key} missing in {style_ref}")
        inp = dc.get("inputs")
        self.assertIsNotNone(inp, f"ui.dialogs.moment.inputs missing in {style_ref}")
        for key in _MOMENT_INPUT_KEYS:
            self.assertIn(key, inp, f"ui.dialogs.moment.inputs.{key} missing in {style_ref}")

    def test_default_theme(self):
        self._check_theme("style_default.config.json")

    def test_light_theme(self):
        self._check_theme("style_light.config.json")

    def test_scholar_theme(self):
        self._check_theme("style_scholar.config.json")


class TestChessLogSettingsKeysInAllThemes(unittest.TestCase):
    def _check_theme(self, style_ref: str) -> None:
        config = _load_config(style_ref)
        dc = config.get("ui", {}).get("dialogs", {}).get("chess_log_settings")
        self.assertIsNotNone(dc, f"ui.dialogs.chess_log_settings missing in {style_ref}")
        for key in _CHESS_LOG_SETTINGS_KEYS:
            self.assertIn(key, dc, f"ui.dialogs.chess_log_settings.{key} missing in {style_ref}")

    def test_default_theme(self):
        self._check_theme("style_default.config.json")

    def test_light_theme(self):
        self._check_theme("style_light.config.json")

    def test_scholar_theme(self):
        self._check_theme("style_scholar.config.json")


if __name__ == "__main__":
    unittest.main()
