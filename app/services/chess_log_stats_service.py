"""Aggregation service for Chess Log charting.

Walks CARAChessLog payloads across a list of GameData objects, filters by
player and color, and produces per-preset binned time series ready for
ChessLogCategoryChartWidget.

Presets CLAMP, CCT, and Custom share the same {category + optional why}
entry shape, so one generic pipeline covers all three.  3x3 is excluded:
its Why1/2/3 entries aren't a comparable category axis.

Reuses from player_stats_service:
- _game_date_ordinal_for_trends   (date → ordinal with partial-date fallbacks)
- _ordinal_target_bin_count       (bin count from target_progression_bins config)
- _ordinal_fallback_mode          (quantile vs equal_width strategy)
- _calendar_bin_center_time_pct   (X-axis position for a bin's calendar range)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from app.models.database_model import GameData
from app.services.chess_log_storage_service import ChessLogStorageService
from app.utils.chess_log_color_scoping import color_from_path_key
from app.services.player_stats_service import (
    _calendar_bin_center_time_pct,
    _game_date_ordinal_for_trends,
    _ordinal_fallback_mode,
    _ordinal_target_bin_count,
)
from app.utils.chess_log_preset_order import CLAMP_ORDER, CCT_ORDER, order_categories

# Presets included in the charting pipeline
CHARTED_PRESETS: frozenset[str] = frozenset({"CLAMP", "CCT", "Custom"})

# Sentinel for uncategorized moments (cat="" from the zero-category-save feature)
UNCATEGORIZED: str = ""


@dataclass
class ChessLogCategoryBin:
    """One time bin's category-frequency counts for a single preset."""

    time_pct: float          # 0–100, X position on the chart
    total: int               # total moments in this bin
    lab0: str                # ISO date of the earliest game in the bin
    lab1: str                # ISO date of the latest game in the bin
    counts: Dict[str, int]   # category → moment count; "" key = uncategorized


@dataclass
class ChessLogPresetSeries:
    """Complete time-series data for one preset.

    Binning fields (set by aggregate):
        preset, categories, bins

    Rendering fields (set by ChessLogAggregationWorker after aggregate,
    threaded from controller's live instance fields):
        x_axis_layout, max_gap_segment_days, line_style, smoothing_strength
    """

    preset: str
    categories: List[str]             # canonical order per preset, then "" last
    bins: List[ChessLogCategoryBin]
    x_axis_layout: str = "uniform_bins"    # "uniform_bins" / "gap_compressed" / "calendar_linear"
    max_gap_segment_days: int = 28
    line_style: str = "smooth"             # "smooth" or "straight"
    smoothing_strength: float = 1.0
    t_min: Optional[int] = None           # day ordinal of the earliest game; None on legacy call sites
    t_max: Optional[int] = None           # day ordinal of the latest game


def aggregate(
    games: List[GameData],
    player: str,
    color_filter: str = "both",       # "white", "black", or "both"
    chart_cfg: Optional[Dict[str, Any]] = None,
    preset_orders: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, ChessLogPresetSeries]:
    """Aggregate Chess Log moments into per-preset time series.

    Args:
        games:         Games to scan (from Data Source selection).
        player:        Player name to scope to (case-insensitive). Empty string
                       skips player filtering — all moments in all games.
        color_filter:  "white" / "black" / "both" — further scope to games where
                       the player had that color.
        chart_cfg:     Optional config dict with ``target_progression_bins`` and
                       ``ordinal_fallback_mode`` (same keys as Player Stats).
                       Build via ``chart_cfg_with_chess_log_charts_overrides`` so
                       the user's ``target_bins`` and ``binning_mode`` are applied.
        preset_orders: Optional mapping of preset name → authoritative category
                       ordering. Used for the Custom preset (insertion order from
                       user settings); CLAMP/CCT use built-in canonical order.

    Returns:
        Dict mapping preset name → ChessLogPresetSeries, one entry per preset
        that has at least one moment in the filtered games. Empty if no data.
        Rendering fields (x_axis_layout, etc.) are at their defaults; the caller
        (ChessLogAggregationWorker) sets them from live controller fields before
        emitting.
    """
    chart_cfg = chart_cfg or {}
    preset_orders = preset_orders or {}
    player_cf = (player or "").casefold().strip()

    raw: List[Tuple[int, str, str]] = []  # (ordinal, preset, cat)

    for game in games:
        if not getattr(game, "has_chess_log_tags", False):
            continue

        ordinal = _game_date_ordinal_for_trends(game.date or "")
        if ordinal is None:
            continue

        if player_cf:
            white_cf = (game.white or "").casefold().strip()
            black_cf = (game.black or "").casefold().strip()
            is_white_player = player_cf == white_cf
            is_black_player = player_cf == black_cf
            if not (is_white_player or is_black_player):
                continue
            if color_filter == "white" and not is_white_player:
                continue
            if color_filter == "black" and not is_black_player:
                continue

        paths_data = ChessLogStorageService.load_tags(game)
        for entries in paths_data.values():
            for entry in entries:
                preset = entry.get("preset", "")
                if preset not in CHARTED_PRESETS:
                    continue
                cat = entry.get("cat", "")
                raw.append((ordinal, preset, cat))

    if not raw:
        return {}

    result: Dict[str, ChessLogPresetSeries] = {}
    presets_in_data: Set[str] = {r[1] for r in raw}

    for preset in sorted(presets_in_data):
        samples = [(o, c) for o, p, c in raw if p == preset]
        custom_order = preset_orders.get(preset)
        result[preset] = _bin_preset(preset, samples, chart_cfg, custom_order)

    return result


