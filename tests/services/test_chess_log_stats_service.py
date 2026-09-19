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
    has_any_moments,
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
            },
        )

    def test_two_presets_produce_two_series(self):
        result = aggregate([self._mixed_game()], player="Alice")
        self.assertIn("CLAMP", result)
        self.assertIn("CCT", result)
        self.assertEqual(len(result), 2)

    def test_presets_not_mixed(self):
        result = aggregate([self._mixed_game()], player="Alice")
        clamp_cats = set().union(*(b.counts.keys() for b in result["CLAMP"].bins))
        cct_cats = set().union(*(b.counts.keys() for b in result["CCT"].bins))
        self.assertNotIn("Checks", clamp_cats)
        self.assertNotIn("C", cct_cats)

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
    """get_all_players mirrors Player Stats: threshold >= 2 tagged games, sort by count desc then name.

    Path key conventions (from pgn_variation_path.py):
      "0"   → length 1 (odd)  → White just moved
      "0.0" → length 2 (even) → Black just moved
    """

    # White's move tagged, Black's move tagged, or both.
    _WHITE_TAG = {"0": [_clamp_entry("C")]}
    _BLACK_TAG = {"0.0": [_clamp_entry("C")]}
    _BOTH_TAG  = {"0": [_clamp_entry("C")], "0.0": [_clamp_entry("C")]}

    def _white_tagged(self, white="Alice", black="Bob", date="2025.01.15"):
        """Game where only White's move is tagged."""
        return _make_game(white=white, black=black, date=date, entries_per_path=self._WHITE_TAG)

    def _black_tagged(self, white="Alice", black="Bob", date="2025.01.15"):
        """Game where only Black's move is tagged."""
        return _make_game(white=white, black=black, date=date, entries_per_path=self._BLACK_TAG)

    def _both_tagged(self, white="Alice", black="Bob", date="2025.01.15"):
        """Game where both colors have tagged moves."""
        return _make_game(white=white, black=black, date=date, entries_per_path=self._BOTH_TAG)

    def _untagged(self, white="Alice", black="Bob", date="2025.01.15"):
        return _make_game(white=white, black=black, date=date)

    def _names(self, games):
        return [name for name, _ in get_all_players(games)]

    # --- per-color correctness (the bug being fixed) ---

    def test_only_white_tagged_credits_white_not_black(self):
        # NotThePainter (White) tags their own moves; kpepin (Black) tags nothing.
        games = [
            self._white_tagged("NotThePainter", "kpepin", "2025.01.01"),
            self._white_tagged("NotThePainter", "kpepin", "2025.02.01"),
        ]
        names = self._names(games)
        self.assertIn("NotThePainter", names)
        self.assertNotIn("kpepin", names)  # kpepin's moves were never tagged

    def test_only_black_tagged_credits_black_not_white(self):
        games = [
            self._black_tagged("Alice", "Bob", "2025.01.01"),
            self._black_tagged("Alice", "Bob", "2025.02.01"),
        ]
        names = self._names(games)
        self.assertIn("Bob", names)
        self.assertNotIn("Alice", names)

    def test_both_colors_tagged_credits_both(self):
        games = [
            self._both_tagged("Alice", "Bob", "2025.01.01"),
            self._both_tagged("Alice", "Bob", "2025.02.01"),
        ]
        names = self._names(games)
        self.assertIn("Alice", names)
        self.assertIn("Bob", names)

    def test_untagged_game_credits_neither(self):
        games = [self._untagged("Alice", "Bob")] * 5
        self.assertEqual(get_all_players(games), [])

    # --- threshold filter ---

    def test_player_with_one_tagged_game_excluded(self):
        games = [self._white_tagged("Alice", "Bob")]
        self.assertNotIn("Alice", self._names(games))

    def test_player_with_two_tagged_games_included(self):
        games = [
            self._white_tagged("Alice", "Opp1", "2025.01.01"),
            self._white_tagged("Alice", "Opp2", "2025.02.01"),
        ]
        self.assertIn("Alice", self._names(games))

    def test_untagged_games_do_not_count_toward_threshold(self):
        # 1 white-tagged + 1 untagged → still only 1 qualifying → excluded
        games = [
            self._white_tagged("Alice", "Bob", "2025.01.01"),
            self._untagged("Alice", "Carlos", "2025.02.01"),
        ]
        self.assertNotIn("Alice", self._names(games))

    def test_empty_names_excluded(self):
        # White name is empty; only Alice (Black) has tagged moves
        games = [
            self._black_tagged(white="", black="Alice", date="2025.01.01"),
            self._black_tagged(white="", black="Alice", date="2025.02.01"),
        ]
        self.assertNotIn("", self._names(games))
        self.assertIn("Alice", self._names(games))

    def test_no_games_returns_empty(self):
        self.assertEqual(get_all_players([]), [])

    def test_returns_tuples_of_name_and_count(self):
        games = [
            self._white_tagged("Alice", "Opp1", "2025.01.01"),
            self._white_tagged("Alice", "Opp2", "2025.02.01"),
        ]
        result = get_all_players(games)
        self.assertEqual(result[0], ("Alice", 2))

    # --- sort order ---

    def test_sorted_by_count_descending(self):
        # Alice (White) has 3 tagged games; Bob (White) has 2.
        games = [
            self._white_tagged("Alice", "Opp1", "2025.01.01"),
            self._white_tagged("Alice", "Opp2", "2025.02.01"),
            self._white_tagged("Alice", "Opp3", "2025.03.01"),
            self._white_tagged("Bob", "Opp4", "2025.04.01"),
            self._white_tagged("Bob", "Opp5", "2025.05.01"),
        ]
        names = self._names(games)
        self.assertEqual(names.index("Alice"), 0)
        self.assertEqual(names.index("Bob"), 1)

    def test_ties_broken_by_name_ascending(self):
        games = [
            self._white_tagged("Alice", "Opp1", "2025.01.01"),
            self._white_tagged("Alice", "Opp2", "2025.02.01"),
            self._white_tagged("Carlos", "Opp3", "2025.03.01"),
            self._white_tagged("Carlos", "Opp4", "2025.04.01"),
        ]
        names = self._names(games)
        self.assertLess(names.index("Alice"), names.index("Carlos"))

    def test_3x3_only_player_with_two_games_qualifies(self):
        """A player with 2 games tagged using 3x3 must appear in the dropdown."""
        entry = ChessLogStorageService.make_entry("3x3", "Why1", "I attacked too early")
        g1 = _make_game(white="Alice", black="Bob", date="2025.01.01",
                        entries_per_path={"0": [entry]})
        entry2 = ChessLogStorageService.make_entry("3x3", "Why2", "It lost a tempo")
        g2 = _make_game(white="Alice", black="Bob", date="2025.02.01",
                        entries_per_path={"0": [entry2]})
        names = self._names([g1, g2])
        self.assertIn("Alice", names)

    def test_mixed_preset_one_each_does_not_qualify(self):
        """1 CLAMP game + 1 3x3 game = no single preset reaches threshold of 2."""
        clamp_entry = _clamp_entry("C")
        threex_entry = ChessLogStorageService.make_entry("3x3", "Why1", "text")
        g1 = _make_game(white="Alice", black="Bob", date="2025.01.01",
                        entries_per_path={"0": [clamp_entry]})
        g2 = _make_game(white="Alice", black="Bob", date="2025.02.01",
                        entries_per_path={"0": [threex_entry]})
        names = self._names([g1, g2])
        self.assertNotIn("Alice", names)

    def test_mixed_preset_two_clamp_plus_one_3x3_qualifies(self):
        """2 CLAMP + 1 3x3 — CLAMP reaches threshold so player qualifies."""
        clamp_entry = _clamp_entry("C")
        threex_entry = ChessLogStorageService.make_entry("3x3", "Why1", "text")
        g1 = _make_game(white="Alice", black="Bob", date="2025.01.01",
                        entries_per_path={"0": [clamp_entry]})
        g2 = _make_game(white="Alice", black="Bob", date="2025.02.01",
                        entries_per_path={"0": [clamp_entry]})
        g3 = _make_game(white="Alice", black="Bob", date="2025.03.01",
                        entries_per_path={"0": [threex_entry]})
        names = self._names([g1, g2, g3])
        self.assertIn("Alice", names)


