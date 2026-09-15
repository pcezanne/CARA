"""Tests for ChessLogPDFService — filename helpers and export smoke tests."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _qt_starts_cleanly() -> bool:
    probe = (
        "import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); "
        "from PyQt6.QtWidgets import QApplication; a = QApplication([]); print('ok')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            timeout=10,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        return result.returncode == 0 and b"ok" in result.stdout
    except Exception:
        return False


_QT_OK = _qt_starts_cleanly()
requires_qt = unittest.skipUnless(_QT_OK, "Qt platform plugin unavailable")

if _QT_OK:
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication(sys.argv[:1])

    from app.services.chess_log_pdf_service import (
        ChessLogPDFService,
        TagRowSnapshot,
        default_chess_log_charts_pdf_filename,
        default_chess_log_tags_pdf_filename,
    )


class TestFilenameHelpers(unittest.TestCase):
    def test_tags_filename_has_pdf_extension(self):
        name = default_chess_log_tags_pdf_filename()
        self.assertTrue(name.endswith(".pdf"), name)

    def test_tags_filename_shallow_variant(self):
        name = default_chess_log_tags_pdf_filename(is_shallow_only=True)
        self.assertIn("ShallowTags", name)

    def test_charts_filename_has_pdf_extension(self):
        name = default_chess_log_charts_pdf_filename()
        self.assertTrue(name.endswith(".pdf"), name)

    def test_charts_filename_includes_player_name(self):
        name = default_chess_log_charts_pdf_filename("Paul")
        self.assertIn("Paul", name)

    def test_charts_filename_sanitizes_spaces(self):
        name = default_chess_log_charts_pdf_filename("Paul Morphy")
        self.assertTrue(name.endswith(".pdf"), name)
        self.assertNotIn(" ", name)


@requires_qt
class TestExportTagsSmoke(unittest.TestCase):
    """Smoke tests: export_tags writes a non-empty PDF file."""

    _MINIMAL_CONFIG: dict = {}

    def _make_minimal_snapshot(self) -> TagRowSnapshot:
        return TagRowSnapshot(
            move_label="1. e4",
            preset="CLAMP",
            entries=[{"preset": "CLAMP", "cat": "C", "why": "test note"}],
            fen=None,
            played_move=None,
            show_ignore=False,
        )

    def test_export_tags_creates_file(self):
        svc = ChessLogPDFService(self._MINIMAL_CONFIG)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            result = svc.export_tags(tmp_path, [{"header": None, "rows": [self._make_minimal_snapshot()]}])
            self.assertTrue(result, "export_tags returned False")
            self.assertTrue(tmp_path.exists(), "PDF file not created")
            self.assertGreater(tmp_path.stat().st_size, 0, "PDF file is empty")
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_export_tags_multi_game(self):
        svc = ChessLogPDFService(self._MINIMAL_CONFIG)
        groups = [
            {"header": "White - Black * (2026.01.01 - 20 moves)", "rows": [self._make_minimal_snapshot()]},
            {"header": "A - B 1-0 (2026.02.01 - 15 moves)", "rows": [self._make_minimal_snapshot()]},
        ]
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            result = svc.export_tags(tmp_path, groups)
            self.assertTrue(result)
            self.assertGreater(tmp_path.stat().st_size, 0)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_export_tags_empty_groups_succeeds(self):
        svc = ChessLogPDFService(self._MINIMAL_CONFIG)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            result = svc.export_tags(tmp_path, [])
            self.assertTrue(result)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_export_charts_report_creates_file(self):
        from PyQt6.QtGui import QPixmap
        svc = ChessLogPDFService(self._MINIMAL_CONFIG)
        pixmap = QPixmap(400, 200)
        pixmap.fill()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            result = svc.export_charts_report(
                tmp_path,
                player_name="Paul",
                source_label="Active Database",
                chart_pixmaps=[("CLAMP", pixmap)],
                narrative_text="Test narrative text.",
                shallow_rows=[],
            )
            self.assertTrue(result, "export_charts_report returned False")
            self.assertGreater(tmp_path.stat().st_size, 0)
        finally:
            tmp_path.unlink(missing_ok=True)


class TestParseBoldSpans(unittest.TestCase):
    """Unit tests for ChessLogPDFService._parse_bold_spans — no Qt needed."""

    def _parse(self, text):
        if _QT_OK:
            return ChessLogPDFService._parse_bold_spans(text)
        # Fallback: import directly without Qt guard
        from app.services.chess_log_pdf_service import ChessLogPDFService as _Svc
        return _Svc._parse_bold_spans(text)

    def test_empty_string(self):
        self.assertEqual(self._parse(""), [])

    def test_no_markers(self):
        self.assertEqual(self._parse("hello world"), [("hello world", False)])

    def test_single_bold_span(self):
        result = self._parse("**bold**")
        self.assertEqual(result, [("bold", True)])

    def test_bold_in_middle(self):
        result = self._parse("before **bold** after")
        self.assertEqual(result, [("before ", False), ("bold", True), (" after", False)])

    def test_two_bold_spans(self):
        result = self._parse("**a** and **b**")
        self.assertIn(("a", True), result)
        self.assertIn(("b", True), result)

    def test_unmatched_trailing_marker_treated_as_literal(self):
        result = self._parse("text **orphan")
        joined = "".join(s for s, _ in result)
        self.assertIn("**orphan", joined)
        # None of the runs should be bold since there's no closing marker.
        self.assertTrue(all(not bold for _, bold in result))


@requires_qt
class TestDrawNarrativePaginated(unittest.TestCase):
    """drawText-spy tests for bold-span rendering in _draw_narrative_paginated."""

    from unittest.mock import MagicMock

    def _make_service(self):
        return ChessLogPDFService({})

    def _run(self, text):
        from unittest.mock import MagicMock
        from PyQt6.QtCore import QRectF
        svc = self._make_service()
        painter = MagicMock()
        writer = MagicMock()
        content = QRectF(0, 0, 500, 700)
        svc._draw_narrative_paginated(painter, writer, content, 0.0, text)
        return svc, painter

    def test_no_asterisks_reach_draw_text(self):
        _, painter = self._run("Regular **bold phrase** rest of line.")
        drawn_strings = [
            a for call in painter.drawText.call_args_list
            for a in call.args if isinstance(a, str)
        ]
        self.assertFalse(
            any("**" in s for s in drawn_strings),
            f"raw ** markers reached drawText: {drawn_strings}",
        )

    def test_bold_font_used_for_bold_span(self):
        svc, painter = self._run("Plain **emphatic** end.")
        bold_calls = [
            c for c in painter.setFont.call_args_list
            if c.args and c.args[0] == svc._font_body_bold
        ]
        self.assertGreater(len(bold_calls), 0,
                           "Expected at least one setFont(_font_body_bold) call")

    def test_plain_text_no_bold_font_calls(self):
        svc, painter = self._run("Completely plain sentence with no markers.")
        bold_calls = [
            c for c in painter.setFont.call_args_list
            if c.args and c.args[0] == svc._font_body_bold
        ]
        self.assertEqual(len(bold_calls), 0,
                         "No bold font expected for plain text")

    def test_heading_does_not_call_draw_text_directly(self):
        """Heading lines go through _section_heading, not the word-draw loop."""
        from unittest.mock import MagicMock, patch
        from PyQt6.QtCore import QRectF
        svc = self._make_service()
        painter = MagicMock()
        writer = MagicMock()
        content = QRectF(0, 0, 500, 700)
        with patch.object(svc, "_section_heading", return_value=10.0) as mock_sh:
            svc._draw_narrative_paginated(painter, writer, content, 0.0,
                                          "## My Heading\nBody text here.")
        mock_sh.assert_called_once()
        drawn_strings = [
            a for call in painter.drawText.call_args_list
            for a in call.args if isinstance(a, str)
        ]
        self.assertFalse(
            any("My Heading" in s for s in drawn_strings),
            "Heading text should not reach drawText directly",
        )


if __name__ == "__main__":
    unittest.main()