def get_all_players(games: List[GameData]) -> List[Tuple[str, int]]:
    """Return (name, tagged_game_count) for players with >= 2 games sharing the same preset.

    A player qualifies when any single preset (CLAMP, CCT, 3x3, Custom) has at
    least 2 games where that player personally tagged moments with that preset.
    Requiring 2 of the same type prevents a 1-CLAMP + 1-3x3 combination from
    surfacing a player who has no useful data for any chart or narrative.

    The count shown in the dropdown is the total across all presets (not the
    per-preset maximum) so it reflects how many games the player has tagged overall.

    Only games where the player's OWN COLOR has at least one tagged path are
    credited — this avoids crediting both players equally for a game where only
    one side tagged moments.

    Cost: one ChessLogStorageService.load_tags() call per tagged game. Runs in
    a background worker; acceptable for typical datasets.
    """
    # per_preset_counts[player][preset] = number of games with that preset
    per_preset_counts: Dict[str, Dict[str, int]] = {}
    total_counts: Dict[str, int] = {}

    for game in games:
        if not getattr(game, "has_chess_log_tags", False):
            continue
        paths_data = ChessLogStorageService.load_tags(game)
        if not paths_data:
            continue

        # Determine which (color, preset) pairs appear in this game.
        color_preset_pairs: Set[Tuple[str, str]] = set()
        for path_key, entries in paths_data.items():
            color = color_from_path_key(path_key)
            if not color:
                continue
            for entry in entries:
                preset = entry.get("preset", "")
                if preset:
                    color_preset_pairs.add((color, preset))

        # Credit the player whose color appears, once per (player, preset) per game.
        seen_player_preset: Set[Tuple[str, str]] = set()
        for name, color in ((game.white, "white"), (game.black, "black")):
            if not (name and name.strip()):
                continue
            n = name.strip()
            for cp_color, preset in color_preset_pairs:
                if cp_color != color:
                    continue
                if (n, preset) not in seen_player_preset:
                    seen_player_preset.add((n, preset))
                    per_preset_counts.setdefault(n, {})
                    per_preset_counts[n][preset] = per_preset_counts[n].get(preset, 0) + 1
                    total_counts[n] = total_counts.get(n, 0) + 1

    qualified = [
        (name, total_counts[name])
        for name, preset_map in per_preset_counts.items()
        if any(count >= 2 for count in preset_map.values())
    ]
    qualified.sort(key=lambda x: (-x[1], x[0]))
    return qualified


def has_any_moments(
    games: List[GameData],
    player: str,
    color_filter: str = "both",
) -> bool:
    """Return True if any game has tagged moments for this player/color, any preset.

    Used by ChessLogAggregationWorker to distinguish 'moments exist but are not
    chartable (e.g. 3x3 only)' from 'truly no moments for this selection'.
    """
    player_cf = (player or "").casefold().strip()
    for game in games:
        if not getattr(game, "has_chess_log_tags", False):
            continue
        if player_cf:
            white_cf = (game.white or "").casefold().strip()
            black_cf = (game.black or "").casefold().strip()
            is_white = player_cf == white_cf
            is_black = player_cf == black_cf
            if not (is_white or is_black):
                continue
            if color_filter == "white" and not is_white:
                continue
            if color_filter == "black" and not is_black:
                continue
        paths_data = ChessLogStorageService.load_tags(game)
        if paths_data:
            return True
    return False


