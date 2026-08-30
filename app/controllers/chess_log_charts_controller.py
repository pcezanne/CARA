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
from app.services.chess_log_narrative_service import generate_narrative
from app.services.chess_log_stats_service import ChessLogPresetSeries, aggregate, get_all_players
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
    """Run chess_log_stats_service.aggregate() off the UI thread."""

    charts_updated = pyqtSignal(object)    # Dict[str, ChessLogPresetSeries]
    charts_unavailable = pyqtSignal(str)   # reason string

    def __init__(
        self,
        games: List[GameData],
        player: str,
        color_filter: str,
        chart_cfg: Dict[str, Any],
        preset_orders: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        super().__init__()
        self._games = games
        self._player = player
        self._color_filter = color_filter
        self._chart_cfg = chart_cfg
        self._preset_orders = preset_orders or {}
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
    players_ready = pyqtSignal(list)       # List[str]
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
        self._get_selected_games_callback: Optional[Callable[[bool], List[GameData]]] = None

        self._dropdown_worker: Optional[ChessLogPlayerDropdownWorker] = None
        self._agg_worker: Optional[ChessLogAggregationWorker] = None
        self._narrative_thread: Optional[ChessLogNarrativeThread] = None

        self._selection_debounce = QTimer(self)
        self._selection_debounce.setSingleShot(True)
        self._selection_debounce.timeout.connect(self._on_selection_debounced)
        self._selection_debounce_ms = 100

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

    def is_ai_configured(self) -> bool:
        return resolve_default_provider(self._user_settings) is not None

    def set_source_selection(self, source: int) -> None:
        """Set the Data Source (0=None, 1=Active, 2=All, 3=SelectedActive, 4=SelectedAll)."""
        self._source_selection = source
        if source == 0:
            self._cancel_agg_worker()
            self.charts_unavailable.emit("no_source")
            return
        self._refresh_dropdown_and_charts()

    def set_player_selection(self, player: str) -> None:
        self._current_player = player or ""
        self._schedule_charts_refresh()

    def set_color_filter(self, color_filter: str) -> None:
        self._color_filter = color_filter
        self._schedule_charts_refresh()

    def notify_selection_changed(self) -> None:
        """Called when database table selection changes (sources 3/4 only)."""
        if self._source_selection not in (3, 4):
            return
        self._selection_debounce.stop()
        self._selection_debounce.start(self._selection_debounce_ms)

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

    def _on_selection_debounced(self) -> None:
        if self._source_selection not in (3, 4):
            return
        self._refresh_dropdown_and_charts()

    def _refresh_dropdown_and_charts(self) -> None:
        games = self._resolve_games()
        self._start_dropdown_worker(games)
        self._schedule_charts_refresh(games=games)

    def _schedule_charts_refresh(
        self, games: Optional[List[GameData]] = None
    ) -> None:
        if self._source_selection == 0:
            return
        if games is None:
            games = self._resolve_games()
        self._cancel_agg_worker()
        custom_cats = self._user_settings.get("chess_log", {}).get("custom_categories", [])
        preset_orders = {"Custom": list(custom_cats)} if custom_cats else {}
        worker = ChessLogAggregationWorker(
            games=games,
            player=self._current_player,
            color_filter=self._color_filter,
            chart_cfg=self._config,
            preset_orders=preset_orders,
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