# ---------------------------------------------------------------------------
# has_any_moments
# ---------------------------------------------------------------------------

class TestHasAnyMoments(unittest.TestCase):

    def test_returns_true_for_3x3_only_data(self):
        entry = ChessLogStorageService.make_entry("3x3", "Why1", "text")
        game = _make_game(white="Alice", black="Bob", date="2025.01.01",
                          entries_per_path={"0": [entry]})
        self.assertTrue(has_any_moments([game], player="Alice"))

    def test_returns_true_for_clamp_data(self):
        game = _make_game(white="Alice", black="Bob", date="2025.01.01",
                          entries_per_path={"0": [_clamp_entry("C")]})
        self.assertTrue(has_any_moments([game], player="Alice"))

    def test_returns_false_for_no_tagged_games(self):
        game = _make_game(white="Alice", black="Bob", date="2025.01.01")
        self.assertFalse(has_any_moments([game], player="Alice"))

    def test_returns_false_for_wrong_player(self):
        entry = ChessLogStorageService.make_entry("3x3", "Why1", "text")
        game = _make_game(white="Alice", black="Bob", date="2025.01.01",
                          entries_per_path={"0": [entry]})
        self.assertFalse(has_any_moments([game], player="Carlos"))

    def test_empty_player_matches_all(self):
        entry = ChessLogStorageService.make_entry("3x3", "Why1", "text")
        game = _make_game(white="Alice", black="Bob", date="2025.01.01",
                          entries_per_path={"0": [entry]})
        self.assertTrue(has_any_moments([game], player=""))


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