# ---------------------------------------------------------------------------
# Internal binning helpers
# ---------------------------------------------------------------------------

def _bin_preset(
    preset: str,
    samples: List[Tuple[int, str]],  # (ordinal, cat)
    chart_cfg: Dict[str, Any],
    custom_order: Optional[List[str]] = None,
) -> ChessLogPresetSeries:
    seed_cats: Set[str] = set(CLAMP_ORDER) if preset == "CLAMP" else (
        set(CCT_ORDER) if preset == "CCT" else set()
    )
    all_cats: Set[str] = seed_cats | {cat for _, cat in samples}
    categories = order_categories(preset, list(all_cats), custom_order=custom_order)

    ordinals = [o for o, _ in samples]
    t_min, t_max = min(ordinals), max(ordinals)
    n_bins = _ordinal_target_bin_count(chart_cfg, len(samples))
    mode = _ordinal_fallback_mode(chart_cfg)
    bins = (
        _count_bins_quantile(samples, n_bins, t_min, t_max)
        if mode == "quantile"
        else _count_bins_equal_width(samples, n_bins, t_min, t_max)
    )

    return ChessLogPresetSeries(preset=preset, categories=categories, bins=bins,
                               t_min=t_min, t_max=t_max)


def _make_bin(
    chunk: List[Tuple[int, str]],
    lo_o: int,
    hi_o: int,
    t_min: int,
    t_max: int,
) -> ChessLogCategoryBin:
    time_pct = _calendar_bin_center_time_pct(lo_o, hi_o, t_min, t_max)
    counts: Dict[str, int] = {}
    for _, cat in chunk:
        counts[cat] = counts.get(cat, 0) + 1
    return ChessLogCategoryBin(
        time_pct=time_pct,
        total=len(chunk),
        lab0=date.fromordinal(lo_o).isoformat(),
        lab1=date.fromordinal(hi_o).isoformat(),
        counts=counts,
    )


def _count_bins_equal_width(
    samples: List[Tuple[int, str]],
    n_bins: int,
    t_min: int,
    t_max: int,
) -> List[ChessLogCategoryBin]:
    days = t_max - t_min + 1
    if days <= 1 or t_max <= t_min:
        return [_make_bin(samples, t_min, t_max, t_min, t_max)]
    n_bins = max(2, min(n_bins, days))
    result: List[ChessLogCategoryBin] = []
    for b in range(n_bins):
        lo_o = t_min + (days * b) // n_bins
        hi_o = t_min + (days * (b + 1)) // n_bins - 1
        chunk = [(o, c) for o, c in samples if lo_o <= o <= hi_o]
        if not chunk:
            continue
        ords = [x[0] for x in chunk]
        result.append(_make_bin(chunk, min(ords), max(ords), t_min, t_max))
    result.sort(key=lambda b: b.time_pct)
    return result


def _count_bins_quantile(
    samples: List[Tuple[int, str]],
    n_bins: int,
    t_min: int,
    t_max: int,
) -> List[ChessLogCategoryBin]:
    sorted_s = sorted(samples, key=lambda x: x[0])
    n = len(sorted_s)
    if n == 0:
        return []
    n_bins = max(2, min(n_bins, n))
    result: List[ChessLogCategoryBin] = []
    for b in range(n_bins):
        lo_i = b * n // n_bins
        hi_i = (b + 1) * n // n_bins if b < n_bins - 1 else n
        chunk = sorted_s[lo_i:hi_i]
        if not chunk:
            continue
        ords = [x[0] for x in chunk]
        lo_o = max(min(ords), t_min)
        hi_o = min(max(ords), t_max)
        if lo_o > hi_o:
            lo_o, hi_o = hi_o, lo_o
        result.append(_make_bin(chunk, lo_o, hi_o, t_min, t_max))
    result.sort(key=lambda b: b.time_pct)
    return result
