"""User overrides for Chess Log Charts binning and rendering (persisted in user settings)."""

from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_CHESS_LOG_CHARTS: Dict[str, Any] = {
    "target_bins": 16,
    "binning_mode": "quantile",
    "x_axis_layout": "uniform_bins",
    "max_gap_segment_days": 28,
    "line_style": "smooth",
    "smoothing_strength": 1.0,
}

CHOICES_TARGET_BINS: tuple = (8, 12, 16, 24, 32)
CHOICES_BINNING_MODE: tuple = ("quantile", "equal_width")
CHOICES_X_AXIS_LAYOUT: tuple = ("uniform_bins", "gap_compressed", "calendar_linear")
CHOICES_MAX_GAP_SEGMENT_DAYS: tuple = (14, 28, 50, 100)
CHOICES_LINE_STYLE: tuple = ("smooth", "straight")
CHOICES_SMOOTHING_STRENGTH: tuple = (0.5, 1.0, 1.5, 2.0)


def normalize_chess_log_charts_settings(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a full Chess Log Charts settings dict with invalid values dropped and defaults filled.

    Migration: if the old ``x_axis_mode`` key is present it is converted to the nearest
    ``x_axis_layout`` equivalent ("game_count" → "uniform_bins", "time" → "calendar_linear")
    and then discarded so subsequent saves use the new schema.
    """
    out = dict(DEFAULT_CHESS_LOG_CHARTS)
    if not raw or not isinstance(raw, dict):
        return out

    # --- migration from the old two-value x_axis_mode ---
    if "x_axis_mode" in raw and "x_axis_layout" not in raw:
        legacy = str(raw.get("x_axis_mode", "")).strip().lower()
        if legacy == "game_count":
            out["x_axis_layout"] = "uniform_bins"
        else:
            out["x_axis_layout"] = "calendar_linear"

    if raw.get("target_bins") in CHOICES_TARGET_BINS:
        out["target_bins"] = int(raw["target_bins"])

    bm = str(raw.get("binning_mode", "")).strip().lower()
    if bm in CHOICES_BINNING_MODE:
        out["binning_mode"] = bm

    xl = str(raw.get("x_axis_layout", "")).strip().lower()
    if xl in CHOICES_X_AXIS_LAYOUT:
        out["x_axis_layout"] = xl

    if raw.get("max_gap_segment_days") in CHOICES_MAX_GAP_SEGMENT_DAYS:
        out["max_gap_segment_days"] = int(raw["max_gap_segment_days"])

    ls = str(raw.get("line_style", "")).strip().lower()
    if ls in CHOICES_LINE_STYLE:
        out["line_style"] = ls

    if raw.get("smoothing_strength") in CHOICES_SMOOTHING_STRENGTH:
        out["smoothing_strength"] = float(raw["smoothing_strength"])

    return out


def chart_cfg_with_chess_log_charts_overrides(
    app_config: Optional[Dict[str, Any]],
    target_bins: int,
    binning_mode: str = "quantile",
) -> Dict[str, Any]:
    """Build a chart_cfg dict for chess_log_stats_service.aggregate() with user overrides applied.

    Extracts the player_stats.time_series block from app_config (for min_games_per_ordinal_bin,
    max_ordinal_bins, etc.) and overrides target_progression_bins and ordinal_fallback_mode with
    the caller's already-resolved values so player_stats_service helpers read the right values.
    """
    ts_block: Dict[str, Any] = (
        (app_config or {})
        .get("ui", {})
        .get("panels", {})
        .get("detail", {})
        .get("player_stats", {})
        .get("time_series", {})
    )
    cfg = dict(ts_block)
    cfg["target_progression_bins"] = target_bins
    cfg["ordinal_fallback_mode"] = binning_mode
    return cfg