class TestCalendarLinearTimePct(unittest.TestCase):
    """Regression: time_pct must be calendar-proportional, not bin-rank-based.

    Root cause of the Calendar Linear == Uniform Bins visual bug: if time_pct
    were based on bin index rather than actual calendar position, switching from
    Uniform Bins to Calendar Linear would produce an identical rendering.

    Tests pass chart_cfg with min_games_per_ordinal_bin=1 so that 10 test games
    produce 10 bins (one per game) rather than 3 (the default min_per=3 collapses
    sparse test data and can produce bins that straddle the April-July gap).
    """

    _CHART_CFG = {
        "target_progression_bins": 10,
        "min_games_per_ordinal_bin": 1,
        "max_ordinal_bins": 120,
        "ordinal_fallback_mode": "quantile",
    }

    def _gappy_games(self) -> list:
        """5 moments in April 2026, 5 in July 2026, nothing in May/June."""
        games = []
        april_dates = ["2026.04.01", "2026.04.08", "2026.04.15", "2026.04.22", "2026.04.29"]
        july_dates  = ["2026.07.01", "2026.07.08", "2026.07.15", "2026.07.22", "2026.07.29"]
        for d in april_dates + july_dates:
            games.append(_make_game(
                white="Alice", black="Bob", date=d,
                entries_per_path={"0": [_clamp_entry("C")]},
            ))
        return games

    def test_april_bins_have_low_time_pct(self):
        result = aggregate(self._gappy_games(), player="Alice", chart_cfg=self._CHART_CFG)
        bins = result["CLAMP"].bins
        april_bins = [b for b in bins if b.lab0 < "2026-05"]
        self.assertTrue(len(april_bins) > 0)
        for b in april_bins:
            self.assertLess(b.time_pct, 30.0, f"April bin has time_pct={b.time_pct:.1f}%, expected < 30%")

    def test_july_bins_have_high_time_pct(self):
        result = aggregate(self._gappy_games(), player="Alice", chart_cfg=self._CHART_CFG)
        bins = result["CLAMP"].bins
        july_bins = [b for b in bins if b.lab0 >= "2026-07"]
        self.assertTrue(len(july_bins) > 0)
        for b in july_bins:
            self.assertGreater(b.time_pct, 70.0, f"July bin has time_pct={b.time_pct:.1f}%, expected > 70%")

    def test_large_gap_in_time_pct_between_clusters(self):
        """The gap between last April bin and first July bin must exceed 50pp."""
        result = aggregate(self._gappy_games(), player="Alice", chart_cfg=self._CHART_CFG)
        bins = sorted(result["CLAMP"].bins, key=lambda b: b.time_pct)
        april_bins = [b for b in bins if b.lab0 < "2026-05"]
        july_bins  = [b for b in bins if b.lab0 >= "2026-07"]
        self.assertTrue(april_bins and july_bins)
        last_april_pct = max(b.time_pct for b in april_bins)
        first_july_pct = min(b.time_pct for b in july_bins)
        gap = first_july_pct - last_april_pct
        self.assertGreater(gap, 50.0, f"Gap between clusters is only {gap:.1f}pp — time_pct may be rank-based")

    def test_time_pct_not_evenly_spaced(self):
        """time_pct values must NOT be uniformly distributed for gappy data."""
        result = aggregate(self._gappy_games(), player="Alice", chart_cfg=self._CHART_CFG)
        bins = sorted(result["CLAMP"].bins, key=lambda b: b.time_pct)
        pcts = [b.time_pct for b in bins]
        gaps = [pcts[i + 1] - pcts[i] for i in range(len(pcts) - 1)]
        max_gap = max(gaps)
        avg_gap = sum(gaps) / len(gaps)
        # Calendar-proportional data has a large gap (May/June) relative to average spacing
        self.assertGreater(
            max_gap, avg_gap * 3,
            f"Max inter-bin gap ({max_gap:.1f}pp) not >> avg ({avg_gap:.1f}pp) — may be evenly spaced"
        )


