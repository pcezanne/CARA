"""Controller for Chess Log — per-move player self-diagnosis tagging."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.controllers.game_controller import GameController
from app.services.chess_log_storage_service import ChessLogStorageService
from app.utils.pgn_variation_path import encode_path


class ChessLogController:
    """Controller for Chess Log tagging.

    Maintains an in-memory cache of the current game's moments (paths_data)
    and writes them back to the PGN tag only on an explicit save gesture,
    matching the Annotations / Notes explicit-save convention.

    Lifecycle:
    - Instantiated by AppController alongside NotesController.
    - Connects to game_model.active_game_changed to reload cache on game switch.
    - Views call add_moment_at_active_path() on user action, then
      save_tags_for_current_game() via the Chess Log menu or Ctrl+Alt+L.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        game_controller: GameController,
        database_controller=None,
        user_settings_service=None,
    ) -> None:
        self.config = config
        self._game_controller = game_controller
        self._database_controller = database_controller
        self._user_settings_service = user_settings_service
        self._cached_paths_data: Dict[str, List[Dict[str, Any]]] = {}
        self._cached_game_id: Optional[int] = None

        game_model = game_controller.get_game_model()
        game_model.active_game_changed.connect(self._on_active_game_changed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_active_preset(self) -> str:
        """Return the currently active Chess Log preset name (e.g. 'CLAMP')."""
        if self._user_settings_service is None:
            return "CLAMP"
        return self._user_settings_service.get_chess_log().get("active_preset", "CLAMP")

    def get_custom_categories(self) -> List[str]:
        """Return the user-defined Custom picklist categories."""
        if self._user_settings_service is None:
            return []
        cats = self._user_settings_service.get_chess_log().get("custom_categories", [])
        return list(cats) if isinstance(cats, list) else []

    def get_tags_for_current_game(self) -> Dict[str, List[Dict[str, Any]]]:
        """Return in-memory moments for the active game (loading from PGN if needed)."""
        game = self._game_controller.get_game_model().active_game
        if game is None:
            return {}
        if game.game_number != self._cached_game_id:
            self._load_into_cache(game)
        return self._cached_paths_data

    def get_entries_at_active_path(self) -> List[Dict[str, Any]]:
        """Return the entries stored at the current active path, or [] if none."""
        data = self.get_tags_for_current_game()
        path_key = encode_path(self._game_controller.get_game_model().get_active_path())
        return list(data.get(path_key, []))

    def add_moment_at_active_path(
        self,
        entries: List[Dict[str, Any]],
        parent_widget=None,
    ) -> bool:
        """Append one or more entries as a single moment at the active path.

        Args:
            entries: One or more {preset, cat, why, ...} dicts, all for the same
                     moment.  CCT with two letters = two entries, still one moment.
            parent_widget: Qt parent for the confirmation dialog (may be None).

        Returns:
            True if the moment was added; False if the user declined confirmation
            or there was nothing to add.
        """
        if not entries:
            return False
        game = self._game_controller.get_game_model().active_game
        if game is None:
            return False
        if game.game_number != self._cached_game_id:
            self._load_into_cache(game)

        path_key = encode_path(self._game_controller.get_game_model().get_active_path())
        is_new_moment = path_key not in self._cached_paths_data or not self._cached_paths_data[path_key]
        current_count = ChessLogStorageService.count_tags(self._cached_paths_data)

        if is_new_moment and current_count >= 3:
            if not self._confirm_extra_moment(parent_widget):
                return False

        tagged = [ChessLogStorageService.make_entry(e["preset"], e["cat"], e.get("why", "")) for e in entries]
        preset_of_new = tagged[0].get("preset") if tagged else None
        if path_key in self._cached_paths_data:
            if preset_of_new:
                kept = [e for e in self._cached_paths_data[path_key] if e.get("preset") != preset_of_new]
                self._cached_paths_data[path_key] = kept + tagged
            else:
                self._cached_paths_data[path_key].extend(tagged)
        else:
            self._cached_paths_data[path_key] = tagged
        return True

    def save_tags_for_current_game(self) -> bool:
        """Persist the in-memory cache to the active game's PGN tag."""
        game = self._game_controller.get_game_model().active_game
        if game is None:
            return False
        ok = ChessLogStorageService.store_tags(game, self._cached_paths_data, self.config)
        if ok:
            self._game_controller.get_game_model().metadata_updated.emit()
            self._mark_database_unsaved(game)
        return ok

    def clear_tags_for_current_game(self) -> bool:
        """Clear all moments for the active game (in-memory; needs save to persist)."""
        game = self._game_controller.get_game_model().active_game
        if game is None:
            return False
        self._cached_paths_data = {}
        ok = ChessLogStorageService.clear_tags(game)
        if ok:
            self._game_controller.get_game_model().metadata_updated.emit()
            self._mark_database_unsaved(game)
        return ok

    def has_unsaved_changes(self) -> bool:
        """Return True if in-memory cache differs from what's stored in the PGN."""
        game = self._game_controller.get_game_model().active_game
        if game is None:
            return False
        stored = ChessLogStorageService.load_tags(game)
        return self._cached_paths_data != stored

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _on_active_game_changed(self, game) -> None:
        """Reload cache when the active game changes."""
        if game is None:
            self._cached_paths_data = {}
            self._cached_game_id = None
        else:
            self._load_into_cache(game)

    def _load_into_cache(self, game) -> None:
        self._cached_paths_data = ChessLogStorageService.load_tags(game)
        self._cached_game_id = game.game_number

    def _mark_database_unsaved(self, game) -> None:
        if self._database_controller is None or game is None:
            return
        try:
            db_model = self._database_controller.find_database_model_for_game(game)
            if db_model:
                self._database_controller.mark_database_unsaved(db_model)
        except Exception:
            pass

    def _confirm_extra_moment(self, parent_widget=None) -> bool:
        """Show the 4th-moment 'Are you sure?' confirmation dialog."""
        try:
            from app.views.dialogs.confirmation_dialog import ConfirmationDialog
            return ConfirmationDialog.show_confirmation(
                self.config,
                "Chess Log — More than three moments?",
                "You already have three tagged moments in this game. "
                "Studer's 3×3 method suggests focusing on at most three — "
                "piling on more can dilute the lesson rather than sharpen it.\n\n"
                "Add this moment anyway?",
                parent_widget,
            )
        except Exception:
            return True
