"""Controller for Chess Log — per-move player self-diagnosis tagging."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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

        # Multi-game cache for Tags Report and save-all.
        # Games not currently active live here; the active game lives in
        # _cached_paths_data / _cached_game_id.  Games move between stores on
        # active-game transitions — only one store ever owns a given game_number.
        self._multi_cache: Dict[int, Dict[str, List[Dict[str, Any]]]] = {}
        self._dirty_games: Dict[int, Any] = {}  # game_number -> GameData

        # Nag persistence: once the "more than three moments?" nag has been shown
        # for a game, it is suppressed for the rest of the session (global flag)
        # and for all future sessions for that specific game (per-game flag
        # persisted in the CARAChessLog payload).
        self._nag_shown_by_game: Dict[int, bool] = {}
        self._nag_shown_this_session: bool = False

        game_model = game_controller.get_game_model()
        game_model.active_game_changed.connect(self._on_active_game_changed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_active_preset(self) -> str:
        """Return the currently active Chess Log preset name (e.g. 'CLAMP')."""
        if self._user_settings_service is None:
            return "CLAMP"
        preset = self._user_settings_service.get_chess_log().get("active_preset", "CLAMP")
        return preset if preset in {"CLAMP", "CCT", "3x3"} else "CLAMP"

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
            parent_widget: Unused; kept for signature compatibility.

        Returns:
            True if the moment was added; False if there was nothing to add.
        """
        if not entries:
            return False
        game = self._game_controller.get_game_model().active_game
        if game is None:
            return False
        if game.game_number != self._cached_game_id:
            self._load_into_cache(game)

        path_key = encode_path(self._game_controller.get_game_model().get_active_path())
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
        ok = ChessLogStorageService.store_tags(
            game, self._cached_paths_data, self.config,
            nag_shown=self._nag_shown_by_game.get(self._cached_game_id, False),
        )
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
            # clear_tags writes the final state immediately, so nothing is left to
            # save for this game — remove it from _dirty_games to prevent
            # save_all_dirty_games from saving it again with empty data.
            self._dirty_games.pop(game.game_number, None)
            self._game_controller.get_game_model().metadata_updated.emit()
            self._mark_database_unsaved(game)
        return ok

    def game_has_any_tags(self) -> bool:
        """Return True if the current game has any tagged entries across any preset."""
        data = self.get_tags_for_current_game()
        return any(data.values())

    def replace_entries_at_path(
        self,
        path_key: str,
        preset: str,
        entries: List[Dict[str, Any]],
        view=None,
    ) -> None:
        """Replace all entries for *preset* at *path_key* in the in-memory cache.

        Analogous to add_moment_at_active_path but takes an explicit path_key
        instead of the game model's active path.  Only the named preset's entries
        at that path are replaced; other presets at the same path are preserved.
        In-memory only — call save_tags_for_current_game() to persist to PGN.
        """
        tagged = [
            ChessLogStorageService.make_entry(
                e["preset"], e["cat"], e.get("why", ""),
                ignore_shallow=bool(e.get("ignore_shallow")),
                is_shallow=bool(e.get("is_shallow")),
            )
            for e in entries
        ]
        if path_key in self._cached_paths_data:
            kept = [e for e in self._cached_paths_data[path_key] if e.get("preset") != preset]
            merged = kept + tagged
            if merged:
                self._cached_paths_data[path_key] = merged
            else:
                del self._cached_paths_data[path_key]
        elif tagged:
            self._cached_paths_data[path_key] = tagged

    def get_tags_for_game(self, game) -> Dict[str, List[Dict[str, Any]]]:
        """Return moments for any game, not just the active one.

        Checks the multi-cache first; falls back to disk.  The active game's
        moments are always read from the single-game cache to stay coherent with
        in-progress edits.
        """
        gid = game.game_number
        if gid == self._cached_game_id:
            return self._cached_paths_data
        if gid not in self._multi_cache:
            self._multi_cache[gid] = ChessLogStorageService.load_tags(game)
        return self._multi_cache[gid]

    def replace_entries_at_path_for_game(
        self,
        game,
        path_key: str,
        preset: str,
        entries: List[Dict[str, Any]],
    ) -> None:
        """Replace all entries for *preset* at *path_key* for any game.

        Writes to whichever store owns this game (single-game cache if it is
        the active game, multi-cache otherwise).  Marks the game dirty so
        save_all_dirty_games() will persist it later.
        """
        gid = game.game_number
        tagged = [
            ChessLogStorageService.make_entry(
                e["preset"], e["cat"], e.get("why", ""),
                ignore_shallow=bool(e.get("ignore_shallow")),
                is_shallow=bool(e.get("is_shallow")),
            )
            for e in entries
        ]
        if gid == self._cached_game_id:
            data = self._cached_paths_data
        else:
            if gid not in self._multi_cache:
                self._multi_cache[gid] = ChessLogStorageService.load_tags(game)
            data = self._multi_cache[gid]

        if path_key in data:
            kept = [e for e in data[path_key] if e.get("preset") != preset]
            merged = kept + tagged
            if merged:
                data[path_key] = merged
            else:
                del data[path_key]
        elif tagged:
            data[path_key] = tagged

        self._dirty_games[gid] = game

    def save_all_dirty_games(self) -> Tuple[int, int]:
        """Persist every dirty game via ChessLogStorageService.store_tags.

        Returns:
            (n_saved, n_failed)

        In addition to games tracked in _dirty_games (which covers edits made via
        ShowTagsDialog / ShowShallowTagsDialog), this also saves the active game's
        single-game cache when it has unsaved changes.  add_moment_at_active_path
        writes only to _cached_paths_data without touching _dirty_games, so without
        this check a Ctrl+Alt+Shift+L after tagging would silently skip the current game.
        """
        saved = failed = 0

        # Save the active game's single-game cache if it has unsaved changes and is
        # not already captured in _dirty_games (the loop below handles that case).
        current_game = self._game_controller.get_game_model().active_game
        if current_game is not None and current_game.game_number not in self._dirty_games:
            if self.has_unsaved_changes():
                ok = ChessLogStorageService.store_tags(
                    current_game, self._cached_paths_data, self.config,
                    nag_shown=self._nag_shown_by_game.get(self._cached_game_id, False),
                )
                if ok:
                    saved += 1
                    self._mark_database_unsaved(current_game)
                    self._game_controller.get_game_model().metadata_updated.emit()
                else:
                    failed += 1

        for gid, game in list(self._dirty_games.items()):
            data = (
                self._cached_paths_data
                if gid == self._cached_game_id
                else self._multi_cache.get(gid, {})
            )
            ok = ChessLogStorageService.store_tags(
                game, data, self.config,
                nag_shown=self._nag_shown_by_game.get(gid, False),
            )
            if ok:
                saved += 1
                self._mark_database_unsaved(game)
                self._dirty_games.pop(gid, None)
            else:
                failed += 1
        return saved, failed

    def has_dirty_games(self) -> bool:
        """Return True if any multi-game edits are pending a save."""
        return bool(self._dirty_games)

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
        """Reload cache when the active game changes.

        Rule B (deactivation): flush the outgoing active game into _multi_cache
        so edits made via the Tags Report survive the game switch.

        Rule A (activation): promote from _multi_cache if present, so edits to
        an inactive game made via the Tags Report are visible once it becomes active.
        """
        # Rule B — flush outgoing active game into multi-cache
        old_gid = self._cached_game_id
        if old_gid is not None and (self._cached_paths_data or old_gid in self._dirty_games):
            self._multi_cache[old_gid] = dict(self._cached_paths_data)

        if game is None:
            self._cached_paths_data = {}
            self._cached_game_id = None
        else:
            self._load_into_cache(game)

    def _load_into_cache(self, game) -> None:
        """Load *game* into the single-game cache.

        Rule A: check _multi_cache first so unsaved edits on an inactive game
        survive being made active.  Remove from _multi_cache once promoted
        (a game lives in exactly one store at a time).
        """
        gid = game.game_number
        if gid in self._multi_cache:
            self._cached_paths_data = self._multi_cache.pop(gid)
            # Keep any in-session nag flag set for this game; don't overwrite from disk.
        else:
            self._cached_paths_data = ChessLogStorageService.load_tags(game)
            self._nag_shown_by_game[gid] = ChessLogStorageService.load_nag_shown(game)
        self._cached_game_id = gid

    def _mark_database_unsaved(self, game) -> None:
        if self._database_controller is None or game is None:
            return
        try:
            db_model = self._database_controller.find_database_model_for_game(game)
            if db_model:
                self._database_controller.mark_database_unsaved(db_model)
        except Exception:
            pass

    def should_confirm_extra_moment(self, parent_widget=None) -> bool:
        """Return True if the caller should proceed with opening Tag This Moment.

        Returns False only when: the player is attempting to tag a *new* path,
        the current game already has >= 3 moments, the nag hasn't been shown yet
        for this game or this session, AND the user said "no" to the nag.

        Called by DetailMovesListView._on_tag_moment BEFORE opening MomentDialog
        so the user is asked before investing typing effort — not after.
        """
        game = self._game_controller.get_game_model().active_game
        if game is None:
            return True
        if game.game_number != self._cached_game_id:
            self._load_into_cache(game)
        path_key = encode_path(self._game_controller.get_game_model().get_active_path())
        is_new_moment = (
            path_key not in self._cached_paths_data
            or not self._cached_paths_data[path_key]
        )
        if not is_new_moment:
            return True
        if ChessLogStorageService.count_tags(self._cached_paths_data) < 3:
            return True
        gid = game.game_number
        if self._nag_shown_this_session:
            return True
        if self._nag_shown_by_game.get(gid, False):
            return True
        confirmed = self._confirm_extra_moment(parent_widget)
        # Suppress for the rest of this session and for this game's future sessions
        # regardless of whether the user said Yes or No — the nag fires at most once.
        self._nag_shown_by_game[gid] = True
        self._nag_shown_this_session = True
        return confirmed

    def _confirm_extra_moment(self, parent_widget=None) -> bool:
        """Show the 4th-moment 'Are you sure?' confirmation dialog."""
        try:
            from app.views.dialogs.confirmation_dialog import ConfirmationDialog
            return ConfirmationDialog.show_confirmation(
                self.config,
                "Chess Log — More than three moments?",
                "You already have three tagged moments in this game. "
                "Three tends to be the sweet spot — enough to see a pattern, "
                "few enough that each one still stands out when you review the "
                "game later. Piling on more can dilute the lesson rather than "
                "sharpen it.\n\n"
                "Add this moment anyway?",
                parent_widget,
            )
        except Exception:
            return True
