"""Tests for ChessLogStatsService aggregation."""

from __future__ import annotations

import unittest

from app.models.database_model import GameData
from app.services.chess_log_storage_service import ChessLogStorageService
from app.services.chess_log_stats_service import (
    CHARTED_PRESETS,
    UNCATEGORIZED,
    ChessLogCategoryBin,
    ChessLogPresetSeries,
    aggregate,
    get_all_players,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_PGN = (
    '[Event "Test"]\n'
    '[Site "?"]\n'
    '[Date "{date}"]\n'
    '[Round "?"]\n'
    '[White "{white}"]\n'
    '[Black "{black}"]\n'
    '[Result "*"]\n'
    '\n1. e4 *\n'
)


def _make_game(
    white: str = "Alice",
    black: str = "Bob",
    date: str = "2025.01.15",
    entries_per_path: dict | None = None,
) -> GameData:
    pgn = _BASE_PGN.format(white=white, black=black, date=date)
    game = GameData(game_number=1, pgn=pgn, white=white, black=black, date=date)
    if entries_per_path:
        ChessLogStorageService.store_tags(game, entries_per_path)
    return game


def _clamp_entry(cat: str, why: str = "") -> dict:
    return ChessLogStorageService.make_entry("CLAMP", cat, why)


def _cct_entry(cat: str, why: str = "") -> dict:
    return ChessLogStorageService.make_entry("CCT", cat, why)


def _custom_entry(cat: str, why: str = "") -> dict:
    return ChessLogStorageService.make_entry("Custom", cat, why)


def _threexthree_entry(cat: str, why: str) -> dict:
    return ChessLogStorageService.make_entry("3x3", cat, why)


# ---------------------------------------------------------------------------
# Basic aggregation
# ---------------------------------------------------------------------------

class TestBasicAggregation(unittest.TestCase):

    def _one_game(self, entries_per_path, player="Alice", color_filter="both"):
        game = _make_game(white="Alice", black="Bob", date="2025.06.01",
                          entries_per_path=entries_per_path)
        return aggregate([game], player=player, color_filter=color_filter)

    def test_single_clamp_moment_returns_one_preset(self):
        result = self._one_game({"0": [_clamp_entry("C")]})
        self.assertIn("CLAMP", result)
        self.assertEqual(len(result), 1)

    def test_clamp_moment_count_correct(self):
        result = self._one_game({"0": [_clamp_entry("C"), _clamp_entry("L")]})
        series = result["CLAMP"]
        total = sum(b.total for b in series.bins)
        self.assertEqual(total, 2)

    def test_uncategorized_moment_surfaces_as_empty_key(self):
        result = self._one_game({"0": [_clamp_entry("")]})
        series = result["CLAMP"]
        self.assertIn(UNCATEGORIZED, series.categories)
        all_counts = {}
        for b in series.bins:
            for cat, cnt in b.counts.items():
                all_counts[cat] = all_counts.get(cat, 0) + cnt
        self.assertEqual(all_counts.get(UNCATEGORIZED, 0), 1)

    def test_uncategorized_is_last_in_categories(self):
        result = self._one_game({"0": [_clamp_entry("C"), _clamp_entry("")]})
        cats = result["CLAMP"].categories
        self.assertEqual(cats[-1], UNCATEGORIZED)

    def test_no_games_returns_empty(self):
        self.assertEqual(aggregate([], player="Alice"), {})

    def test_game_with_no_chess_log_tags_skipped(self):
        game = _make_game(white="Alice", black="Bob", date="2025.06.01")
        result = aggregate([game], player="Alice")
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# Preset separation
# ---------------------------------------------------------------------------

class TestPresetSeparation(unittest.TestCase):

    def _mixed_game(self):
        return _make_game(
            white="Alice", black="Bob", date="2025.06.01",
            entries_per_path={
                "0": [_clamp_entry("C")],
                "0.0": [_cct_entry("Checks")],
                "0.0.0": [_custom_entry("Time trouble")],
            },
        )

    def test_three_presets_produce_three_series(self):
        result = aggregate([self._mixed_game()], player="Alice")
        self.assertIn("CLAMP", result)
        self.assertIn("CCT", result)
        self.assertIn("Custom", result)
        self.assertEqual(len(result), 3)

    def test_presets_not_mixed(self):
        result = aggregate([self._mixed_game()], player="Alice")
        for preset, series in result.items():
            for b in series.bins:
                for cat in b.counts:
                    self.assertNotIn(cat, {"Checks", "C", "Time trouble"} - {
                        "Checks" if preset == "CCT" else "",
                        "C" if preset == "CLAMP" else "",
                        "Time trouble" if preset == "Custom" else "",
                    })

    def test_3x3_excluded(self):
        game = _make_game(
            white="Alice", black="Bob", date="2025.06.01",
            entries_per_path={"0": [_threexthree_entry("Why1", "reason")]},
        )
        result = aggregate([game], player="Alice")
        self.assertNotIn("3x3", result)

    def test_3x3_alongside_clamp_clamp_present_3x3_absent(self):
        game = _make_game(
            white="Alice", black="Bob", date="2025.06.01",
            entries_per_path={
                "0": [_clamp_entry("M")],
                "0.0": [_threexthree_entry("Why1", "thought")],
            },
        )
        result = aggregate([game], player="Alice")
        self.assertIn("CLAMP", result)
        self.assertNotIn("3x3", result)


# ---------------------------------------------------------------------------
# Player filter
# ---------------------------------------------------------------------------

class TestPlayerFilter(unittest.TestCase):

    def _two_games(self):
        g1 = _make_game(white="Alice", black="Bob", date="2025.01.01",
                        entries_per_path={"0": [_clamp_entry("C")]})
        g2 = _make_game(white="Carlos", black="Alice", date="2025.02.01",
                        entries_per_path={"0": [_clamp_entry("L")]})
        g3 = _make_game(white="Carlos", black="Bob", date="2025.03.01",
                        entries_per_path={"0": [_clamp_entry("M")]})
        return [g1, g2, g3]

    def test_player_filter_excludes_games_without_player(self):
        result = aggregate(self._two_games(), player="Alice")
        total = sum(b.total for b in result["CLAMP"].bins)
        self.assertEqual(total, 2)  # g1 and g2, not g3

    def test_color_filter_white_only(self):
        result = aggregate(self._two_games(), player="Alice", color_filter="white")
        total = sum(b.total for b in result["CLAMP"].bins)
        self.assertEqual(total, 1)  # only g1 (Alice is White)

    def test_color_filter_black_only(self):
        result = aggregate(self._two_games(), player="Alice", color_filter="black")
        total = sum(b.total for b in result["CLAMP"].bins)
        self.assertEqual(total, 1)  # only g2 (Alice is Black)

    def test_no_player_includes_all_games(self):
        result = aggregate(self._two_games(), player="")
        total = sum(b.total for b in result["CLAMP"].bins)
        self.assertEqual(total, 3)

    def test_player_name_case_insensitive(self):
        result = aggregate(self._two_games(), player="alice")
        total = sum(b.total for b in result["CLAMP"].bins)
        self.assertEqual(total, 2)


# ---------------------------------------------------------------------------
# Mixed-preset history across multiple games
# ---------------------------------------------------------------------------

class TestMixedPresetHistory(unittest.TestCase):

    def test_two_games_different_presets_produces_two_series(self):
        g1 = _make_game(white="Alice", black="Bob", date="2025.01.01",
                        entries_per_path={"0": [_clamp_entry("C")]})
        g2 = _make_game(white="Alice", black="Bob", date="2025.02.01",
                        entries_per_path={"0": [_cct_entry("Threats")]})
        result = aggregate([g1, g2], player="Alice")
        self.assertIn("CLAMP", result)
        self.assertIn("CCT", result)

    def test_categories_from_same_preset_across_games_merged(self):
        g1 = _make_game(white="Alice", black="Bob", date="2025.01.01",
                        entries_per_path={"0": [_clamp_entry("C")]})
        g2 = _make_game(white="Alice", black="Bob", date="2025.02.01",
                        entries_per_path={"0": [_clamp_entry("L")]})
        result = aggregate([g1, g2], player="Alice")
        cats = result["CLAMP"].categories
        self.assertIn("C", cats)
        self.assertIn("L", cats)


# ---------------------------------------------------------------------------
# Canonical preset ordering (Item 7)
# ---------------------------------------------------------------------------

class TestCanonicalCategoryOrder(unittest.TestCase):

    def _game_with_cats(self, preset: str, cats: list[str], make_entry_fn) -> GameData:
        paths = {str(i): [make_entry_fn(c)] for i, c in enumerate(cats)}
        return _make_game(white="Alice", black="Bob", date="2025.06.01",
                          entries_per_path=paths)

    def test_clamp_canonical_order_regardless_of_tag_order(self):
        # Tag in reverse canonical order (P, M, A, L, C)
        game = self._game_with_cats("CLAMP", ["P", "M", "A", "L", "C"], _clamp_entry)
        result = aggregate([game], player="Alice")
        cats = result["CLAMP"].categories
        self.assertEqual(cats, ["C", "L", "A", "M", "P"])

    def test_cct_canonical_order_regardless_of_tag_order(self):
        game = self._game_with_cats("CCT", ["Threats", "Checks", "Captures"], _cct_entry)
        result = aggregate([game], player="Alice")
        cats = result["CCT"].categories
        self.assertEqual(cats, ["Checks", "Captures", "Threats"])

    def test_clamp_partial_subset_canonical_order(self):
        # CLAMP always seeds all 5 canonical categories even when only a subset is tagged.
        game = self._game_with_cats("CLAMP", ["P", "C"], _clamp_entry)
        result = aggregate([game], player="Alice")
        cats = result["CLAMP"].categories
        self.assertEqual(cats, ["C", "L", "A", "M", "P"])

    def test_custom_with_preset_orders_respected(self):
        game = self._game_with_cats("Custom", ["Zeta", "Alpha", "Mango"], _custom_entry)
        result = aggregate(
            [game],
            player="Alice",
            preset_orders={"Custom": ["Mango", "Alpha", "Zeta"]},
        )
        cats = result["Custom"].categories
        self.assertEqual(cats, ["Mango", "Alpha", "Zeta"])

    def test_custom_without_preset_orders_alphabetical(self):
        game = self._game_with_cats("Custom", ["Zeta", "Alpha"], _custom_entry)
        result = aggregate([game], player="Alice")
        cats = result["Custom"].categories
        self.assertEqual(cats, ["Alpha", "Zeta"])

    def test_uncategorized_always_last_in_canonical_order(self):
        paths = {
            "0": [_clamp_entry("P")],
            "1": [_clamp_entry("")],
            "2": [_clamp_entry("C")],
        }
        game = _make_game(white="Alice", black="Bob", date="2025.06.01",
                          entries_per_path=paths)
        result = aggregate([game], player="Alice")
        cats = result["CLAMP"].categories
        self.assertEqual(cats[-1], "")
        self.assertEqual(cats[0], "C")


# ---------------------------------------------------------------------------
# Canonical category always present for CLAMP/CCT (Bug 4 fix)
# ---------------------------------------------------------------------------

class TestCanonicalCategoryAlwaysPresent(unittest.TestCase):
    """CLAMP and CCT seed all canonical categories even if absent from data."""

    def _game_with_cats(self, preset: str, cats: list[str], make_entry_fn) -> GameData:
        paths = {str(i): [make_entry_fn(c)] for i, c in enumerate(cats)}
        return _make_game(white="Alice", black="Bob", date="2025.06.01",
                          entries_per_path=paths)

    def test_clamp_missing_categories_seeded(self):
        game = self._game_with_cats("CLAMP", ["C"], _clamp_entry)
        result = aggregate([game], player="Alice")
        self.assertEqual(result["CLAMP"].categories, ["C", "L", "A", "M", "P"])

    def test_cct_missing_categories_seeded(self):
        game = self._game_with_cats("CCT", ["Threats"], _cct_entry)
        result = aggregate([game], player="Alice")
        self.assertEqual(result["CCT"].categories, ["Checks", "Captures", "Threats"])

    def test_custom_only_present_categories_shown(self):
        # Custom preset does NOT seed — only categories with data appear.
        game = self._game_with_cats("Custom", ["Alpha"], _custom_entry)
        result = aggregate(
            [game],
            player="Alice",
            preset_orders={"Custom": ["Alpha", "Beta", "Gamma"]},
        )
        self.assertEqual(result["Custom"].categories, ["Alpha"])

    def test_clamp_seeded_cats_have_zero_counts_in_bins(self):
        # Seeded categories absent from data must appear in categories list
        # with zero counts across all bins.
        game = self._game_with_cats("CLAMP", ["C"], _clamp_entry)
        result = aggregate([game], player="Alice")
        series = result["CLAMP"]
        for absent_cat in ("L", "A", "M", "P"):
            self.assertIn(absent_cat, series.categories)
            for b in series.bins:
                self.assertEqual(b.counts.get(absent_cat, 0), 0)


# ---------------------------------------------------------------------------
# Date filtering: games with undateable dates are skipped
# ---------------------------------------------------------------------------

class TestDateFiltering(unittest.TestCase):

    def test_game_with_unknown_date_skipped(self):
        game = _make_game(white="Alice", black="Bob", date="????.??.??",
                          entries_per_path={"0": [_clamp_entry("C")]})
        result = aggregate([game], player="Alice")
        self.assertEqual(result, {})

    def test_game_with_partial_date_included(self):
        game = _make_game(white="Alice", black="Bob", date="2025.??.??",
                          entries_per_path={"0": [_clamp_entry("C")]})
        result = aggregate([game], player="Alice")
        self.assertIn("CLAMP", result)


# ---------------------------------------------------------------------------
# get_all_players
# ---------------------------------------------------------------------------

class TestGetAllPlayers(unittest.TestCase):

    def test_returns_sorted_unique_names(self):
        games = [
            _make_game(white="Alice", black="Carlos"),
            _make_game(white="Bob", black="Alice"),
        ]
        players = get_all_players(games)
        self.assertEqual(players, ["Alice", "Bob", "Carlos"])

    def test_empty_names_excluded(self):
        games = [_make_game(white="", black="Alice")]
        players = get_all_players(games)
        self.assertEqual(players, ["Alice"])

    def test_no_games_returns_empty(self):
        self.assertEqual(get_all_players([]), [])


# ---------------------------------------------------------------------------
# Binning mode routing (chart_cfg.ordinal_fallback_mode)
# ---------------------------------------------------------------------------

class TestBinningModeRouting(unittest.TestCase):
    """ordinal_fallback_mode in chart_cfg independently controls quantile vs equal_width."""

    def _make_games(self) -> list:
        """10 tagged games spread sparsely across a year — unequal-density distribution."""
        months = [1, 1, 1, 1, 1, 6, 7, 10, 11, 12]  # 5 in Jan, 5 spread
        games = []
        for month in months:
            g = _make_game(
                white="Alice", black="Bob",
                date=f"2026.{month:02d}.15",
                entries_per_path={"0": [_clamp_entry("C")]},
            )
            games.append(g)
        return games

    def test_quantile_mode_produces_equal_count_bins(self):
        games = self._make_games()
        cfg = {"target_progression_bins": 2, "ordinal_fallback_mode": "quantile",
               "min_games_per_ordinal_bin": 1, "max_ordinal_bins": 120}
        result = aggregate(games, player="Alice", chart_cfg=cfg)
        bins = result["CLAMP"].bins
        totals = [b.total for b in bins]
        # quantile splits evenly (within ±1) across N moments
        self.assertAlmostEqual(totals[0], totals[-1], delta=1)

    def test_equal_width_mode_places_bins_by_date_span(self):
        games = self._make_games()
        cfg = {"target_progression_bins": 2, "ordinal_fallback_mode": "equal_width",
               "min_games_per_ordinal_bin": 1, "max_ordinal_bins": 120}
        result = aggregate(games, player="Alice", chart_cfg=cfg)
        bins = result["CLAMP"].bins
        # equal_width splits the calendar; dense Jan cluster → all 5 Jan moments in bin 0
        totals = [b.total for b in bins]
        self.assertGreater(totals[0], totals[-1])

    def test_binning_mode_does_not_affect_series_rendering_fields(self):
        games = self._make_games()
        cfg = {"target_progression_bins": 2, "ordinal_fallback_mode": "quantile",
               "min_games_per_ordinal_bin": 1, "max_ordinal_bins": 120}
        result = aggregate(games, player="Alice", chart_cfg=cfg)
        series = result["CLAMP"]
        # Rendering fields are defaults — aggregate() doesn't set them
        self.assertEqual(series.x_axis_layout, "uniform_bins")
        self.assertEqual(series.max_gap_segment_days, 28)
        self.assertEqual(series.line_style, "smooth")
        self.assertAlmostEqual(series.smoothing_strength, 1.0)


# ---------------------------------------------------------------------------
# ChessLogPresetSeries rendering fields
# ---------------------------------------------------------------------------

class TestPresetSeriesRenderingFields(unittest.TestCase):
    """aggregate() leaves rendering fields at defaults; callers set them."""

    def _one_game_result(self):
        game = _make_game(
            white="Alice", black="Bob",
            date="2026.01.15",
            entries_per_path={"0": [_clamp_entry("C")]},
        )
        return aggregate([game], player="Alice")

    def test_default_x_axis_layout(self):
        result = self._one_game_result()
        self.assertEqual(result["CLAMP"].x_axis_layout, "uniform_bins")

    def test_default_max_gap_segment_days(self):
        result = self._one_game_result()
        self.assertEqual(result["CLAMP"].max_gap_segment_days, 28)

    def test_default_line_style(self):
        result = self._one_game_result()
        self.assertEqual(result["CLAMP"].line_style, "smooth")

    def test_default_smoothing_strength(self):
        result = self._one_game_result()
        self.assertAlmostEqual(result["CLAMP"].smoothing_strength, 1.0)

    def test_rendering_fields_are_mutable(self):
        result = self._one_game_result()
        series = result["CLAMP"]
        series.x_axis_layout = "gap_compressed"
        series.line_style = "straight"
        self.assertEqual(series.x_axis_layout, "gap_compressed")
        self.assertEqual(series.line_style, "straight")


if __name__ == "__main__":
    unittest.main()
