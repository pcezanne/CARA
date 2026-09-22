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

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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
from app.services.chess_log_stats_service import (
    ChessLogPresetSeries,
    aggregate,
    get_all_players,
    has_any_moments,
)
from app.services.user_settings_service import UserSettingsService
from app.utils.ai_provider_config import resolve_default_provider


class ChessLogPlayerDropdownWorker(QThread):
    """Populate the player dropdown from the current game set."""

    players_ready = pyqtSignal(list)   # List[Tuple[str, int]]

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
            with QMutexLocker(self._mutex):
                if self._cancelled:
                    return
            if has_any_moments(self._games, self._player, self._color_filter):
                self.charts_unavailable.emit("no_chartable_preset")
            else:
                self.charts_unavailable.emit("no_data")


class ChessLogShallowThread(QThread):
    """Classify why-notes as SHALLOW or DEEP off the UI thread."""

    shallow_ready = pyqtSignal(object)   # Set[Tuple[int, str, str]]
    shallow_failed = pyqtSignal(str)     # error message

    def __init__(
        self,
        games: List[GameData],
        provider: str,
        model: str,
        api_key: str,
        base_url_override: Optional[str],
        config: Optional[Dict[str, Any]],
        timeout_seconds: int,
        notes: List[Tuple[int, int, str, str, str]],  # (idx, game_number, path_key, preset, why)
    ) -> None:
        super().__init__()
        self._games = games
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self._base_url_override = base_url_override
        self._config = config
        self._timeout_seconds = timeout_seconds
        self._notes = notes
        self._cancelled = False
        self._mutex = QMutex()

    def cancel(self) -> None:
        with QMutexLocker(self._mutex):
            self._cancelled = True

    def run(self) -> None:
        with QMutexLocker(self._mutex):
            if self._cancelled:
                return
        from app.services.ai_service import AIService
        notes_text = "\n".join(f"{i}: {why}" for (i, _gn, _pk, _pr, why) in self._notes)
        prompt = (
            "Classify each of these player self-notes as SHALLOW or DEEP.\n\n"
            "SHALLOW = only reports the outcome, the move played, or what's objectively\n"
            "wrong with the position — a label or a fact about the board, not an\n"
            "explanation of the player's own thinking\n"
            "(e.g. \"I blundered\", \"missed it\", \"this hangs my Rook for a Bishop\",\n"
            "\"there was a discovered attack on my Queen that I missed\").\n\n"
            "DEEP = explains why the PLAYER made the move or missed the better one —\n"
            "what they were thinking, focused on, or misjudging. Naming what's wrong\n"
            "with the position or the resulting tactic (a fork, a discovered attack, a\n"
            "weak rank) is NOT enough on its own — the note has to say something about\n"
            "the player's own reasoning or mental error, even if brief or tentative.\n\n"
            "A DEEP note doesn't need an explicit causal word like \"because\" — connecting\n"
            "two facts is enough. \"I saw the free rook\" next to \"missed the mate\" already\n"
            "explains the distraction that caused the miss.\n\n"
            "Examples of DEEP:\n"
            "- \"I went to kick their Knight not seeing my Bishop was hanging.\" (explains\n"
            "  what distracted them)\n"
            "- \"This is a calculation error, 2 attackers, one defender.\" (attributes\n"
            "  the mistake to a specific miscount, not just stating the position)\n"
            "- \"I think I played a3 to protect it from capture.\" (states own intent,\n"
            "  even tentatively)\n"
            "- \"I needed to get on the same file as the Queen to force it away.\"\n"
            "  (explains the missed plan)\n\n"
            "Examples of SHALLOW:\n"
            "- \"This hangs my Rook for a Bishop.\"\n"
            "- \"There was a discovered attack on my Queen that I missed.\"\n"
            "- \"I moved my queen into a forking square with my King.\"\n"
            "- \"This is a passive move, permitting my opponent to play Rc2, putting\n"
            "  their rook on a very powerful rank.\"\n"
            "- \"It appears that the engine wants to make sure they don't have a bishop\n"
            "  pair, but that's a guess.\" (explains the engine's logic, not the\n"
            "  player's own reasoning)\n\n"
            "Return one line per note: <index>: SHALLOW or <index>: DEEP.\n\n"
            f"{notes_text}"
        )
        service = AIService(config=self._config)
        messages = [{"role": "user", "content": prompt}]
        success, response = service.send_message(
            provider=self._provider,
            model=self._model,
            api_key=self._api_key,
            messages=messages,
            base_url_override=self._base_url_override,
            timeout_seconds=self._timeout_seconds,
        )
        with QMutexLocker(self._mutex):
            if self._cancelled:
                return
        if not success:
            self.shallow_failed.emit(response or "Classification failed.")
            return
        shallow: Set[Tuple[int, str, str]] = set()
        for line in response.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            try:
                idx = int(parts[0].strip())
            except ValueError:
                continue
            if parts[1].strip().upper() == "SHALLOW" and 0 <= idx < len(self._notes):
                _, gn, pk, pr, _ = self._notes[idx]
                shallow.add((gn, pk, pr))
        self.shallow_ready.emit(shallow)


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
        timeout_seconds: int = 60,
        token_limit: Optional[int] = None,
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
        self._timeout_seconds = timeout_seconds
        self._token_limit = token_limit
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
            timeout_seconds=self._timeout_seconds,
            token_limit=self._token_limit,
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
    players_ready = pyqtSignal(list)       # List[Tuple[str, int]]
    player_selection_cleared = pyqtSignal()  # view should reset player combo to unselected
    narrative_ready = pyqtSignal(str, list)
    narrative_failed = pyqtSignal(str)
    shallow_ready = pyqtSignal(object)   # Set[Tuple[int, str, str]]
    shallow_failed = pyqtSignal(str)
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
        self._target_bins: int = _charts_defaults["target_progression_bins"]
        self._binning_mode: str = _charts_defaults["ordinal_fallback_mode"]
        self._x_axis_layout: str = _charts_defaults["progression_x_axis_mode"]
        self._max_gap_segment_days: int = _charts_defaults["compress_gap_max_segment_days"]
        self._line_style: str = _charts_defaults["progression_line_style"]
        self._smoothing_strength: float = _charts_defaults["progression_line_smooth_strength"]

        self._dropdown_worker: Optional[ChessLogPlayerDropdownWorker] = None
        self._agg_worker: Optional[ChessLogAggregationWorker] = None
        self._narrative_thread: Optional[ChessLogNarrativeThread] = None
        self._shallow_thread: Optional[ChessLogShallowThread] = None

        # Narrative-panel ephemeral settings (not persisted except timeout).
        self._narrative_token_limit: int = 12000
        self._narrative_model_override: Optional[str] = None
        self._chess_log_controller: Optional[Any] = None

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

    def set_chess_log_controller(self, controller: Any) -> None:
        """Inject ChessLogController for Chess Log dialogs."""
        self._chess_log_controller = controller

    def get_chess_log_controller(self) -> Optional[Any]:
        """Return the injected ChessLogController."""
        return self._chess_log_controller

    def resolve_games(self) -> List[GameData]:
        """Public wrapper around _resolve_games()."""
        return self._resolve_games()

    def notify_chess_log_saved(self) -> None:
        """Re-run the player dropdown worker after Chess Log tags have been saved.

        Must be called after any successful Chess Log save so that the tagged-game
        counts in the player combo stay current.  Only refreshes the dropdown;
        does not re-run chart aggregation (the chart data is still valid).
        """
        if self._source_selection == 0:
            return
        self._start_dropdown_worker(self._resolve_games())

    def has_player_selected(self) -> bool:
        """True iff the user has explicitly picked a player in the Player dropdown."""
        return self._player_explicit_selected

    def get_tags_for_game(self, game: GameData) -> Dict[str, Any]:
        """Return Chess Log moments for *game* (delegates to ChessLogController)."""
        if self._chess_log_controller is None:
            from app.services.chess_log_storage_service import ChessLogStorageService
            return ChessLogStorageService.load_tags(game)
        return self._chess_log_controller.get_tags_for_game(game)

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
        self._target_bins = charts["target_progression_bins"]
        self._binning_mode = charts["ordinal_fallback_mode"]
        self._x_axis_layout = charts["progression_x_axis_mode"]
        self._max_gap_segment_days = charts["compress_gap_max_segment_days"]
        self._line_style = charts["progression_line_style"]
        self._smoothing_strength = charts["progression_line_smooth_strength"]

        new = (
            self._target_bins, self._binning_mode, self._x_axis_layout,
            self._max_gap_segment_days, self._line_style, self._smoothing_strength,
        )
        if old != new:
            self._selection_debounce.stop()
            self._selection_debounce.start(self._selection_debounce_ms)

    def is_ai_configured(self) -> bool:
        return resolve_default_provider(self._user_settings) is not None

    # --- narrative panel controls ---

    def get_narrative_timeout_seconds(self) -> int:
        """Return the shared AI Summary timeout (persisted in user_settings)."""
        return int(self._user_settings.get("ai_summary", {}).get("request_timeout_seconds", 60))

    def set_narrative_timeout_seconds(self, seconds: int) -> None:
        """Persist the timeout to the shared ai_summary.request_timeout_seconds key."""
        try:
            UserSettingsService.get_instance().update_ai_summary_settings(
                {"request_timeout_seconds": seconds}
            )
        except Exception:
            pass
        self._user_settings.setdefault("ai_summary", {})["request_timeout_seconds"] = seconds

    def set_narrative_token_limit(self, limit: int) -> None:
        self._narrative_token_limit = limit

    def set_narrative_model_override(self, model: Optional[str]) -> None:
        """Set a specific model to use for narrative generation (None = provider default)."""
        self._narrative_model_override = model or None

    def get_available_models(self) -> List[str]:
        """Return model IDs available for the active provider (same filtering as AI Summary)."""
        ai_settings = self._user_settings.get("ai_models", {})
        ai_summary = self._user_settings.get("ai_summary", {})
        use_openai = bool(ai_summary.get("use_openai_models", True))
        use_anthropic = bool(ai_summary.get("use_anthropic_models", False))
        use_custom = bool(ai_summary.get("use_custom_models", False))
        if sum([use_openai, use_anthropic, use_custom]) != 1:
            use_openai, use_anthropic, use_custom = True, False, False

        if use_openai:
            s = ai_settings.get("openai", {})
            if s.get("api_key"):
                return list(s.get("models", []) or [])
        if use_anthropic:
            s = ai_settings.get("anthropic", {})
            if s.get("api_key"):
                return list(s.get("models", []) or [])
        if use_custom:
            s = ai_settings.get("custom", {})
            if s.get("enabled", False) and (s.get("base_url") or "").strip():
                return list(s.get("models", []) or [])
        return []

    def get_default_narrative_model(self) -> Optional[str]:
        """Return the default model ID for the active provider, or None if unconfigured."""
        provider_tuple = resolve_default_provider(self._user_settings)
        return provider_tuple[1] if provider_tuple else None

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
        if self._source_selection == 0:
            self.narrative_failed.emit("Please select a Data Source first.")
            return
        if not self._current_player:
            self.narrative_failed.emit("Please select a player first.")
            return
        provider_tuple = resolve_default_provider(self._user_settings)
        if not provider_tuple:
            self.narrative_failed.emit("No AI provider configured.")
            return
        provider, default_model, api_key, base_url = provider_tuple
        model = self._narrative_model_override or default_model
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
            timeout_seconds=self.get_narrative_timeout_seconds(),
            token_limit=self._narrative_token_limit,
        )
        thread.narrative_ready.connect(self.narrative_ready)
        thread.narrative_failed.connect(self.narrative_failed)
        thread.finished.connect(self._on_narrative_finished)
        self._narrative_thread = thread
        thread.start()

    def request_flag_shallow_notes(self) -> None:
        """Start shallow-note classification off the UI thread.

        Gathers all non-empty why-notes from games in scope, then spawns
        ChessLogShallowThread. On completion, emits ``shallow_ready`` with the
        set of (game_number, path_key, preset) keys whose notes were judged
        SHALLOW, and writes is_shallow onto each affected entry in the cache.
        Emits ``shallow_failed`` on error.
        """
        provider_tuple = resolve_default_provider(self._user_settings)
        if not provider_tuple:
            self.shallow_failed.emit("No AI provider configured.")
            return
        provider, default_model, api_key, base_url = provider_tuple
        model = self._narrative_model_override or default_model

        games = self._resolve_games()
        # (idx, game_number, path_key, preset, why) — skip ignore_shallow entries
        notes: List[Tuple[int, int, str, str, str]] = []
        for game in games:
            tags = self.get_tags_for_game(game)
            for path_key, entries in tags.items():
                if not entries:
                    continue
                by_preset: Dict[str, list] = {}
                for entry in entries:
                    p = entry.get("preset", "")
                    by_preset.setdefault(p, []).append(entry)
                for preset, preset_entries in by_preset.items():
                    for entry in preset_entries:
                        if entry.get("ignore_shallow"):
                            continue
                        why = (entry.get("why") or "").strip()
                        if why:
                            notes.append((len(notes), game.game_number, path_key, preset, why))

        if not notes:
            self.shallow_ready.emit(set())
            return

        self._cancel_shallow_thread()
        thread = ChessLogShallowThread(
            games=games,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url_override=base_url,
            config=self._config,
            timeout_seconds=self.get_narrative_timeout_seconds(),
            notes=notes,
        )
        thread.shallow_ready.connect(self._on_shallow_thread_ready)
        thread.shallow_failed.connect(self._on_shallow_thread_failed)
        thread.finished.connect(self._on_shallow_thread_finished)
        self._shallow_thread = thread
        thread.start()

    def _on_shallow_thread_ready(self, shallow_keys: Set[Tuple[int, str, str]]) -> None:
        """Write is_shallow onto every in-scope entry (full sync), then re-emit."""
        games = self._resolve_games()
        for game in games:
            tags = self.get_tags_for_game(game)
            for path_key, entries in list(tags.items()):
                if not entries:
                    continue
                by_preset: Dict[str, list] = {}
                for entry in entries:
                    by_preset.setdefault(entry.get("preset", ""), []).append(entry)
                for preset, preset_entries in by_preset.items():
                    key = (game.game_number, path_key, preset)
                    flag = key in shallow_keys
                    updated = [dict(e, is_shallow=flag) if flag else
                               {k: v for k, v in e.items() if k != "is_shallow"}
                               for e in preset_entries]
                    if self._chess_log_controller is not None:
                        self._chess_log_controller.replace_entries_at_path_for_game(
                            game, path_key, preset, updated
                        )
        self.shallow_ready.emit(shallow_keys)

    def _on_shallow_thread_failed(self, message: str) -> None:
        self.shallow_failed.emit(message)

    def _cancel_shallow_thread(self) -> None:
        if self._shallow_thread:
            try:
                if self._shallow_thread.isRunning():
                    self._shallow_thread.cancel()
                    self._shallow_thread.finished.disconnect()
                    self._shallow_thread = None
                    return
                self._shallow_thread.finished.disconnect()
            except RuntimeError:
                pass
            self._shallow_thread = None

    def _on_shallow_thread_finished(self) -> None:
        try:
            if self._shallow_thread:
                self._shallow_thread.finished.disconnect()
        except RuntimeError:
            pass
        self._shallow_thread = None

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
        chart_cfg = chart_cfg_with_chess_log_charts_overrides(
            self._config, self._target_bins, self._binning_mode
        )
        worker = ChessLogAggregationWorker(
            games=games,
            player=self._current_player,
            color_filter=self._color_filter,
            chart_cfg=chart_cfg,
            preset_orders={},
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

    def get_current_source_filenames(self) -> List[str]:
        """Return display names of the databases backing the current source selection."""
        if self._source_selection == 0:
            return []
        if self._source_selection == 1:
            db = self._database_controller.get_active_database()
            return [db.display_name] if db else []
        if self._source_selection == 2:
            panel = self._database_controller.get_panel_model()
            if not panel:
                return []
            return [db.display_name for db in panel.get_all_database_models()]
        if self._source_selection == 3:
            db = self._database_controller.get_active_database()
            return [db.display_name] if db else []
        if self._source_selection == 4:
            panel = self._database_controller.get_panel_model()
            if not panel:
                return []
            return [db.display_name for db in panel.get_all_database_models()]
        return []

    def _persist_chart_settings(self) -> None:
        try:
            UserSettingsService.get_instance().update_chess_log_settings({
                "charts": {
                    "target_progression_bins": self._target_bins,
                    "ordinal_fallback_mode": self._binning_mode,
                    "progression_x_axis_mode": self._x_axis_layout,
                    "compress_gap_max_segment_days": self._max_gap_segment_days,
                    "progression_line_style": self._line_style,
                    "progression_line_smooth_strength": self._smoothing_strength,
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
