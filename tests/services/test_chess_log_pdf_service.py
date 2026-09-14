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


if __name__ == "__main__":
    unittest.main()