# ---------------------------------------------------------------------------
# ChessLogPresetSeries t_min / t_max date extent (Commit 1 — calendar axis)
# ---------------------------------------------------------------------------

class TestSeriesDateExtent(unittest.TestCase):
    """aggregate() populates t_min/t_max with the raw ordinal range."""

    def _games_with_dates(self, dates: list[str]) -> list:
        return [
            _make_game(
                white="Alice", black="Bob",
                date=d.replace("-", "."),
                entries_per_path={"0": [_clamp_entry("C")]},
            )
            for d in dates
        ]

    def test_single_game_t_min_equals_t_max(self):
        from datetime import date
        games = self._games_with_dates(["2026-06-15"])
        result = aggregate(games, player="Alice")
        series = result["CLAMP"]
        expected = date.fromisoformat("2026-06-15").toordinal()
        self.assertEqual(series.t_min, expected)
        self.assertEqual(series.t_max, expected)

    def test_t_min_is_earliest_game_ordinal(self):
        from datetime import date
        games = self._games_with_dates(["2026-04-01", "2026-07-15", "2026-12-31"])
        result = aggregate(games, player="Alice")
        series = result["CLAMP"]
        self.assertEqual(series.t_min, date.fromisoformat("2026-04-01").toordinal())

    def test_t_max_is_latest_game_ordinal(self):
        from datetime import date
        games = self._games_with_dates(["2026-04-01", "2026-07-15", "2026-12-31"])
        result = aggregate(games, player="Alice")
        series = result["CLAMP"]
        self.assertEqual(series.t_max, date.fromisoformat("2026-12-31").toordinal())

    def test_t_min_t_max_independent_of_binning_mode(self):
        from datetime import date
        dates = ["2026-01-01", "2026-01-15", "2026-06-01", "2026-12-31"]
        games = self._games_with_dates(dates)
        cfg_q = {"ordinal_fallback_mode": "quantile", "target_progression_bins": 2,
                 "min_games_per_ordinal_bin": 1, "max_ordinal_bins": 120}
        cfg_e = {"ordinal_fallback_mode": "equal_width", "target_progression_bins": 2,
                 "min_games_per_ordinal_bin": 1, "max_ordinal_bins": 120}
        r_q = aggregate(games, player="Alice", chart_cfg=cfg_q)
        r_e = aggregate(games, player="Alice", chart_cfg=cfg_e)
        self.assertEqual(r_q["CLAMP"].t_min, r_e["CLAMP"].t_min)
        self.assertEqual(r_q["CLAMP"].t_max, r_e["CLAMP"].t_max)
        self.assertEqual(r_q["CLAMP"].t_min, date.fromisoformat("2026-01-01").toordinal())
        self.assertEqual(r_q["CLAMP"].t_max, date.fromisoformat("2026-12-31").toordinal())

    def test_equal_width_skipped_bins_do_not_affect_t_min_t_max(self):
        """equal_width may skip empty bins; t_min/t_max must still be the raw data extremes."""
        from datetime import date
        dates = ["2026-01-01", "2026-12-31"]
        games = self._games_with_dates(dates)
        cfg = {"ordinal_fallback_mode": "equal_width", "target_progression_bins": 10,
               "min_games_per_ordinal_bin": 1, "max_ordinal_bins": 120}
        result = aggregate(games, player="Alice", chart_cfg=cfg)
        series = result["CLAMP"]
        self.assertEqual(series.t_min, date.fromisoformat("2026-01-01").toordinal())
        self.assertEqual(series.t_max, date.fromisoformat("2026-12-31").toordinal())


if __name__ == "__main__":
    unittest.main()
