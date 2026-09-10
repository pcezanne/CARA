"""Unit tests for DatabaseModel."""

from __future__ import annotations

import unittest


class TestDatabaseModelDisplayName(unittest.TestCase):
    def _make_model(self, file_path=None):
        from app.models.database_model import DatabaseModel
        return DatabaseModel(file_path=file_path)

    def test_display_name_returns_stem_for_file_path(self):
        model = self._make_model("/home/user/games/PaulChessGames.pgn")
        self.assertEqual(model.display_name, "PaulChessGames")

    def test_display_name_returns_clipboard_for_none(self):
        model = self._make_model(None)
        self.assertEqual(model.display_name, "Clipboard")

    def test_display_name_stem_strips_extension(self):
        model = self._make_model("/data/MyGames-2026.pgn")
        self.assertEqual(model.display_name, "MyGames-2026")


if __name__ == "__main__":
    unittest.main()
