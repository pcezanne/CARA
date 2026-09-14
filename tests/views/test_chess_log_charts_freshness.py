"""Tests for DetailChessLogChartsView freshness-cache and invalidation."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

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
    from app.views.detail_chess_log_charts_view import DetailChessLogChartsView


_MINIMAL_CONFIG: dict = {}
_SHALLOW_KEYS = frozenset({(1, "k1", "CLAMP"), (2, "k2", "CCT")})


@requires_qt
class TestShalowKeysFreshness(unittest.TestCase):
    def setUp(self):
        self._view = DetailChessLogChartsView(_MINIMAL_CONFIG)

    def test_initial_state_is_none(self):
        self.assertIsNone(self._view._last_shallow_keys)

    def test_on_shallow_ready_caches_keys(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS)
        self.assertEqual(self._view._last_shallow_keys, _SHALLOW_KEYS)

    def test_on_shallow_ready_empty_set_stores_none(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS)  # set first
        self._view._on_shallow_ready(set())
        self.assertIsNone(self._view._last_shallow_keys)

    def test_on_source_changed_clears_cache(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS)
        self._view._on_source_changed(1)
        self.assertIsNone(self._view._last_shallow_keys)

    def test_on_player_changed_clears_cache(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS)
        # _on_player_changed with index=-1 returns early without controller call
        # but still clears cache
        self._view._on_player_changed(-1)
        self.assertIsNone(self._view._last_shallow_keys)

    def test_cache_survives_narrative_ready(self):
        self._view._on_shallow_ready(_SHALLOW_KEYS)
        # Narrative update should not touch shallow cache
        self._view._on_narrative_ready("some narrative", [])
        self.assertEqual(self._view._last_shallow_keys, _SHALLOW_KEYS)

    def test_cache_type_is_frozenset(self):
        self._view._on_shallow_ready({(1, "k", "CLAMP")})
        self.assertIsInstance(self._view._last_shallow_keys, frozenset)


if __name__ == "__main__":
    unittest.main()
