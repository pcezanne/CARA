"""Phase 8: verify that Chess Log config paths exist in all three theme files.

Does NOT load via ConfigLoader (no $ref expansion needed) — just checks key
existence so a missing entry is caught before the app is launched.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any


_REPO = Path(__file__).resolve().parents[2]
_STYLE_FILES = [
    _REPO / "app/config/style_default.config.json",
    _REPO / "app/config/style_light.config.json",
    _REPO / "app/config/style_scholar.config.json",
]

_CHESS_LOG_CHARTS_COLOR_KEYS = [
    "ui.panels.detail.chess_log_charts.colors.background",
    "ui.panels.detail.chess_log_charts.colors.text",
    "ui.panels.detail.chess_log_charts.colors.input_background",
    "ui.panels.detail.chess_log_charts.colors.border",
    "ui.panels.detail.chess_log_charts.colors.hint_text",
    "ui.panels.detail.chess_log_charts.colors.link",
    "ui.panels.detail.chess_log_charts.colors.spinner_color",
]

_CHESS_LOG_CHARTS_PDF_KEYS = [
    "ui.panels.detail.chess_log_charts.pdf_report.colors.warning_fill",
    "ui.panels.detail.chess_log_charts.pdf_report.colors.warning_outline",
    "ui.panels.detail.chess_log_charts.pdf_report.table_col_widths_pct",
]

_CHESS_LOG_CHARTS_CHART_KEYS = [
    "ui.panels.detail.chess_log_charts.chart.background_color",
    "ui.panels.detail.chess_log_charts.chart.grid_color",
    "ui.panels.detail.chess_log_charts.chart.axis_color",
    "ui.panels.detail.chess_log_charts.chart.text_color",
    "ui.panels.detail.chess_log_charts.chart.title_color",
]

_ALL_PATHS = (
    _CHESS_LOG_CHARTS_COLOR_KEYS
    + _CHESS_LOG_CHARTS_PDF_KEYS
    + _CHESS_LOG_CHARTS_CHART_KEYS
)


def _get_nested(d: Any, dotted_path: str) -> bool:
    """Return True iff the dotted key path exists in the nested dict."""
    parts = dotted_path.split(".")
    cur = d
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


class TestChessLogThemeCoverage(unittest.TestCase):
    """All curated Chess Log config paths must be present in every theme file."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._themes: dict[str, Any] = {}
        for path in _STYLE_FILES:
            with open(path, encoding="utf-8") as fh:
                cls._themes[path.name] = json.load(fh)

    def _check_path(self, dotted_path: str) -> None:
        for name, cfg in self._themes.items():
            with self.subTest(theme=name, path=dotted_path):
                self.assertTrue(
                    _get_nested(cfg, dotted_path),
                    f"{name} is missing key path: {dotted_path}",
                )

    def test_chess_log_charts_color_keys_present(self):
        for path in _CHESS_LOG_CHARTS_COLOR_KEYS:
            self._check_path(path)

    def test_chess_log_charts_pdf_keys_present(self):
        for path in _CHESS_LOG_CHARTS_PDF_KEYS:
            self._check_path(path)

    def test_chess_log_charts_chart_keys_present(self):
        for path in _CHESS_LOG_CHARTS_CHART_KEYS:
            self._check_path(path)


if __name__ == "__main__":
    unittest.main()
