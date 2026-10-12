"""Service for storing and loading Chess Log moments in PGN tags."""

import json
import uuid
from typing import Dict, List, Optional, Any
from io import StringIO
from datetime import datetime, timezone

import chess.pgn

from app.models.database_model import GameData
from app.services.pgn_service import PgnService
from app.services.logging_service import LoggingService
from app.utils.pgn_tag_compression import (
    decode_and_decompress_to_str,
    compress_and_encode_from_str,
    compute_checksum,
)
from app.utils.pgn_variation_path import decode_path, node_at_path


class ChessLogStorageService:
    """Service for storing and loading Chess Log moments in PGN tags.

    Uses [CARAChessLog "..."] with gzip+base64 encoding,
    [CARAChessLogInfo "..."] for metadata, and [CARAChessLogChecksum "..."]
    for integrity verification — same pattern as CARAAnnotations / CARANotes.

    Storage schema (before compression):
        {"_v": 1, "paths": {path_key: [entry, ...]}, "nag_shown": true}

    "nag_shown" is omitted when False (backward-compatible; readers default to False
    via .get()).  It records that the user has already been shown the "more than three
    moments?" nag for this game so it is suppressed on future saves/sessions.

    One path key = one moment. A path's list may hold multiple entries so that
    a CCT tag with two letters (both apply to the same moment) costs one moment
    against the 3-moment cap, not two.  count_tags() counts paths, not entries.

    For 3x3 moments, cat is one of "Why1", "Why2", "Why3", "Why4" and why holds
    the answer text.  A single 3x3 moment stores up to four entries (one per Why
    answered), all sharing the same path key.  Insertion order is preserved by
    json.dumps/loads and Python dicts (3.7+), so Why1 always precedes Why2,
    Why3, and Why4 when loaded back.  preset="3x3" on all four entries.
    """

    TAG_NAME = "CARAChessLog"
    TAG_INFO = "CARAChessLogInfo"
    TAG_CHECKSUM = "CARAChessLogChecksum"

    @staticmethod
    def has_chess_log_tags(game: GameData) -> bool:
        """Return True if game has a CARAChessLog tag."""
        if game is None or not hasattr(game, "pgn") or game.pgn is None:
            return False
        try:
            chess_game = chess.pgn.read_game(StringIO(game.pgn))
            return chess_game is not None and ChessLogStorageService.TAG_NAME in chess_game.headers
        except Exception:
            return False

    @staticmethod
    def load_tags(game: GameData) -> Dict[str, List[Dict[str, Any]]]:
        """Load Chess Log moments from game PGN.

        Returns {path_key: [entry, ...]}. Returns {} on missing tag, checksum
        mismatch (also strips the corrupt tags), or any error.
        Sets game.has_chess_log_tags as a side effect.
        """
        if game is None:
            return {}
        if not hasattr(game, "pgn") or game.pgn is None:
            game.has_chess_log_tags = False
            return {}
        try:
            chess_game = chess.pgn.read_game(StringIO(game.pgn))
            if not chess_game or ChessLogStorageService.TAG_NAME not in chess_game.headers:
                game.has_chess_log_tags = False
                return {}
            encoded = chess_game.headers[ChessLogStorageService.TAG_NAME]
            json_text = decode_and_decompress_to_str(encoded)
            if ChessLogStorageService.TAG_CHECKSUM in chess_game.headers:
                stored = chess_game.headers[ChessLogStorageService.TAG_CHECKSUM]
                if compute_checksum(json_text.encode("utf-8")) != stored:
                    LoggingService.get_instance().warning(
                        "Chess Log checksum mismatch — removing corrupt tags."
                    )
                    ChessLogStorageService._remove_chess_log_tags(game)
                    game.has_chess_log_tags = False
                    return {}
            payload = json.loads(json_text)
            paths_data: Dict[str, List[Dict[str, Any]]] = payload.get("paths", {})
            game.has_chess_log_tags = ChessLogStorageService.count_tags(paths_data) > 0
            return paths_data
        except ValueError:
            ChessLogStorageService._remove_chess_log_tags(game)
            game.has_chess_log_tags = False
            return {}
        except Exception:
            game.has_chess_log_tags = False
            return {}

    @staticmethod
    def load_resolved_paths(game: GameData) -> Dict[str, List[Dict[str, Any]]]:
        """Load Chess Log moments, hiding path_keys that don't resolve in game's move tree.

        Returns only the path_keys whose decoded paths exist as nodes in the parsed
        chess_game.  Orphans are logged at WARNING and excluded from the returned dict,
        but they remain in the on-disk PGN (use load_tags for the byte-for-byte full
        dict).  This is the view consumed by all feature code; load_tags is the view
        used for save-time round-trip preservation.
        """
        full = ChessLogStorageService.load_tags(game)
        if not full:
            return full
        if not hasattr(game, "pgn") or not game.pgn:
            return full
        try:
            chess_game = chess.pgn.read_game(StringIO(game.pgn))
        except Exception:
            return full
        if not chess_game:
            return full
        resolved: Dict[str, List[Dict[str, Any]]] = {}
        for path_key, entries in full.items():
            path = decode_path(path_key)
            if path is None or node_at_path(chess_game, path) is None:
                preset_set = sorted({e.get("preset", "") for e in (entries or [])})
                LoggingService.get_instance().warning(
                    f"Chess Log orphan path_key skipped on load: "
                    f"game#{getattr(game, 'game_number', '?')}, "
                    f"path_key={path_key!r}, presets={preset_set}, "
                    f"entries={len(entries or [])}"
                )
            else:
                resolved[path_key] = entries
        return resolved

    @staticmethod
    def load_nag_shown(game: GameData) -> bool:
        """Read the nag_shown flag from the CARAChessLog payload.

        Returns False on missing tag, missing key, or any error.  Does not
        re-verify the checksum — callers should call load_tags first if data
        integrity matters; a corrupt tag means load_tags already stripped it.
        """
        if game is None or not hasattr(game, "pgn") or game.pgn is None:
            return False
        try:
            chess_game = chess.pgn.read_game(StringIO(game.pgn))
            if not chess_game or ChessLogStorageService.TAG_NAME not in chess_game.headers:
                return False
            encoded = chess_game.headers[ChessLogStorageService.TAG_NAME]
            json_text = decode_and_decompress_to_str(encoded)
            payload = json.loads(json_text)
            return bool(payload.get("nag_shown", False))
        except Exception:
            return False

    @staticmethod
    def store_tags(
        game: GameData,
        paths_data: Dict[str, List[Dict[str, Any]]],
        config: Optional[Dict[str, Any]] = None,
        nag_shown: bool = False,
        original_paths: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> bool:
        """Store Chess Log moments into game PGN (in-memory). Returns True on success.

        If ``original_paths`` is provided, any path_key that is (a) new — not present
        in ``original_paths`` — AND (b) does not resolve to a node in the game's current
        move tree is refused and logged at ERROR.  Pre-existing orphan keys (present in
        ``original_paths`` even if they no longer resolve) pass through untouched so that
        historical data is never silently destroyed.  When ``original_paths`` is None the
        guard is not applied (backward-compatible behaviour).
        """
        if game is None or not hasattr(game, "pgn") or game.pgn is None:
            return False
        try:
            chess_game = chess.pgn.read_game(StringIO(game.pgn))
            if not chess_game:
                return False
            if original_paths is not None:
                filtered: Dict[str, List[Dict[str, Any]]] = {}
                for pk, entries in paths_data.items():
                    if pk in original_paths:
                        filtered[pk] = entries  # pre-existing: always passthrough
                    else:
                        path = decode_path(pk)
                        if path is not None and node_at_path(chess_game, path) is not None:
                            filtered[pk] = entries
                        else:
                            preset_set = sorted({e.get("preset", "") for e in (entries or [])})
                            LoggingService.get_instance().error(
                                f"Chess Log refusing new orphan path_key on save: "
                                f"game#{getattr(game, 'game_number', '?')}, "
                                f"path_key={pk!r}, presets={preset_set}"
                            )
                paths_data = filtered
            payload: Dict[str, Any] = {"_v": 1, "paths": paths_data}
            if nag_shown:
                payload["nag_shown"] = True
            json_text = json.dumps(payload, ensure_ascii=False)
            data_bytes = json_text.encode("utf-8")
            checksum = compute_checksum(data_bytes)
            encoded = compress_and_encode_from_str(json_text, compresslevel=9)
            app_version = (config or {}).get("version", "1.0")
            info_str = (
                f"App Version: {app_version}, "
                f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            chess_game.headers[ChessLogStorageService.TAG_NAME] = encoded
            chess_game.headers[ChessLogStorageService.TAG_INFO] = info_str
            chess_game.headers[ChessLogStorageService.TAG_CHECKSUM] = checksum
            has_tags = ChessLogStorageService.count_tags(paths_data) > 0
            game.pgn = PgnService.export_game_to_pgn(chess_game)
            game.has_chess_log_tags = has_tags
            return True
        except Exception as e:
            LoggingService.get_instance().error(
                f"Error storing Chess Log tags: {e}", exc_info=e
            )
            return False

    @staticmethod
    def clear_tags(game: GameData) -> bool:
        """Remove CARAChessLog* tags from game PGN (in-memory)."""
        if game is None or not hasattr(game, "pgn") or game.pgn is None:
            return False
        ChessLogStorageService._remove_chess_log_tags(game)  # also removes chip from header
        game.has_chess_log_tags = False
        return True

    @staticmethod
    def count_tags(paths_data: Dict[str, List[Dict[str, Any]]]) -> int:
        """Count distinct moments (non-empty path keys) — NOT total entries.

        One path = one moment, even if it carries multiple entries
        (e.g. CCT with two letters selected on the same moment).
        """
        return sum(1 for entries in paths_data.values() if entries)

    @staticmethod
    def make_entry(
        preset: str,
        cat: str,
        why: str = "",
        ignore_shallow: bool = False,
        is_shallow: bool = False,
        is_vague: bool = False,
        ignore_text_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a single moment entry dict with a new UUID and UTC timestamp."""
        entry: Dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "preset": preset,
            "cat": cat,
            "why": why,
            "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if ignore_shallow:
            entry["ignore_shallow"] = True
        if is_shallow:
            entry["is_shallow"] = True
        if is_vague:
            entry["is_vague"] = True
        if ignore_text_hash:
            entry["ignore_text_hash"] = ignore_text_hash
        return entry

    @staticmethod
    def _remove_chess_log_tags(game: GameData) -> None:
        """Remove CARAChessLog* tags from game PGN (in-memory, best-effort)."""
        try:
            chess_game = chess.pgn.read_game(StringIO(game.pgn))
            if not chess_game:
                return
            for key in (
                ChessLogStorageService.TAG_NAME,
                ChessLogStorageService.TAG_INFO,
                ChessLogStorageService.TAG_CHECKSUM,
            ):
                if key in chess_game.headers:
                    del chess_game.headers[key]
            game.pgn = PgnService.export_game_to_pgn(chess_game)
            # Sync Python-side attributes for immediate in-session UI consistency.
            from app.utils.game_tags_utils import parse_game_tags, tags_display_text
            new_raw = chess_game.headers.get("CARAGameTags", "")
            game.game_tags_raw = new_raw
            game.game_tags = tags_display_text(parse_game_tags(new_raw))
        except Exception as e:
            LoggingService.get_instance().warning(f"Chess Log tag cleanup failed: {e}")
