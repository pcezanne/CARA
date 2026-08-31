"""Controller for Chess Log Charts tab (§5.1 + §5.2).

Owns Data Source + Player selection state, three worker threads:
  - ChessLogPlayerDropdownWorker — populates player dropdown from selected games
  - ChessLogAggregationWorker   — runs chess_log_stats_service.aggregate()
  - ChessLogNarrativeThread     — runs chess_log_narrative_service.generate_narrative()

Mirrors the selection/callback injection pattern from PlayerStatsController
(set_get_selected_games_callback, notify_selection_changed) for consistent
wiring in AppController / MainWindow.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QMutex, QMutexLocker, QObject, QThread, QTimer, pyqtSignal

from app.models.database_model import GameData
from app.services.chess_log_charts_user import (
    CHOICES_BINNING_MODE,
    CHOICES_LINE_STYLE,
    CHOICES_MAX_GAP_SEGMENT_DAYS,
    CHOICES_SMOOTHING_STRENGTH,
    CHOICES_TARGET_BINS,
    CHOICES_X_AXIS_LAYOUT,
    chart_cfg_with_chess_log_charts_overrides,
    normalize_chess_log_charts_settings,
)
from app.services.chess_log_narrative_service import generate_narrative
from app.services.chess_log_stats_service import ChessLogPresetSeries, aggregate, get_all_players
from app.services.user_settings_service import UserSettingsService
from app.utils.ai_provider_config import resolve_default_provider


class ChessLogPlayerDropdownWorker(QThread):
    """Populate the player dropdown from the current game set."""

    players_ready = pyqtSignal(list)   # List[str]

    def __init__(self, games: List[GameData]) -> None:
        super().__init__()
        self._games = games
        self._cancelled = False
        self._mutex = QMutex()

    def cancel(self) -> None:
        with QMutexLocker(self._mutex):
            self._cancelled = True

    def run(self) -> None:
        with QMutexLocker(self._mutex):
            if self._cancelled:
                return
        players = get_all_players(self._games)
        with QMutexLocker(self._mutex):
            if not self._cancelled:
                self.players_ready.emit(players)


class ChessLogAggregationWorker(QThread):
    """Run chess_log_stats_service.aggregate() off the UI thread.

    Rendering-only fields (x_axis_layout, max_gap_segment_days, line_style,
    smoothing_strength) are stamped onto every ChessLogPresetSeries returned
    by aggregate() before the result is emitted, so the widget can read them
    directly from the series without knowing controller state.
    """

    charts_updated = pyqtSignal(object)    # Dict[str, ChessLogPresetSeries]
    charts_unavailable = pyqtSignal(str)   # reason string

    def __init__(
        self,
        games: List[GameData],
        player: str,
        color_filter: str,
        chart_cfg: Dict[str, Any],
        preset_orders: Optional[Dict[str, List[str]]] = None,
        x_axis_layout: str = "uniform_bins",
        max_gap_segment_days: int = 28,
        line_style: str = "smooth",
        smoothing_strength: float = 1.0,
    ) -> None:
        super().__init__()
        self._games = games
        self._player = player
        self._color_filter = color_filter
        self._chart_cfg = chart_cfg
        self._preset_orders = preset_orders or {}
        self._x_axis_layout = x_axis_layout
        self._max_gap_segment_days = max_gap_segment_days
        self._line_style = line_style
        self._smoothing_strength = smoothing_strength
        self._cancelled = False
        self._mutex = QMutex()

    def cancel(self) -> None:
        with QMutexLocker(self._mutex):
            self._cancelled = True

    def run(self) -> None:
        with QMutexLocker(self._mutex):
            if self._cancelled:
                return
        try:
            result = aggregate(
                self._games,
                player=self._player,
                color_filter=self._color_filter,
                chart_cfg=self._chart_cfg,
                preset_orders=self._preset_orders,
            )
        except Exception as exc:
            with QMutexLocker(self._mutex):
                if not self._cancelled:
                    self.charts_unavailable.emit(str(exc))
            return
        with QMutexLocker(self._mutex):
            if self._cancelled:
                return
        if result:
            # Stamp rendering fields onto each series before emit.
            for series in result.values():
                series.x_axis_layout = self._x_axis_layout
                series.max_gap_segment_days = self._max_gap_segment_days
                series.line_style = self._line_style
                series.smoothing_strength = self._smoothing_strength
            self.charts_updated.emit(result)
        else:
            self.charts_unavailable.emit("no_data")


class ChessLogNarrativeThread(QThread):
    """Run chess_log_narrative_service.generate_narrative() off the UI thread."""

    narrative_ready = pyqtSignal(str, list)   # narrative_text, shallow_flags
    narrative_failed = pyqtSignal(str)        # error message

    def __init__(
        self,
        games: List[GameData],
        provider: str,
        model: str,
        api_key: str,
        base_url_override: Optional[str],
        player: str,
        color_filter: str,
        config: Optional[Dict[str, Any]],
    ) -> None:
        super().__init__()
        self._games = games
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self._base_url_override = base_url_override
        self._player = player
        self._color_filter = color_filter
        self._config = config
        self._cancelled = False
        self._mutex = QMutex()

    def cancel(self) -> None:
        with QMutexLocker(self._mutex):
            self._cancelled = True

    def run(self) -> None:
        with QMutexLocker(self._mutex):
            if self._cancelled:
                return
        success, text, flags = generate_narrative(
            games=self._games,
            provider=self._provider,
            model=self._model,
            api_key=self._api_key,
            base_url_override=self._base_url_override,
            player=self._player,
            color_filter=self._color_filter,
            config=self._config,
        )
        with QMutexLocker(self._mutex):
            if self._cancelled:
                return
        if success:
            self.narrative_ready.emit(text, flags)
        else:
            self.narrative_failed.emit(text)


class ChessLogChartsController(QObject):
    """Controller for the Chess Log Charts detail tab."""

    charts_updated = pyqtSignal(object)    # Dict[str, ChessLogPresetSeries]
    charts_unavailable = pyqtSignal(str)   # reason ("no_source", "no_player", "no_data", ...)
    charts_loading = pyqtSignal()          # aggregation worker about to start; view should clear stale chart
    players_ready = pyqtSignal(list)       # List[str]
    player_selection_cleared = pyqtSignal()  # view should reset player combo to unselected
    narrative_ready = pyqtSignal(str, list)
    narrative_failed = pyqtSignal(str)
    ai_configured_changed = pyqtSignal(bool)  # True when LLM becomes available or unavailable

    def __init__(
        self,
        config: Dict[str, Any],
        database_controller: Any,
    ) -> None:
        super().__init__()
        self._config = config
        self._database_controller = database_controller
        self._user_settings: Dict[str, Any] = {}

        self._source_selection: int = 0   # 0=None, 1=Active, 2=All, 3=SelectedActive, 4=SelectedAll
        self._current_player: str = ""
        self._color_filter: str = "both"
        self._player_explicit_selected: bool = False
        self._get_selected_games_callback: Optional[Callable[[bool], List[GameData]]] = None

        _charts_defaults = normalize_chess_log_charts_settings({})
        self._target_bins: int = _charts_defaults["target_bins"]
        self._binning_mode: str = _charts_defaults["binning_mode"]
        self._x_axis_layout: str = _charts_defaults["x_axis_layout"]
        self._max_gap_segment_days: int = _charts_defaults["max_gap_segment_days"]
        self._line_style: str = _charts_defaults["line_style"]
        self._smoothing_strength: float = _charts_defaults["smoothing_strength"]

        self._dropdown_worker: Optional[ChessLogPlayerDropdownWorker] = None
        self._agg_worker: Optional[ChessLogAggregationWorker] = None
        self._narrative_thread: Optional[ChessLogNarrativeThread] = None

        self._selection_debounce = QTimer(self)
        self._selection_debounce.setSingleShot(True)
        self._selection_debounce.timeout.connect(self._on_selection_debounced)
        self._selection_debounce_ms = 100

        self._connect_to_database_panel_model()

    # ------------------------------------------------------------------
    # Public API — called by AppController / MainWindow
    # ------------------------------------------------------------------

    def set_get_selected_games_callback(
        self, callback: Optional[Callable[[bool], List[GameData]]]
    ) -> None:
        self._get_selected_games_callback = callback

    def set_user_settings(self, user_settings: Dict[str, Any]) -> None:
        """Refresh user settings (e.g. after AI Model Settings dialog closes)."""
        was_configured = resolve_default_provider(self._user_settings) is not None
        self._user_settings = user_settings
        is_configured = resolve_default_provider(self._user_settings) is not None
        if was_configured != is_configured:
            self.ai_configured_changed.emit(is_configured)

        old = (
            self._target_bins, self._binning_mode, self._x_axis_layout,
            self._max_gap_segment_days, self._line_style, self._smoothing_strength,
        )
        charts = normalize_chess_log_charts_settings(
            user_settings.get("chess_log", {}).get("charts", {})
        )
        self._target_bins = charts["target_bins"]
        self._binning_mode = charts["binning_mode"]
        self._x_axis_layout = charts["x_axis_layout"]
        self._max_gap_segment_days = charts["max_gap_segment_days"]
        self._line_style = charts["line_style"]
        self._smoothing_strength = charts["smoothing_strength"]

        new = (
            self._target_bins, self._binning_mode, self._x_axis_layout,
            self._max_gap_segment_days, self._line_style, self._smoothing_strength,
        )
        if old != new:
            self._selection_debounce.stop()
            self._selection_debounce.start(self._selection_debounce_ms)

    def is_ai_configured(self) -> bool:
        return resolve_default_provider(self._user_settings) is not None

    # --- getters ---

    def get_target_bins(self) -> int:
        return self._target_bins

    def get_binning_mode(self) -> str:
        return self._binning_mode

    def get_x_axis_layout(self) -> str:
        return self._x_axis_layout

    def get_max_gap_segment_days(self) -> int:
        return self._max_gap_segment_days

    def get_line_style(self) -> str:
        return self._line_style

    def get_smoothing_strength(self) -> float:
        return self._smoothing_strength

    # --- setters (menu-driven) ---

    def set_target_bins(self, n: int) -> None:
        if n not in CHOICES_TARGET_BINS:
            return
        self._target_bins = n
        self._persist_chart_settings()
        self._kick_debounce()

    def set_binning_mode(self, mode: str) -> None:
        if mode not in CHOICES_BINNING_MODE:
            return
        self._binning_mode = mode
        self._persist_chart_settings()
        self._kick_debounce()

    def set_x_axis_layout(self, layout: str) -> None:
        if layout not in CHOICES_X_AXIS_LAYOUT:
            return
        self._x_axis_layout = layout
        self._persist_chart_settings()
        self._kick_debounce()

    def set_max_gap_segment_days(self, days: int) -> None:
        if days not in CHOICES_MAX_GAP_SEGMENT_DAYS:
            return
        self._max_gap_segment_days = days
        self._persist_chart_settings()
        self._kick_debounce()

    def set_line_style(self, style: str) -> None:
        if style not in CHOICES_LINE_STYLE:
            return
        self._line_style = style
        self._persist_chart_settings()
        self._kick_debounce()

    def set_smoothing_strength(self, strength: float) -> None:
        if strength not in CHOICES_SMOOTHING_STRENGTH:
            return
        self._smoothing_strength = strength
        self._persist_chart_settings()
        self._kick_debounce()

    def set_source_selection(self, source: int) -> None:
        """Set the Data Source (0=None, 1=Active, 2=All, 3=SelectedActive, 4=SelectedAll)."""
        self._source_selection = source
        self._player_explicit_selected = False
        if source == 0:
            self._cancel_agg_worker()
            self.charts_unavailable.emit("no_source")
            return
        # Refresh the player dropdown but hold off on aggregation until the
        # user explicitly picks a player.
        games = self._resolve_games()
        self._start_dropdown_worker(games)
        self.charts_unavailable.emit("no_player")

    def set_player_selection(self, player: str) -> None:
        self._current_player = player or ""
        self._player_explicit_selected = True
        self._kick_debounce()

    def set_color_filter(self, color_filter: str) -> None:
        self._color_filter = color_filter
        self._kick_debounce()

    def notify_selection_changed(self) -> None:
        """Called when database table selection changes (sources 3/4 only)."""
        if self._source_selection not in (3, 4):
            return
        self._kick_debounce()

    def request_narrative(self) -> None:
        """Start the narrative generation worker (idempotent: cancels running thread)."""
        provider_tuple = resolve_default_provider(self._user_settings)
        if not provider_tuple:
            self.narrative_failed.emit("No AI provider configured.")
            return
        provider, model, api_key, base_url = provider_tuple
        games = self._resolve_games()
        if not games:
            self.narrative_failed.emit("No games in scope.")
            return
        self._cancel_narrative_thread()
        thread = ChessLogNarrativeThread(
            games=games,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url_override=base_url,
            player=self._current_player,
            color_filter=self._color_filter,
            config=self._config,
        )
        thread.narrative_ready.connect(self.narrative_ready)
        thread.narrative_failed.connect(self.narrative_failed)
        thread.finished.connect(self._on_narrative_finished)
        self._narrative_thread = thread
        thread.start()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _kick_debounce(self) -> None:
        self._selection_debounce.stop()
        self._selection_debounce.start(self._selection_debounce_ms)

    def _on_selection_debounced(self) -> None:
        if self._source_selection == 0:
            return
        if not self._player_explicit_selected:
            self.charts_unavailable.emit("no_player")
            return
        if self._source_selection in (3, 4):
            self._refresh_dropdown_and_charts()
        else:
            self._schedule_charts_refresh()

    def _refresh_dropdown_and_charts(self) -> None:
        games = self._resolve_games()
        self._start_dropdown_worker(games)
        self._schedule_charts_refresh(games=games)

    def _schedule_charts_refresh(
        self, games: Optional[List[GameData]] = None
    ) -> None:
        if self._source_selection == 0:
            return
        self.charts_loading.emit()
        if games is None:
            games = self._resolve_games()
        self._cancel_agg_worker()
        custom_cats = self._user_settings.get("chess_log", {}).get("custom_categories", [])
        preset_orders = {"Custom": list(custom_cats)} if custom_cats else {}
        chart_cfg = chart_cfg_with_chess_log_charts_overrides(
            self._config, self._target_bins, self._binning_mode
        )
        worker = ChessLogAggregationWorker(
            games=games,
            player=self._current_player,
            color_filter=self._color_filter,
            chart_cfg=chart_cfg,
            preset_orders=preset_orders,
            x_axis_layout=self._x_axis_layout,
            max_gap_segment_days=self._max_gap_segment_days,
            line_style=self._line_style,
            smoothing_strength=self._smoothing_strength,
        )
        worker.charts_updated.connect(self.charts_updated)
        worker.charts_unavailable.connect(self.charts_unavailable)
        worker.finished.connect(self._on_agg_worker_finished)
        self._agg_worker = worker
        worker.start()

    def _start_dropdown_worker(self, games: List[GameData]) -> None:
        self._cancel_dropdown_worker()
        worker = ChessLogPlayerDropdownWorker(games=games)
        worker.players_ready.connect(self._on_players_ready)
        worker.finished.connect(self._on_dropdown_worker_finished)
        self._dropdown_worker = worker
        worker.start()

    def _on_players_ready(self, players: List[str]) -> None:
        self.players_ready.emit(players)

    def _resolve_games(self) -> List[GameData]:
        if self._source_selection == 0:
            return []
        if self._source_selection == 1:
            db = self._database_controller.get_active_database()
            return db.get_all_games() if db else []
        if self._source_selection == 2:
            panel = self._database_controller.get_panel_model()
            if not panel:
                return []
            result: List[GameData] = []
            for db in panel.get_all_database_models():
                result.extend(db.get_all_games())
            return result
        if self._source_selection in (3, 4) and self._get_selected_games_callback:
            try:
                active_only = self._source_selection == 3
                raw = self._get_selected_games_callback(active_only)
                return list(raw) if raw else []
            except Exception:
                return []
        return []

    def _persist_chart_settings(self) -> None:
        try:
            UserSettingsService.get_instance().update_chess_log_settings({
                "charts": {
                    "target_bins": self._target_bins,
                    "binning_mode": self._binning_mode,
                    "x_axis_layout": self._x_axis_layout,
                    "max_gap_segment_days": self._max_gap_segment_days,
                    "line_style": self._line_style,
                    "smoothing_strength": self._smoothing_strength,
                }
            })
        except Exception:
            pass

    def _cancel_agg_worker(self) -> None:
        if self._agg_worker:
            try:
                if self._agg_worker.isRunning():
                    self._agg_worker.cancel()
                    self._agg_worker.finished.disconnect()
                    self._agg_worker = None
                    return
                self._agg_worker.finished.disconnect()
            except RuntimeError:
                pass
            self._agg_worker = None

    def _cancel_dropdown_worker(self) -> None:
        if self._dropdown_worker:
            try:
                if self._dropdown_worker.isRunning():
                    self._dropdown_worker.cancel()
                    self._dropdown_worker.finished.disconnect()
                    self._dropdown_worker = None
                    return
                self._dropdown_worker.finished.disconnect()
            except RuntimeError:
                pass
            self._dropdown_worker = None

    def _cancel_narrative_thread(self) -> None:
        if self._narrative_thread:
            try:
                if self._narrative_thread.isRunning():
                    self._narrative_thread.cancel()
                    self._narrative_thread.finished.disconnect()
                    self._narrative_thread = None
                    return
                self._narrative_thread.finished.disconnect()
            except RuntimeError:
                pass
            self._narrative_thread = None

    def _on_agg_worker_finished(self) -> None:
        try:
            if self._agg_worker:
                self._agg_worker.finished.disconnect()
        except RuntimeError:
            pass
        self._agg_worker = None

    def _on_dropdown_worker_finished(self) -> None:
        try:
            if self._dropdown_worker:
                self._dropdown_worker.finished.disconnect()
        except RuntimeError:
            pass
        self._dropdown_worker = None

    def _on_narrative_finished(self) -> None:
        try:
            if self._narrative_thread:
                self._narrative_thread.finished.disconnect()
        except RuntimeError:
            pass
        self._narrative_thread = None

    def _connect_to_database_panel_model(self) -> None:
        panel_model = self._database_controller.get_panel_model()
        if not panel_model:
            return
        try:
            panel_model.active_database_changed.disconnect(self._on_active_database_changed)
        except (RuntimeError, TypeError):
            pass
        panel_model.active_database_changed.connect(self._on_active_database_changed)

    def _on_active_database_changed(self, database) -> None:
        """Reset player selection when the active database changes (sources 1 and 2 only)."""
        if self._source_selection not in (1, 2):
            return
        self._cancel_agg_worker()
        self._player_explicit_selected = False
        self.player_selection_cleared.emit()
        games = self._resolve_games()
        self._start_dropdown_worker(games)
        self.charts_unavailable.emit("no_player")
